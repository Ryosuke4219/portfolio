from pathlib import Path


def test_python_targets_point_to_primary_project() -> None:
    justfile = Path(__file__).resolve().parents[2] / "justfile"
    content = justfile.read_text(encoding="utf-8")

    assert "projects/04-llm-adapter/tests" in content
    assert "projects/04-llm-adapter/adapter" in content
    assert "projects/04-llm-adapter-shadow" not in content
