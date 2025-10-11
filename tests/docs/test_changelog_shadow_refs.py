from __future__ import annotations

from pathlib import Path


def test_shadow_refs_limited_to_migration_section() -> None:
    changelog_lines = Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines()

    current_section = None
    migration_section = "### Migration"
    occurrences: list[tuple[int, str | None, str]] = []

    for index, line in enumerate(changelog_lines, start=1):
        stripped = line.strip()
        if stripped.startswith("### "):
            current_section = stripped
        if "04-llm-adapter-shadow" in line:
            occurrences.append((index, current_section, stripped))
            assert (
                current_section == migration_section
            ), f"shadow 参照が移行履歴以外で検出されました: 行 {index}"

    assert (
        occurrences
    ), "移行履歴に旧 `projects/04-llm-adapter-shadow` の記録がありません"
