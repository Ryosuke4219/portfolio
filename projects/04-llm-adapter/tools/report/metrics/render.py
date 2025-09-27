"""HTML and Markdown rendering helpers for metrics reports."""

from __future__ import annotations

import html
import json
from string import Template
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .data import load_baseline_expectations
from .utils import coerce_optional_float, latest_metrics_by_key


def _format_rate(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}"


def _extract_diff_rate(metric: Mapping[str, object]) -> Optional[float]:
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
    metrics: Sequence[Mapping[str, object]], golden_dir: Optional[Path]
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
    rows: List[Dict[str, object]] = []
    seen_keys: set[Tuple[str, str, str]] = set()
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
    table_rows: List[str] = []
    for row in rows:
        notes_parts = [row["notes"], row["detail"]]
        notes_cell = "<br />".join(
            html.escape(part) for part in notes_parts if part
        ) or "-"
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(row['provider'])}</td>"
            f"<td>{html.escape(row['model'])}</td>"
            f"<td>{html.escape(row['prompt_id'])}</td>"
            f"<td>{_format_rate(row['threshold'])}</td>"
            f"<td>{_format_rate(row['baseline_diff'])}</td>"
            f"<td>{_format_rate(row['latest_diff'])}</td>"
            f"<td>{html.escape(str(row['latest_status']))}</td>"
            f"<td>{html.escape(str(row['result']))}</td>"
            f"<td>{notes_cell}</td>"
            "</tr>"
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


def render_html(
    overview: Mapping[str, object],
    comparison_table: Sequence[Mapping[str, object]],
    hist_data: Mapping[str, Sequence[float]],
    scatter_data: Mapping[str, Sequence[Mapping[str, object]]],
    regression_html: str,
    failure_total: int,
    failure_summary: Sequence[Mapping[str, object]],
    determinism_alerts: Sequence[Mapping[str, object]],
) -> str:
    rows_html: List[str] = []
    for row in comparison_table:
        diff_value = row.get("avg_diff_rate")
        diff_text = diff_value if diff_value is not None else "-"
        rows_html.append(
            "<tr>"
            f"<td>{row['provider']}</td>"
            f"<td>{row['model']}</td>"
            f"<td>{row['prompt_id']}</td>"
            f"<td>{row['attempts']}</td>"
            f"<td>{row['ok_rate']}%</td>"
            f"<td>{row['avg_latency']} ms</td>"
            f"<td>${row['avg_cost']}</td>"
            f"<td>{diff_text}</td>"
            "</tr>"
        )
    comparison_rows = "".join(rows_html)
    overview_html = f"""
    <ul>
      <li>総試行数: {overview['total']}</li>
      <li>成功率: {overview['success_rate']}%</li>
      <li>平均レイテンシ: {overview['avg_latency']} ms</li>
      <li>中央値レイテンシ: {overview['median_latency']} ms</li>
      <li>総コスト: ${overview['total_cost']}</li>
      <li>平均コスト: ${overview['avg_cost']}</li>
    </ul>
    """
    if failure_summary:
        failure_rows = "".join(
            f"<tr><td>{idx}</td><td>{row['failure_kind']}</td><td>{row['count']}</td></tr>"
            for idx, row in enumerate(failure_summary, start=1)
        )
        failure_html = f"""
        <p>記録された失敗件数: {failure_total}</p>
        <table>
          <thead>
            <tr><th>Rank</th><th>Failure Kind</th><th>Count</th></tr>
          </thead>
          <tbody>
            {failure_rows}
          </tbody>
        </table>
        """
    else:
        failure_html = "<p>失敗は記録されていません。</p>"
    if determinism_alerts:
        determinism_items = "".join(
            "<li>{provider} / {model} / {prompt} (件数: {count})</li>".format(
                provider=alert.get("provider", "?"),
                model=alert.get("model", "?"),
                prompt=alert.get("prompt_id", "?"),
                count=alert.get("count", 0),
            )
            for alert in determinism_alerts
        )
        determinism_html = f"<ul>{determinism_items}</ul>"
    else:
        determinism_html = "<p>決定性アラートはありません。</p>"
    hist_json = json.dumps(hist_data)
    scatter_json = json.dumps(scatter_data)
    template = Template(
        """<!DOCTYPE html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <title>LLM Adapter レポート</title>
  <script src=\"https://cdn.jsdelivr.net/npm/plotly.js-dist-min\"></script>
  <style>
    body {{ font-family: sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
    th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; }}
    th {{ background-color: #f5f5f5; }}
    section {{ margin-bottom: 2rem; }}
  </style>
</head>
<body>
  <h1>LLM Adapter メトリクスレポート</h1>
  <section>
    <h2>Overview</h2>
    ${overview_html}
  </section>
  <section>
    <h2>比較テーブル</h2>
    <table>
      <thead>
        <tr>
          <th>Provider</th>
          <th>Model</th>
          <th>Prompt</th>
          <th>Attempts</th>
          <th>OK%</th>
          <th>Avg Latency</th>
          <th>Avg Cost</th>
          <th>Avg Diff Rate</th>
        </tr>
      </thead>
      <tbody>
        ${comparison_rows}
      </tbody>
    </table>
  </section>
  <section>
    <h2>Latency Histogram</h2>
    <div id=\"latency_hist\" style=\"width:100%;height:400px;\"></div>
  </section>
  <section>
    <h2>Cost vs Latency</h2>
    <div id=\"cost_latency_scatter\" style=\"width:100%;height:400px;\"></div>
  </section>
  <section>
    <h2>Failure Summary</h2>
    ${failure_html}
  </section>
  <section>
    <h2>Determinism Alerts</h2>
    ${determinism_html}
  </section>
  <section>
    <h2>Baseline Regression</h2>
    ${regression_html}
  </section>
  <script>
    const histData = ${hist_json};
    const histTraces = Object.keys(histData).map(provider => ({
      type: 'histogram',
      name: provider,
      x: histData[provider],
      opacity: 0.6,
    }));
    Plotly.newPlot('latency_hist', histTraces, {barmode: 'overlay', title: 'Latency Histogram'});

    const scatterRaw = ${scatter_json};
    const scatterTraces = Object.keys(scatterRaw).map(provider => ({
      x: scatterRaw[provider].map(p => p.latency),
      y: scatterRaw[provider].map(p => p.cost),
      mode: 'markers',
      type: 'scatter',
      name: provider,
      text: scatterRaw[provider].map(p => p.prompt_id),
    }));
    Plotly.newPlot('cost_latency_scatter', scatterTraces, {
      title: 'Cost vs Latency',
      xaxis: {title: 'Latency (ms)'},
      yaxis: {title: 'Cost (USD)'},
    });
  </script>
</body>
</html>
"""
    )
    return template.substitute(
        overview_html=overview_html,
        comparison_rows=comparison_rows,
        regression_html=regression_html,
        hist_json=hist_json,
        scatter_json=scatter_json,
        failure_html=failure_html,
        determinism_html=determinism_html,
    )


def update_weekly_summary(
    weekly_path: Path,
    failure_total: int,
    failure_summary: Sequence[Mapping[str, object]],
) -> None:
    weekly_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: List[str] = [f"## {today} 時点の失敗サマリ", ""]
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
    existing_entries: List[str] = []
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


__all__ = [
    "build_regression_summary",
    "render_html",
    "update_weekly_summary",
]
