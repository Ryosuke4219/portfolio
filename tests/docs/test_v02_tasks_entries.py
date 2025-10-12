"""docs/spec/v0.2/TASKS.md の整合性検証テスト。"""

from pathlib import Path


TASKS_PATH = Path("docs/spec/v0.2/TASKS.md")


def _load_tasks_markdown() -> str:
    return TASKS_PATH.read_text(encoding="utf-8")


def test_provider_yaml_tasks_reflect_existing_files() -> None:
    """Ollama/OpenRouter の YAML が既存であることをタスクが示しているか。"""

    text = _load_tasks_markdown()
    keywords = ("既存", "現状", "現行", "提供済")

    for provider in ("ollama", "openrouter"):
        config_path = Path(
            f"projects/04-llm-adapter/adapter/config/providers/{provider}.yaml"
        )
        assert config_path.exists(), f"{config_path} が存在しない"

        matching_lines = [
            line for line in text.splitlines() if f"{provider}.yaml" in line
        ]

        assert matching_lines, f"{provider}.yaml を参照する行がタスクリストにない"

        assert any(
            any(keyword in line for keyword in keywords)
            for line in matching_lines
        ), (
            f"{provider}.yaml を参照する行に既存ファイルを示すキーワードが不足"
        )


def test_shadow_dependency_cleanup_task_exists() -> None:
    """Shadow 実装への src.llm_adapter 依存排除タスクが追加されているか。"""

    text = _load_tasks_markdown()
    assert "src.llm_adapter" in text, "Shadow 依存除去タスクが記載されていない"


def test_tasks_markdown_does_not_reference_removed_cli_diagnostics() -> None:
    """非存在の CLI diagnostics テストを参照していないか検証する。"""

    text = _load_tasks_markdown()
    forbidden = "test_cli_single_prompt_diagnostics.py"
    assert forbidden not in text, (
        "存在しない CLI diagnostics テストファイルへの参照を docs/spec/v0.2/TASKS.md "
        "から削除してください"
    )
