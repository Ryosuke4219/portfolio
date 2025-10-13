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


def _assert_task_in_progress_with_todos(
    section: str,
    *,
    required_todos: list[str],
) -> None:
    lines = section.splitlines()
    if not lines:
        pytest.fail("タスク節が空です")

    header = lines[0]
    assert "（進行中）" in header, "タスク見出しが進行中になっていない"

    has_remaining_section = any("残タスク:" in line for line in lines)
    assert has_remaining_section, "残タスクの節が存在しない"

    for todo in required_todos:
        matching = [line for line in lines if todo in line]
        if not matching:
            pytest.fail(f"残タスクに '{todo}' が記載されていない")


def test_task6_section_reflects_completion() -> None:
    section = _load_task_section(6)
    _assert_task_in_progress_with_todos(
        section,
        required_todos=[
            "CLI リテラル API キー経路",
            "ストリーミング透過検証",
        ],
    )


def test_task7_section_marked_completed() -> None:
    section = _load_task_section(7)
    lines = section.splitlines()
    assert lines, "タスク7の節が空です"
    assert "（対応済み）" in lines[0], "タスク7が対応済みとしてマークされていない"
    assert all("残タスク" not in line for line in lines), "完了済み節に残タスクが残っている"
