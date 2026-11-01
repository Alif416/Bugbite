import threading
from decimal import Decimal

import pytest
from adapter_contract import AdapterContract
from chain_helpers import names
from claude_helpers import HAIKU_PRICING, adapter_for as claude_adapter_for
from claude_helpers import message, model as claude_model, text as claude_text, tool_use as claude_tool_use
from openai_helpers import adapter_for as openai_adapter_for
from openai_helpers import completion, tool_call

from bugbite.adapter import (
    ClaudeAdapter,
    CostLedger,
    GenerationRequest,
    Message,
    MeteredAdapter,
    Usage,
    create_adapter,
    worst_case_cost,
)
from bugbite.adapter.testing import ScriptedAdapter, text_response, tool_call_response
from bugbite.config import Pricing
from bugbite.errors import INVALID_REQUEST, RATE_LIMITED_MODEL, SERVER_ERROR_MODEL, AdapterError

D = Decimal
REQUEST = GenerationRequest(messages=(Message.user("hi"),))


def paid_config(name="haiku"):
    return claude_model(name=name)


def scripted(script, name="haiku"):
    return ScriptedAdapter(paid_config(name), script)


# -- recording ---------------------------------------------------------------------------------


def test_a_call_is_recorded_with_its_tokens_tier_and_cost():
    ledger = CostLedger()
    adapter = MeteredAdapter(scripted([text_response("hi", usage=Usage(1000, 200, 5000, 400))]), ledger)
    adapter.generate(REQUEST)
    (record,) = ledger.calls
    assert record.model == "haiku" and record.cost.total_usd == D("0.0003") and record.cost.tier == "standard"
    assert record.stop_reason == "end_turn" and not record.failed
    assert adapter.last_call is record and ledger.total_usd == D("0.0003")


def test_the_response_comes_back_as_the_very_same_object():
    response = text_response("same object")
    adapter = MeteredAdapter(scripted([response]), CostLedger())
    assert adapter.generate(REQUEST) is response


def test_a_long_prompt_call_is_priced_on_the_long_card():
    ledger = CostLedger()
    MeteredAdapter(scripted([text_response("x", usage=Usage(100_001, 1000))]), ledger).generate(REQUEST)
    assert ledger.calls[0].cost.tier == "long_prompt" and ledger.total_usd == D("0.0525005")


def test_estimated_usage_is_flagged_in_the_record():
    from bugbite.adapter import GenerationResponse, TextBlock

    estimated = GenerationResponse(blocks=(TextBlock("x"),), stop_reason="end_turn", usage=Usage(10, 5), model="m", usage_estimated=True)
    ledger = CostLedger()
    MeteredAdapter(scripted([estimated]), ledger).generate(REQUEST)
    assert ledger.calls[0].cost.estimated is True and ledger.totals().estimated_calls == 1


def test_a_free_model_logs_tokens_and_time_with_cost_zero():
    ledger = CostLedger()
    free = ScriptedAdapter(None, [text_response("x", usage=Usage(500, 50))])
    MeteredAdapter(free, ledger).generate(REQUEST)
    record = ledger.calls[0]
    assert record.cost.free and record.cost.total_usd == 0
    assert record.usage.total == 550 and record.latency_s >= 0


# -- failures -------------------------------------------------------------------------------------


def test_a_provider_failure_is_recorded_and_the_same_error_is_re_raised():
    error = AdapterError(RATE_LIMITED_MODEL, "slow down", retry_after_s=3, status_code=429)
    ledger = CostLedger()
    adapter = MeteredAdapter(scripted([error, text_response("ok")]), ledger)
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert info.value is error
    adapter.generate(REQUEST)
    failed, ok = ledger.calls
    assert failed.failed and failed.error_code == "rate_limited" and failed.cost is None and failed.usage is None
    assert not ok.failed and ledger.totals().failed_calls == 1


