from llm_adapter import __version__


def test_version_constant() -> None:
    assert __version__ == "0.1.0"
