"""The guard at the model boundary, and the proof that nothing reaches a model around it."""

import itertools

import pytest
from chain_helpers import names, raw
from claude_helpers import KEY
from text_action_helpers import READ_FILE, action

from bugbite.adapter import (
    CostLedger,
    GenerationRequest,
    Message,
    PrivacyGuardAdapter,
    create_adapter,
    register_adapter,
    unregister_adapter,
)
from bugbite.adapter.testing import ScriptedAdapter, text_response
from bugbite.config import ModelConfig, Pricing, load_models_config
from bugbite.errors import PRIVATE_CODE_BLOCKED, AdapterError, PrivacyError
from bugbite.privacy import Sensitivity, may_receive

PLAIN = GenerationRequest(messages=(Message.user("hi"),))
WITH_TOOLS = GenerationRequest(messages=(Message.user("hi"),), tools=(READ_FILE,))
ALL = list(Sensitivity)


def config(allow, native=True, provider="fake_privacy", name=None):
    return ModelConfig(
        name or f"{provider}-{'open' if allow else 'closed'}", provider, "http://x", "m", 100_000, native,
        Pricing.free(), 0, allow,
    )  # fmt: skip


def scripted(allow=False, steps=None):
    return ScriptedAdapter(config(allow), steps if steps is not None else [text_response("fine")] * 20)


# -- the guard itself -----------------------------------------------------------------------------------


def test_a_forbidden_call_never_reaches_the_inner_adapter():
    inner = scripted(allow=False)
    guard = PrivacyGuardAdapter(inner, Sensitivity.PRIVATE)
    for request in (PLAIN, WITH_TOOLS, GenerationRequest(messages=())):  # even an invalid request: policy first
        with pytest.raises(PrivacyError) as info:
            guard.generate(request)
        assert info.value.code == PRIVATE_CODE_BLOCKED
    assert inner.calls == [] and inner.remaining == 20


def test_the_refusal_names_the_model_and_the_sensitivity_and_no_request_content():
    guard = PrivacyGuardAdapter(scripted(False), Sensitivity.PRIVATE)
    secret = GenerationRequest(messages=(Message.user("TOPSECRET-SOURCE-CODE"),))
    with pytest.raises(PrivacyError) as info:
        guard.generate(secret)
    assert "fake_privacy-closed" in info.value.message and "private" in info.value.message
    assert "TOPSECRET" not in info.value.message and "config/models.yaml" in info.value.message


@pytest.mark.parametrize("allow, sensitivity", [(a, s) for a, s in itertools.product([True, False], ALL) if may_receive(config(a), s)])
def test_an_allowed_call_passes_through_and_returns_the_same_object(allow, sensitivity):
    response = text_response("through")
    guard = PrivacyGuardAdapter(scripted(allow, [response]), sensitivity)
    assert guard.generate(PLAIN) is response


def test_inner_errors_propagate_unchanged():
    error = AdapterError("rate_limited", "slow", status_code=429)
    with pytest.raises(AdapterError) as info:
        PrivacyGuardAdapter(scripted(True, [error]), Sensitivity.PRIVATE).generate(PLAIN)
    assert info.value is error


def test_the_guard_looks_like_the_adapter_it_wraps():
    inner = scripted(True)
    guard = PrivacyGuardAdapter(inner, Sensitivity.PUBLIC)
    assert guard.name == inner.name and guard.config is inner.config and guard.inner is inner
    assert guard.estimate_tokens(PLAIN) == inner.estimate_tokens(PLAIN)
    guard.close()


def test_close_reaches_the_inner_adapter():
    class Closable(ScriptedAdapter):
        closed = False

        def close(self):
            self.closed = True

    inner = Closable(config(True), [])
    PrivacyGuardAdapter(inner, Sensitivity.PRIVATE).close()
    assert inner.closed


@pytest.mark.parametrize("bad", [None, "private", "public", "sandbox", 1, True])
def test_the_sensitivity_is_required_and_must_be_a_sensitivity(bad):
    with pytest.raises(TypeError):
        PrivacyGuardAdapter(scripted(True), bad)
    with pytest.raises(TypeError):
        PrivacyGuardAdapter(scripted(True))  # type: ignore[call-arg]