@pytest.mark.parametrize("code, status", [(SERVER_ERROR_MODEL, 503), (INVALID_REQUEST, 400), ("timeout", None), ("network_error", None)])
def test_failures_that_involved_the_provider_are_recorded(code, status):
    ledger = CostLedger()
    with pytest.raises(AdapterError):
        MeteredAdapter(scripted([AdapterError(code, "failed", status_code=status)]), ledger).generate(REQUEST)
    assert ledger.totals().failed_calls == 1


def test_a_request_refused_locally_is_not_a_call():
    ledger = CostLedger()
    adapter = MeteredAdapter(scripted([text_response("never used")]), ledger)
    with pytest.raises(AdapterError) as info:
        adapter.generate(GenerationRequest(messages=()))  # the adapter rejects this before sending anything
    assert info.value.code == INVALID_REQUEST
    assert ledger.calls == () and adapter.last_call is None


def test_a_local_refusal_by_the_claude_adapter_is_not_recorded_but_a_providers_400_is():
    ledger = CostLedger()
    claude, rec = claude_adapter_for(message())
    metered = MeteredAdapter(claude, ledger)
    with pytest.raises(AdapterError):
        metered.generate(GenerationRequest(messages=(Message.user("x"),), temperature=0.5))
    assert rec.requests == [] and ledger.calls == ()

    import httpx2

    bad, _ = claude_adapter_for(httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}))
    with pytest.raises(AdapterError):
        MeteredAdapter(bad, ledger).generate(REQUEST)
    assert ledger.totals().failed_calls == 1  # this one reached the provider


def test_a_bug_in_the_adapter_passes_through_unrecorded():
    class Broken(ScriptedAdapter):
        def generate(self, request):
            raise RuntimeError("a bug, not a provider failure")

    ledger = CostLedger()
    with pytest.raises(RuntimeError):
        MeteredAdapter(Broken(paid_config(), []), ledger).generate(REQUEST)
    assert ledger.calls == ()


# -- sharing and delegation -----------------------------------------------------------------------------


def test_one_ledger_shared_by_two_models_keeps_separate_totals():
    ledger = CostLedger()
    paid = MeteredAdapter(scripted([text_response("a", usage=Usage(100_000, 0))], name="haiku"), ledger)
    free = MeteredAdapter(ScriptedAdapter(None, [text_response("b", usage=Usage(500, 50))]), ledger)
    paid.generate(REQUEST)
    free.generate(REQUEST)
    by_model = ledger.by_model()
    assert by_model["haiku"].cost_usd == D("0.01") and by_model["scripted"].cost_usd == 0
    assert ledger.total_usd == D("0.01")


def test_the_wrapper_looks_like_the_adapter_it_wraps():
    inner = scripted([])
    adapter = MeteredAdapter(inner, CostLedger())
    assert adapter.name == "haiku" and adapter.config is inner.config and adapter.inner is inner
    assert adapter.estimate_tokens(REQUEST) == inner.estimate_tokens(REQUEST)
    assert adapter.resolve_max_output_tokens(REQUEST) == inner.config.max_output_tokens


def test_close_reaches_the_inner_adapter_when_it_has_one():
    claude, _ = claude_adapter_for(message())
    MeteredAdapter(claude, CostLedger()).close()
    assert claude._client.is_closed()
    MeteredAdapter(scripted([]), CostLedger()).close()  # an adapter with nothing to close is fine


def test_concurrent_calls_are_all_recorded():
    ledger = CostLedger()
    adapter = MeteredAdapter(scripted([text_response("x", usage=Usage(1000, 200)) for _ in range(100)]), ledger)
    threads = [threading.Thread(target=lambda: [adapter.generate(REQUEST) for _ in range(10)]) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ledger.calls) == 100 and ledger.total_usd == D("0.0002") * 100


# -- worst case ---------------------------------------------------------------------------------------------------


def test_worst_case_cost_uses_the_models_pricing_and_output_allowance():
    adapter = MeteredAdapter(scripted([]), CostLedger())
    expected = worst_case_cost(HAIKU_PRICING, adapter.estimate_tokens(REQUEST), 2048)
    assert adapter.worst_case_cost(REQUEST) == expected > 0
    assert adapter.worst_case_cost(REQUEST, margin=2) > expected
    long_request = GenerationRequest(messages=(Message.user("word " * 5000),), max_output_tokens=100)
    assert adapter.worst_case_cost(long_request) == worst_case_cost(HAIKU_PRICING, adapter.estimate_tokens(long_request), 100)


