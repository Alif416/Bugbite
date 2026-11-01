import json
import threading
from decimal import Decimal

import pytest
from claude_helpers import HAIKU_PRICING

from bugbite.adapter import CostLedger, GenerationResponse, TextBlock, Usage, compute_cost
from bugbite.errors import RATE_LIMITED_MODEL, SERVER_ERROR_MODEL, AdapterError

D = Decimal


def response(usage=None, request_id="req_1", stop="end_turn", latency=0.5, estimated=False):
    return GenerationResponse(
        blocks=(TextBlock("x"),), stop_reason=stop, usage=usage or Usage(input_tokens=1000, output_tokens=200),
        model="m", latency_s=latency, request_id=request_id, usage_estimated=estimated,
    )  # fmt: skip


def add(ledger, model="haiku", usage=None, **kw):
    r = response(usage, **kw)
    return ledger.record_success(model, r, compute_cost(HAIKU_PRICING, r.usage, estimated=r.usage_estimated))


def test_an_empty_ledger():
    ledger = CostLedger()
    assert ledger.calls == () and ledger.total_usd == 0 and ledger.by_model() == {}
    totals = ledger.totals()
    assert (totals.calls, totals.failed_calls, totals.estimated_calls, totals.cost_usd) == (0, 0, 0, 0)


def test_records_are_numbered_from_one_and_carry_the_call_details():
    ledger = CostLedger(clock=lambda: 1234.5)
    first = add(ledger, request_id="req_a", stop="tool_use", latency=1.25)
    second = add(ledger)
    assert (first.index, second.index) == (1, 2)
    assert (first.model, first.request_id, first.stop_reason, first.latency_s, first.at) == ("haiku", "req_a", "tool_use", 1.25, 1234.5)
    assert first.usage.input_tokens == 1000 and first.cost.total_usd == D("0.0002") and not first.failed


def test_totals_add_up_exactly():
    ledger = CostLedger()
    for _ in range(3):
        add(ledger, usage=Usage(input_tokens=1000, output_tokens=200, cache_read_tokens=5000, cache_write_tokens=400))
    totals = ledger.totals()
    assert ledger.total_usd == totals.cost_usd == D("0.0009")
    assert (totals.calls, totals.input_tokens, totals.output_tokens, totals.cache_read_tokens, totals.cache_write_tokens) == (3, 3000, 600, 15000, 1200)


def test_failed_calls_are_recorded_without_inventing_a_cost():
    ledger = CostLedger()
    add(ledger)
    record = ledger.record_failure("haiku", AdapterError(RATE_LIMITED_MODEL, "slow down", status_code=429), 0.4)
    assert record.failed and record.error_code == "rate_limited" and record.cost is None and record.usage is None
    totals = ledger.totals()
    assert (totals.calls, totals.failed_calls) == (2, 1)
    assert totals.cost_usd == D("0.0002") and totals.latency_s == pytest.approx(0.9)


def test_estimated_calls_are_counted_and_still_priced():
    ledger = CostLedger()
    add(ledger, estimated=True)
    add(ledger)
    totals = ledger.totals()
    assert totals.estimated_calls == 1 and totals.cost_usd == D("0.0004")


def test_totals_are_kept_per_model():
    ledger = CostLedger()
    add(ledger, "haiku", usage=Usage(input_tokens=1_000_000 // 10, output_tokens=0))
    add(ledger, "free-model", usage=Usage(input_tokens=500, output_tokens=50))
    ledger.record_failure("free-model", AdapterError(SERVER_ERROR_MODEL, "down", status_code=503), 0.1)
    by_model = ledger.by_model()
    assert set(by_model) == {"haiku", "free-model"}
    assert by_model["haiku"].cost_usd == D("0.01") and by_model["haiku"].calls == 1
    assert by_model["free-model"].calls == 2 and by_model["free-model"].failed_calls == 1
    assert ledger.total_usd == sum((t.cost_usd for t in by_model.values()), D(0))


def test_the_ledger_enforces_no_cap_whatever_the_total():
    ledger = CostLedger()
    for _ in range(50):
        add(ledger, usage=Usage(input_tokens=90_000, output_tokens=4000))
    assert ledger.total_usd > D("0.5")  # far above any per-issue cap; nothing was raised


def test_calls_returns_a_copy():
    ledger = CostLedger()
    add(ledger)
    calls = ledger.calls
    assert isinstance(calls, tuple) and len(ledger.calls) == 1
    add(ledger)
    assert len(calls) == 1 and len(ledger.calls) == 2


def test_snapshot_is_json_safe_with_money_as_text():
    ledger = CostLedger()
    add(ledger, usage=Usage(input_tokens=1000, output_tokens=200, cache_read_tokens=5000, cache_write_tokens=400))
    ledger.record_failure("haiku", AdapterError(RATE_LIMITED_MODEL, "x", status_code=429), 0.2)
    snapshot = json.loads(json.dumps(ledger.snapshot()))
    assert snapshot["total"]["cost_usd"] == "0.0003" and snapshot["total"]["calls"] == 2 and snapshot["total"]["failed_calls"] == 1
    assert snapshot["by_model"]["haiku"]["cost_usd"] == "0.0003"
    ok, failed = snapshot["calls"]
    assert ok["cost"]["total_usd"] == "0.0003" and ok["cost"]["tier"] == "standard"
    assert ok["usage"] == {"input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 5000, "cache_write_tokens": 400}
    assert failed["error_code"] == "rate_limited" and failed["cost"] is None and failed["usage"] is None


def test_concurrent_recording_loses_nothing():
    ledger = CostLedger()
    usage = Usage(input_tokens=1000, output_tokens=200)

    def work():
        for _ in range(50):
            add(ledger, usage=usage)

    threads = [threading.Thread(target=work) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ledger.calls) == 2000 and ledger.total_usd == D("0.0002") * 2000
    assert sorted(c.index for c in ledger.calls) == list(range(1, 2001))
