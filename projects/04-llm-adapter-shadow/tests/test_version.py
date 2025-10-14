import importlib


def test_version_constant() -> None:
    module = importlib.import_module("llm_adapter")
    assert module.__version__ == "0.1.0"