def test_there_is_no_environment_or_argument_switch():
    import inspect

    assert list(inspect.signature(PrivacyGuardAdapter).parameters) == ["inner", "sensitivity"]
    with pytest.MonkeyPatch.context() as mp:
        for name in ("BUGBITE_ALLOW_PRIVATE", "BUGBITE_DISABLE_PRIVACY", "PRIVACY_OFF", "FORCE"):
            mp.setenv(name, "1")
        with pytest.raises(PrivacyError):
            PrivacyGuardAdapter(scripted(False), Sensitivity.PRIVATE).generate(PLAIN)


# -- create_adapter: the matrix ---------------------------------------------------------------------------------------


@pytest.fixture
def fake_provider():
    built = {}

    def factory(cfg, key):
        reply = action("read_file", path="a.py") if not cfg.native_tool_calling else "plain"
        built[cfg.name] = ScriptedAdapter(cfg, [text_response(reply)] * 20)
        return built[cfg.name]

    register_adapter("fake_privacy", factory)
    yield built
    unregister_adapter("fake_privacy")


def ask(adapter, native):
    return adapter.generate(PLAIN if native else WITH_TOOLS)


@pytest.mark.parametrize("ledger_on", [False, True])
@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("sensitivity", ALL)
@pytest.mark.parametrize("allow", [True, False])
def test_the_raw_adapter_is_called_if_and_only_if_the_policy_allows_it(fake_provider, allow, sensitivity, native, ledger_on):
    cfg = config(allow, native=native, name="m")
    ledger = CostLedger() if ledger_on else None
    adapter = create_adapter(cfg, ledger=ledger, sensitivity=sensitivity)
    if may_receive(cfg, sensitivity):
        ask(adapter, native)
        assert len(fake_provider["m"].calls) == 1  # exactly one model call, no repairs needed
        assert (ledger is None) or len(ledger.calls) == 1
    else:
        with pytest.raises(PrivacyError):
            ask(adapter, native)
        assert fake_provider["m"].calls == []  # nothing was sent
        assert (ledger is None) or ledger.calls == ()  # and a refusal is not a model call
        if not native:
            assert adapter.stats.steps == 0  # the text-action wrapper did not even count a step, let alone repair


def test_the_default_sensitivity_is_private(fake_provider):
    closed = create_adapter(config(False, name="closed"))
    with pytest.raises(PrivacyError):
        closed.generate(PLAIN)
    assert fake_provider["closed"].calls == []
    assert create_adapter(config(True, name="open")).generate(PLAIN)  # a model that may take private code is fine


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("ledger_on", [False, True])
def test_the_guard_is_the_innermost_wrapper(fake_provider, native, ledger_on):
    adapter = create_adapter(config(False, native=native, name="m"), ledger=CostLedger() if ledger_on else None, sensitivity=Sensitivity.PUBLIC)
    order = names(adapter)
    assert order[-1] == "ScriptedAdapter" and order[-2] == "PrivacyGuardAdapter"  # the guard sits right above the raw adapter
    assert order.count("PrivacyGuardAdapter") == 1
    assert raw(adapter) is fake_provider["m"]
    assert ("TextActionAdapter" in order) is (not native) and ("MeteredAdapter" in order) is ledger_on


def test_a_repair_cannot_get_past_the_guard(fake_provider):
    # a closed model on private data: the text-action wrapper's first call is refused, so no repair is attempted
    adapter = create_adapter(config(False, native=False, name="m"), sensitivity=Sensitivity.PRIVATE)
    with pytest.raises(PrivacyError):
        adapter.generate(WITH_TOOLS)
    assert fake_provider["m"].calls == [] and adapter.stats.repaired_steps == 0


def test_sandbox_and_public_data_reach_a_closed_model(fake_provider):
    for sensitivity in (Sensitivity.PUBLIC, Sensitivity.SANDBOX):
        adapter = create_adapter(config(False, name=f"closed-{sensitivity.value}"), sensitivity=sensitivity)
        assert adapter.generate(PLAIN).text == "plain"


def test_a_real_provider_adapter_is_guarded_too():
    haiku = load_models_config("config/models.yaml")["haiku"]
    guarded = create_adapter(haiku, api_key=KEY)  # default sensitivity: private
    try:
        with pytest.raises(PrivacyError):
            guarded.generate(PLAIN)  # refused before any HTTP request is made
    finally:
        guarded.close()
    public = create_adapter(haiku, api_key=KEY, sensitivity=Sensitivity.PUBLIC)
    try:
        assert names(public) == ["PrivacyGuardAdapter", "ClaudeAdapter"]
    finally:
        public.close()
