from pathlib import Path


def test_bootstrap_targets_llm_adapter_requirements() -> None:
    script = Path("scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert "projects/04-llm-adapter/requirements.txt" in script
    assert "-shadow" not in script
