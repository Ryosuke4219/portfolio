from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

import datetime as dt

from .report import build_front_matter, ensure_front_matter


def fallback_write(out_path: Path, today: dt.date, days: int) -> None:
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8").splitlines()
    else:
        existing = []

    if not existing:
        placeholder = [
            f"# Weekly QA Summary — {today.isoformat()}",
            "",
            f"## Overview (last {days} days)",
            "- TotalTests: 0",
            "- PassRate: N/A",
            "- NewDefects: 0",
            "- TopFailureKinds: -",
            "",
            "## Top Flaky (score)",
            "| Rank | Canonical ID | Attempts | p_fail | Score |",
            "|-----:|--------------|---------:|------:|------:|",
            "| - | データなし | 0 | 0.00 | 0.00 |",
            "",
            "## Notes",
            "- データソースが見つからなかったため前回出力を保持しました。",
            "",
            "<details><summary>Method</summary>",
            "データソース: runs.jsonl, flaky_rank.csv / 期間: 直近7日 / 再計算: 毎週月曜 09:00 JST",
            "</details>",
            "",
        ]
        out_path.write_text(
            "\n".join(build_front_matter(today, days) + placeholder) + "\n",
            encoding="utf-8",
        )
        return

    updated = ensure_front_matter(existing, today, days)
    title_line = f"# Weekly QA Summary — {today.isoformat()}"
    for idx, line in enumerate(updated):
        if line.startswith("# Weekly QA Summary"):
            updated[idx] = title_line
            break
    else:
        updated.append(title_line)
        updated.append("")

    out_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def write_summary(
    out_path: Path,
    today: dt.date,
    days: int,
    markdown_lines: Iterable[str],
    *,
    method_lines: Iterable[str],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content: List[str] = [*build_front_matter(today, days), *markdown_lines, "", *method_lines, ""]
    out_path.write_text("\n".join(content) + "\n", encoding="utf-8")
