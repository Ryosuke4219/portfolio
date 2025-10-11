from __future__ import annotations

from pathlib import Path


def test_shadow_tasks_doc_has_no_shadow_dependency_paths() -> None:
    content = Path("docs/tasks/llm_adapter_shadow_v0.2_tasks.md").read_text(encoding="utf-8")

    assert (
        "projects/04-llm-adapter-shadow" not in content
    ), "docs/tasks/llm_adapter_shadow_v0.2_tasks.md から Shadow 依存パスを除去してください"
