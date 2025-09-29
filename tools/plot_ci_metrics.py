#!/usr/bin/env python3
"""Generate CI pass rate and flaky trend chart (SVG)."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from ci_metrics import load_run_history

WIDTH = 960
HEIGHT = 540
MARGIN_LEFT = 90
MARGIN_RIGHT = 70
MARGIN_TOP = 60
MARGIN_BOTTOM = 110

PASS_COLOR = "#2563eb"
FLAKY_COLOR = "#f97316"
BG_COLOR = "#ffffff"
GRID_COLOR = "#94a3b8"
TEXT_COLOR = "#0f172a"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot CI metrics trend (SVG)")
    parser.add_argument("--runs", type=Path, required=True, help="Path to runs.jsonl")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output SVG path",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=5,
        help="Sliding window size used for flaky detection",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum number of recent runs to plot",
    )
    return parser.parse_args()


def scale_positions(count: int) -> list[float]:
    if count <= 1:
        return [MARGIN_LEFT]
    available = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    step = available / (count - 1)
    return [MARGIN_LEFT + step * idx for idx in range(count)]


def build_polyline(points: Iterable[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def build_svg(entries: list[dict]) -> str:
    chart_height = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    positions = scale_positions(len(entries))
    pass_points = []
    flaky_points = []

    max_flaky = max((entry.get("flaky_count") or 0 for entry in entries), default=0)
    max_flaky = max(max_flaky, 1)

    axis_bottom = HEIGHT - MARGIN_BOTTOM
    axis_top = MARGIN_TOP
    axis_left = MARGIN_LEFT
    axis_right = WIDTH - MARGIN_RIGHT

    circles_pass: list[str] = []
    circles_flaky: list[str] = []
    x_labels: list[str] = []

    for idx, entry in enumerate(entries):
        x = positions[idx]
        ts = entry.get("ts") or ""
        run_id = entry.get("run_id") or "-"
        pass_rate = entry.get("pass_rate")
        if pass_rate is not None:
            y = axis_top + chart_height * (1 - float(pass_rate))
            pass_points.append((x, y))
            circles_pass.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" '
                f'r="5" fill="{PASS_COLOR}" '
                f'stroke="{BG_COLOR}" stroke-width="1" />'
            )
        flaky_count = entry.get("flaky_count") or 0
        flaky_ratio = flaky_count / max_flaky if max_flaky else 0.0
        y_flaky = axis_top + chart_height * (1 - flaky_ratio)
        flaky_points.append((x, y_flaky))
        circles_flaky.append(
            f'<circle cx="{x:.2f}" cy="{y_flaky:.2f}" '
            f'r="4" fill="{BG_COLOR}" '
            f'stroke="{FLAKY_COLOR}" stroke-width="2" />'
        )
        labels = [(axis_bottom + 25, "12", run_id)]
        if ts:
            labels.append((axis_bottom + 42, "11", ts[:10]))
        for y_value, font_size, text in labels:
            x_labels.append(
                f'<text x="{x:.2f}" y="{y_value:.2f}" '
                f'fill="{TEXT_COLOR}" font-size="{font_size}" '
                f'text-anchor="middle">{text}</text>'
            )

    grid_lines: list[str] = []
    grid_steps = [0.0, 0.25, 0.5, 0.75, 1.0]
    for step in grid_steps:
        y = axis_top + chart_height * (1 - step)
        label = int(step * 100)
        grid_lines.append(
            f'<line x1="{axis_left}" y1="{y:.2f}" '
            f'x2="{axis_right}" y2="{y:.2f}" '
            f'stroke="{GRID_COLOR}" stroke-width="0.5" '
            'stroke-dasharray="4 4" />'
        )
        grid_lines.append(
            f'<text x="{axis_left - 12}" y="{y + 4:.2f}" '
            f'fill="{TEXT_COLOR}" font-size="12" '
            f'text-anchor="end">{label}%</text>'
        )

    flaky_ticks = max(1, min(max_flaky, 6))
    flaky_step = max_flaky / flaky_ticks
    for idx in range(flaky_ticks + 1):
        value = flaky_step * idx
        y = axis_top + chart_height * (1 - (value / max_flaky if max_flaky else 0.0))
        grid_lines.append(
            f'<text x="{axis_right + 12}" y="{y + 4:.2f}" '
            f'fill="{TEXT_COLOR}" font-size="12" '
            f'text-anchor="start">{value:.0f}</text>'
        )

    pass_polyline = build_polyline(pass_points)
    flaky_polyline = build_polyline(flaky_points)

    legend = (
        f'<rect x="{axis_left}" y="{MARGIN_TOP - 40}" '
        'width="260" height="28" rx="6" ry="6" fill="#f1f5f9" />'
        f'<line x1="{axis_left + 12}" y1="{MARGIN_TOP - 26}" '
        f'x2="{axis_left + 52}" y2="{MARGIN_TOP - 26}" '
        f'stroke="{PASS_COLOR}" stroke-width="2" />'
        f'<text x="{axis_left + 60}" y="{MARGIN_TOP - 22}" '
        f'fill="{TEXT_COLOR}" font-size="13">Pass Rate (%)</text>'
        f'<line x1="{axis_left + 150}" y1="{MARGIN_TOP - 26}" '
        f'x2="{axis_left + 190}" y2="{MARGIN_TOP - 26}" '
        f'stroke="{FLAKY_COLOR}" stroke-width="2" />'
        f'<text x="{axis_left + 198}" y="{MARGIN_TOP - 22}" '
        f'fill="{TEXT_COLOR}" font-size="13">Flaky Count</text>'
    )

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="100%" height="100%" fill="{BG_COLOR}" />',
        f'<text x="{WIDTH / 2:.2f}" y="{MARGIN_TOP - 20:.2f}" '
        'text-anchor="middle" font-size="20" '
        f'fill="{TEXT_COLOR}">CI Pass Rate & Flaky Trend</text>',
        *grid_lines,
        f'<line x1="{axis_left}" y1="{axis_bottom}" '
        f'x2="{axis_right}" y2="{axis_bottom}" '
        f'stroke="{TEXT_COLOR}" stroke-width="1" />',
        f'<line x1="{axis_left}" y1="{axis_top}" '
        f'x2="{axis_left}" y2="{axis_bottom}" '
        f'stroke="{TEXT_COLOR}" stroke-width="1" />',
        f'<line x1="{axis_right}" y1="{axis_top}" '
        f'x2="{axis_right}" y2="{axis_bottom}" '
        f'stroke="{TEXT_COLOR}" stroke-width="1" />',
    ]

    if pass_polyline:
        svg.append(
            f'<polyline points="{pass_polyline}" fill="none" '
            f'stroke="{PASS_COLOR}" stroke-width="3" '
            'stroke-linejoin="round" stroke-linecap="round" />'
        )
    svg.extend(circles_pass)

    if flaky_polyline:
        svg.append(
            f'<polyline points="{flaky_polyline}" fill="none" '
            f'stroke="{FLAKY_COLOR}" stroke-width="2" '
            'stroke-dasharray="6 4" stroke-linejoin="round" '
            'stroke-linecap="round" />'
        )
    svg.extend(circles_flaky)

    svg.extend(x_labels)
    svg.append(
        f'<text x="{axis_left - 50}" '
        f'y="{(axis_top + axis_bottom) / 2:.2f}" '
        f'transform="rotate(-90 {axis_left - 50},{(axis_top + axis_bottom) / 2:.2f})" '
        f'fill="{TEXT_COLOR}" font-size="14" '
        'text-anchor="middle">Pass Rate (%)</text>'
    )
    svg.append(
        f'<text x="{axis_right + 50}" '
        f'y="{(axis_top + axis_bottom) / 2:.2f}" '
        f'transform="rotate(90 {axis_right + 50},{(axis_top + axis_bottom) / 2:.2f})" '
        f'fill="{TEXT_COLOR}" font-size="14" '
        'text-anchor="middle">Flaky Count</text>'
    )
    svg.append(legend)
    svg.append('</svg>')
    return "".join(svg)


def main() -> None:
    args = parse_args()
    if args.output.suffix.lower() != ".svg":
        raise SystemExit("Only SVG output is supported (use --output path/to/file.svg)")

    history = load_run_history(args.runs, window_size=args.window_size)
    if not history:
        raise SystemExit("No run history available")

    entries = [
        {
            "run_id": item.run_id,
            "ts": item.timestamp.isoformat().replace("+00:00", "Z") if item.timestamp else None,
            "pass_rate": item.pass_rate,
            "flaky_count": item.flaky_count,
        }
        for item in history
    ]
    if args.limit > 0:
        entries = entries[-args.limit :]

    svg_content = build_svg(entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg_content, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