def test_worst_case_for_a_free_model_is_zero():
    assert MeteredAdapter(ScriptedAdapter(None, []), CostLedger()).worst_case_cost(REQUEST) == 0


# -- create_adapter ---------------------------------------------------------------------------------------------------


def test_create_adapter_wraps_when_given_a_ledger():
    ledger = CostLedger()
    adapter = create_adapter(claude_model(), api_key="sk-ant-x", ledger=ledger)
    try:
        assert isinstance(adapter, MeteredAdapter) and adapter.ledger is ledger
        assert names(adapter) == ["MeteredAdapter", "PrivacyGuardAdapter", "ClaudeAdapter"]
    finally:
        adapter.close()


def test_create_adapter_without_a_ledger_returns_the_plain_adapter():
    adapter = create_adapter(claude_model(), api_key="sk-ant-x")
    try:
        assert names(adapter) == ["PrivacyGuardAdapter", "ClaudeAdapter"]  # no metering without a ledger
    finally:
        adapter.close()


# -- the shared contract ---------------------------------------------------------------------------------------------------


class TestMeteredScriptedContract(AdapterContract):
    def adapter_for_text(self):
        return MeteredAdapter(ScriptedAdapter(None, [text_response("Hello there!")] * 10), CostLedger())

    def adapter_for_tool_call(self):
        return MeteredAdapter(ScriptedAdapter(None, [tool_call_response(("read_file", {"path": "a.py"}))] * 10), CostLedger())


class TestMeteredOpenAICompatibleContract(AdapterContract):
    def adapter_for_text(self):
        adapter, _ = openai_adapter_for(completion("Hello there!"))
        return MeteredAdapter(adapter, CostLedger())

    def adapter_for_tool_call(self):
        adapter, _ = openai_adapter_for(completion(None, [tool_call("read_file", '{"path": "a.py"}')], finish="tool_calls"))
        return MeteredAdapter(adapter, CostLedger())


class TestMeteredClaudeContract(AdapterContract):
    def adapter_for_text(self):
        adapter, _ = claude_adapter_for(message([claude_text("Hello there!")]))
        return MeteredAdapter(adapter, CostLedger())

    def adapter_for_tool_call(self):
        adapter, _ = claude_adapter_for(message([claude_tool_use("read_file", {"path": "a.py"})], stop_reason="tool_use"))
        return MeteredAdapter(adapter, CostLedger())


# -- a realistic run -----------------------------------------------------------------------------------------------------------


def agent_run(cached: bool):
    """Twenty agent steps with a 20,000-token prompt that mostly repeats from step to step."""
    ledger = CostLedger()
    script = []
    for step in range(20):
        if cached:
            usage = Usage(input_tokens=300, output_tokens=400, cache_read_tokens=0 if step == 0 else 20_000, cache_write_tokens=20_000 if step == 0 else 500)
        else:
            usage = Usage(input_tokens=20_300, output_tokens=400)
        script.append(text_response("step", usage=usage))
    adapter = MeteredAdapter(scripted(script), ledger)
    for _ in range(20):
        adapter.generate(REQUEST)
    return ledger


def test_a_twenty_step_run_costs_far_less_than_the_per_issue_cap_and_caching_helps():
    cap = D("0.10")  # config/models.yaml per_issue_cap_usd for Haiku
    cached, uncached = agent_run(True), agent_run(False)
    assert cached.total_usd < D("0.02") < cap
    assert uncached.total_usd < cap  # even without caching a 20-step Haiku run fits the cap at these prices
    assert cached.total_usd * 3 < uncached.total_usd  # caching makes it more than three times cheaper
    assert cached.calls[0].cost.cache_write_usd > 0 and cached.calls[5].cost.cache_read_usd > 0
