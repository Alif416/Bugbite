import importlib

import pytest

MODULES = [
    "sandbox",
    "retrieval",
    "agent",
    "adapter",
    "verifier",
    "pr_writer",
    "recorder",
    "failure_classifier",
    "evals",
    "trace_store",
    "github",
]


def test_version():
    import bugbite

    assert bugbite.__version__


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    module = importlib.import_module(f"bugbite.{name}")
    assert module.__doc__
