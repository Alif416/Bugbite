import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recorder"))

import pytest  # noqa: E402
from rec_helpers import ProviderState, register, unregister  # noqa: E402


@pytest.fixture
def provider():
    state = ProviderState()
    register(state)
    yield state
    unregister()
