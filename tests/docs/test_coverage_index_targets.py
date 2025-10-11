from pathlib import Path


def test_coverage_index_excludes_shadow_project() -> None:
    index_html = Path("docs/reports/coverage/index.html").read_text(encoding="utf-8")
    assert (
        "projects/04-llm-adapter-shadow" not in index_html
    ), "Coverage index still lists shadow project targets."
