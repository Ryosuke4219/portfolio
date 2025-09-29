"""Regression summary HTML generation for metrics reports."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from pathlib import Path

from .data import load_baseline_expectations
from .utils import coerce_optional_float, latest_metrics_by_key


def _format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}"


def _extract_diff_rate(metric: Mapping[str, object]) -> float | None:
    eval_payload = metric.get("eval")
    if isinstance(eval_payload, Mapping):
        diff = eval_payload.get("diff_rate")
        try:
            if diff is None:
                return None
            return float(diff)
        except (TypeError, ValueError):
            return None
    return None


def build_regression_summary(
    metrics: Sequence[Mapping[str, object]], golden_dir: Path | None
) -> str:
    if not golden_dir:
        return "<p>baseline データが指定されていません。</p>"
    baseline_dir = golden_dir / "baseline"
    if not baseline_dir.exists():
        return "<p>baseline ディレクトリが見つかりません。</p>"
    expectations = load_baseline_expectations(baseline_dir)
    if not expectations:
        return "<p>baseline 出力がまだ登録されていません。</p>"
    latest_map = latest_metrics_by_key(metrics)
    rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for expectation in expectations:
        provider = str(expectation.get("provider", "")).strip()
        model = str(expectation.get("model", "")).strip()
        prompt_id = str(expectation.get("prompt_id", "")).strip()
        if not provider or not model or not prompt_id:
            continue
        key = (provider, model, prompt_id)
        seen_keys.add(key)
        threshold = coerce_optional_float(expectation.get("max_diff_rate"))
        baseline_diff = coerce_optional_float(expectation.get("baseline_diff_rate"))
        notes = str(expectation.get("notes", "") or "")
        latest = latest_map.get(key)
        latest_status = "-"
        latest_diff = None
        result = "MISSING"
        detail = "最新結果がありません。"
        if latest is not None:
            latest_status = str(latest.get("status", "-"))
            latest_diff = _extract_diff_rate(latest)
            if latest_status != "ok":
                result = "FAIL"
                detail = f"最新ステータス: {latest_status}"
            elif latest_diff is None:
                result = "UNKNOWN"
                detail = "diff_rate が計測されていません。"
            else:
                if threshold is not None:
                    if latest_diff <= threshold:
                        result = "PASS"
                        detail = ""
                    else:
                        result = "FAIL"
                        detail = (
                            f"diff_rate {latest_diff:.3f} > 閾値 {threshold:.3f}"
                        )
                elif baseline_diff is not None:
                    if latest_diff <= baseline_diff:
                        result = "PASS"
                        detail = ""
                    else:
                        result = "FAIL"
                        detail = (
                            f"diff_rate {latest_diff:.3f} > baseline {baseline_diff:.3f}"
                        )
                else:
                    result = "PASS"
                    detail = "基準 diff_rate が未設定のため PASS とみなします。"
        rows.append(
            {
                "provider": provider,
                "model": model,
                "prompt_id": prompt_id,
                "threshold": threshold,
                "baseline_diff": baseline_diff,
                "latest_diff": latest_diff,
                "latest_status": latest_status,
                "result": result,
                "notes": notes,
                "detail": detail,
            }
        )
    for key, latest in sorted(latest_map.items()):
        if key in seen_keys:
            continue
        provider, model, prompt_id = key
        rows.append(
            {
                "provider": provider,
                "model": model,
                "prompt_id": prompt_id,
                "threshold": None,
                "baseline_diff": None,
                "latest_diff": _extract_diff_rate(latest),
                "latest_status": str(latest.get("status", "-")),
                "result": "NEW",
                "notes": "",
                "detail": "baseline 未登録。",
            }
        )
    if not rows:
        return "<p>比較対象が存在しません。</p>"
    rows.sort(key=lambda r: (r["provider"], r["model"], r["prompt_id"]))
    pass_count = sum(1 for row in rows if row["result"] == "PASS")
    fail_count = sum(1 for row in rows if row["result"] == "FAIL")
    other_count = len(rows) - pass_count - fail_count
    summary_html = (
        f"<p>PASS: {pass_count} / FAIL: {fail_count} / OTHER: {other_count}</p>"
    )
    table_rows: list[str] = []
    for row in rows:
        notes_parts = [row["notes"], row["detail"]]
        notes_cell = "<br />".join(
            html.escape(part) for part in notes_parts if part
        ) or "-"
        table_rows.append(
            "".join(
                (
                    "<tr>",
                    f"<td>{html.escape(row['provider'])}</td>",
                    f"<td>{html.escape(row['model'])}</td>",
                    f"<td>{html.escape(row['prompt_id'])}</td>",
                    f"<td>{_format_rate(row['threshold'])}</td>",
                    f"<td>{_format_rate(row['baseline_diff'])}</td>",
                    f"<td>{_format_rate(row['latest_diff'])}</td>",
                    f"<td>{html.escape(str(row['latest_status']))}</td>",
                    f"<td>{html.escape(str(row['result']))}</td>",
                    f"<td>{notes_cell}</td>",
                    "</tr>",
                )
            )
        )
    table_html = """
    <table>
      <thead>
        <tr>
          <th>Provider</th>
          <th>Model</th>
          <th>Prompt</th>
          <th>Threshold</th>
          <th>Baseline Diff</th>
          <th>Latest Diff</th>
          <th>Latest Status</th>
          <th>Result</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    """
    return summary_html + table_html.format(rows_html="\n".join(table_rows))


__all__ = ["build_regression_summary"]
