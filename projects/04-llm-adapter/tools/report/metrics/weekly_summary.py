"""Weekly Markdown summary helpers for metrics reports."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, UTC
from pathlib import Path


def update_weekly_summary(
    weekly_path: Path,
    failure_total: int,
    failure_summary: Sequence[Mapping[str, object]],
) -> None:
    weekly_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines: list[str] = [f"## {today} 時点の失敗サマリ", ""]
    if failure_total > 0 and failure_summary:
        lines.append(f"- 失敗総数: {failure_total}")
        lines.append("")
        lines.append("| Rank | Failure Kind | Count |")
        lines.append("| ---: | :----------- | ----: |")
        for idx, row in enumerate(failure_summary, start=1):
            lines.append(f"| {idx} | {row['failure_kind']} | {row['count']} |")
    else:
        lines.append("- 失敗は記録されていません。")
    new_entry = "\n".join(lines).strip()
    header = "# LLM Adapter 週次サマリ"
    if weekly_path.exists():
        existing_text = weekly_path.read_text(encoding="utf-8").strip()
    else:
        existing_text = ""
    existing_entries: list[str] = []
    if existing_text:
        if existing_text.startswith(header):
            body = existing_text[len(header) :].strip()
        else:
            body = existing_text
        if body:
            for chunk in body.split("\n\n"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if not chunk.startswith("## "):
                    continue
                if chunk.startswith(f"## {today}"):
                    continue
                existing_entries.append(chunk)
    existing_entries.append(new_entry)
    content_body = "\n\n".join(existing_entries)
    content = header + "\n\n" + content_body + "\n"
    weekly_path.write_text(content, encoding="utf-8")


__all__ = ["update_weekly_summary"]
