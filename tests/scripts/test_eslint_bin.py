from __future__ import annotations

from pathlib import Path


def test_eslint_bin_ignored_path_patterns() -> None:
    eslint_bin = Path("packages/eslint/bin/eslint.js")
    content = eslint_bin.read_text(encoding="utf-8")

    expected_pattern = "`${path.sep}projects${path.sep}04-llm-adapter${path.sep}`"
    unexpected_pattern = "`${path.sep}projects${path.sep}04-llm-adapter-shadow${path.sep}`"

    assert expected_pattern in content
    assert unexpected_pattern not in content
