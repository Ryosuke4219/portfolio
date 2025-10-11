from pathlib import Path

import pytest

from adapter.core.datasets import load_golden_tasks


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_golden_tasks_handles_bom(tmp_path: Path) -> None:
    path = tmp_path / "tasks.jsonl"
    _write_jsonl(
        path,
        [
            '\ufeff{"id": "1", "expected": {}}',
            '{"id": "2", "expected": {}}',
        ],
    )

    tasks = load_golden_tasks(path)

    assert [task.task_id for task in tasks] == ["1", "2"]


def test_load_golden_tasks_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "invalid.jsonl"
    _write_jsonl(
        path,
        [
            '\ufeff{"id": "1", "expected": {}}',
            '{"id": ",",',  # broken JSON
        ],
    )

    with pytest.raises(ValueError) as excinfo:
        load_golden_tasks(path)

    assert f"invalid JSON at {path}:2" == str(excinfo.value)
