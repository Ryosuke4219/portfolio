import importlib


def test_version_constant() -> None:
    module = importlib.import_module("llm_adapter")
    assert module.__version__ == "0.1.0"


def test_src_namespace_alias() -> None:
    module = importlib.import_module("llm_adapter")
    src_module = importlib.import_module("src.llm_adapter")
    assert module is src_module
