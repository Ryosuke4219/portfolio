"""04/ROADMAP.md の M3 残タスク検証。"""

from __future__ import annotations

from pathlib import Path

ROADMAP_PATH = Path("04/ROADMAP.md")

EXPECTED_TASKS = [
    "OpenRouter の 429/5xx エラー統計を週次で集計し、バックオフ/RPM 調整の指標に取り込む。",
    "CLI でリテラル指定された OpenRouter API キーが `ProviderRequest.options[\"api_key\"]` まで透過する経路を整備し、ギャップを再現する回帰テストを追加する。",
    "OpenRouter 用の env/CLI マッピングと参照ドキュメントを更新し、`OPENROUTER_API_KEY` などのリテラル指定と必須項目の整合、および `options[\"api_key\"]` 配線手順の明示を保証する。",
]


def _extract_m3_tasks(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("## M3 —"))
    except StopIteration as exc:  # pragma: no cover - ドキュメント構造が崩れた場合に検出
        raise AssertionError("M3 セクションが見つかりません") from exc

    task_header_index = None
    for offset, line in enumerate(lines[start:], start=start):
        if line.strip().startswith("**タスク**"):
            task_header_index = offset
            break
    if task_header_index is None:
        raise AssertionError("M3 セクションにタスク見出しがありません")

    tasks: list[str] = []
    for line in lines[task_header_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            break
        if not stripped.startswith("-"):
            break
        task_body = stripped.lstrip("-").strip()
        tasks.append(task_body)
    return tasks


def test_m3_tasks_are_in_sync_with_implementation() -> None:
    markdown = ROADMAP_PATH.read_text(encoding="utf-8")
    tasks = _extract_m3_tasks(markdown)
    assert tasks == EXPECTED_TASKS, (
        "M3 の残タスクが実装状況とずれています。"
        f"\n期待: {EXPECTED_TASKS}\n実際: {tasks}"
    )
