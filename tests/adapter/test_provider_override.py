"""`create_adapter(provider_adapter=...)`: the replayer puts its stand-in where the real provider adapter goes (AD-124)."""

import pytest
from chain_helpers import names, raw

from bugbite.adapter import CostLedger, GenerationRequest, Message, Usage, create_adapter, registered_providers
from bugbite.adapter.testing import ScriptedAdapter, text_response
from bugbite.config import ConfigError, ModelConfig, Pricing
from bugbite.privacy import Sensitivity

MODEL = ModelConfig("m", "not_registered", "http://x", "m", 100_000, True, Pricing.of(1, 2), 0.0, True, api_key_env="SOME_KEY")


class Sink:
    record_requests = False

    def __init__(self):
        self.events = []

    def next_call_number(self):
        return 1

    def write(self, event):
        self.events.append(event)
        return True

    def note_error(self, exc):
        pass


def test_a_given_provider_needs_no_registered_factory_and_no_key():
    assert "not_registered" not in registered_providers()
    stand_in = ScriptedAdapter(MODEL, [text_response("hi", usage=Usage(1, 1))])
    adapter = create_adapter(MODEL, provider_adapter=stand_in)  # no api_key although the model names a key variable
    assert raw(adapter) is stand_in
    assert adapter.generate(GenerationRequest(messages=(Message.user("x"),))).text == "hi"


def test_the_other_layers_are_still_the_real_ones_around_it():
    stand_in = ScriptedAdapter(MODEL, [])
    adapter = create_adapter(MODEL, ledger=CostLedger(), sensitivity=Sensitivity.PUBLIC, recorder=Sink(), provider_adapter=stand_in)
    assert names(adapter) == ["MeteredAdapter", "PrivacyGuardAdapter", "RecordingAdapter", "ScriptedAdapter"]
    text_model = ModelConfig("t", "not_registered", "http://x", "m", 100_000, False, Pricing.free(), 0.0, True)
    wrapped = create_adapter(text_model, provider_adapter=ScriptedAdapter(text_model, []))
    assert names(wrapped) == ["TextActionAdapter", "PrivacyGuardAdapter", "ScriptedAdapter"]


def test_without_a_provider_the_old_rules_still_apply():
    with pytest.raises(ConfigError, match="no adapter is registered"):
        create_adapter(MODEL, api_key="k")
