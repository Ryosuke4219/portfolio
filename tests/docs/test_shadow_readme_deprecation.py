from pathlib import Path


def test_shadow_readme_has_deprecation_notice() -> None:
    readme_lines = Path("projects/04-llm-adapter-shadow/README.md").read_text(encoding="utf-8").splitlines()
    nonempty_lines = [line for line in readme_lines if line.strip()]
    notice_block = "\n".join(nonempty_lines[:5])

    assert "アーカイブ済み" in notice_block
    assert "最新手順" in notice_block
    assert "04-llm-adapter/README.md" in notice_block
