import importlib


def test_version_constant() -> None:
    module = importlib.import_module("src.llm_adapter")
    assert module.__version__ == "0.1.0"
