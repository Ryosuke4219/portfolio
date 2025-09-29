#!/usr/bin/env python3
"""Generate helper snippets for docs gallery pages."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
WEEKLY_PATH = DOCS_DIR / "weekly-summary.md"
INCLUDE_DIR = DOCS_DIR / "_includes"
INCLUDE_PATH = INCLUDE_DIR / "weekly-summary-card.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--weekly",
        type=Path,
        default=WEEKLY_PATH,
        help="Path to weekly summary markdown",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=INCLUDE_PATH,
        help="Output path for generated include",
    )
    return parser.parse_args()


def extract_overview(lines: Iterable[str]) -> tuple[str, list[str]]:
    date_label = ""
    overview: list[str] = []
    capture = False
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("# Weekly QA Summary"):
            parts = line.split("—", maxsplit=1)
            if len(parts) == 2:
                date_label = parts[1].strip()
            else:
                date_label = line.lstrip("# ").strip()
        elif line.startswith("## ") and "Overview" in line:
            capture = True
        elif line.startswith("## ") and capture:
            break
        elif capture and line.startswith("- "):
            overview.append(line[2:].strip())
        elif capture and line.strip() == "":
            if overview:
                break
    return date_label, overview


def build_card(date_label: str, overview: list[str]) -> str:
    if not date_label:
        date_label = dt.date.today().isoformat()
    if not overview:
        overview = [
            "TotalTests: 0",
            "PassRate: N/A",
            "NewDefects: 0",
            "TopFailureKinds: -",
        ]
    header = f"### Weekly QA Snapshot — {date_label}"
    bullets = "\n".join(f"- {item}" for item in overview)
    link = "[週次サマリを詳しく読む →]({{ '/weekly-summary.html' | relative_url }})"
    return "\n".join([header, "", bullets, "", link, ""])


def main() -> None:
    args = parse_args()
    weekly_path: Path = args.weekly
    out_path: Path = args.out

    if weekly_path.exists():
        lines = weekly_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    date_label, overview = extract_overview(lines)
    content = build_card(date_label, overview)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
