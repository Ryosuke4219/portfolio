from pathlib import Path


def test_readme_does_not_reference_shadow_adapter() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "projects/04-llm-adapter-shadow" not in readme
