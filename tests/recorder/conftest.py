import pytest
from rec_helpers import ProviderState, register, unregister


@pytest.fixture
def provider():
    state = ProviderState()
    register(state)
    yield state
    unregister()
