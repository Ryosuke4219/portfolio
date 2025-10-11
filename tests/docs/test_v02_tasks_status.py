"""docs/spec/v0.2/TASKS.md のタスク進捗表示を検証するテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest


TASKS_PATH = Path("docs/spec/v0.2/TASKS.md")


def _load_task_section(task_number: int) -> str:
    text = TASKS_PATH.read_text(encoding="utf-8")
    marker = f"### タスク{task_number}"
    start = text.find(marker)
    if start == -1:
        pytest.fail(f"docs/spec/v0.2/TASKS.md にタスク{task_number}の節が存在しない")

    next_header = text.find("\n### ", start + 1)
    if next_header == -1:
        return text[start:]
    return text[start:next_header]


def _assert_task_completed(section: str, *, test_path: str) -> None:
    lines = section.splitlines()
    if not lines:
        pytest.fail("タスク節が空です")

    header = lines[0]
    assert "（対応済み）" in header, "タスク見出しが対応済みになっていない"

    matching = [line for line in lines if test_path in line]
    if not matching:
        pytest.fail(f"{test_path} を参照する記述が不足している")

    assert all("❌" not in line for line in matching), "品質エビデンスが失敗扱いになっている"
    assert any("✅" in line for line in matching), "品質エビデンスに成功記号がない"


def test_task6_section_reflects_completion() -> None:
    section = _load_task_section(6)
    _assert_task_completed(
        section,
        test_path="projects/04-llm-adapter/tests/providers/test_ollama_provider.py",
    )


def test_task7_section_reflects_completion() -> None:
    section = _load_task_section(7)
    _assert_task_completed(
        section,
        test_path="projects/04-llm-adapter/tests/providers/test_openrouter_provider.py",
    )
