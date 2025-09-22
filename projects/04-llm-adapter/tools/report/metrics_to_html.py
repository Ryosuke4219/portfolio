"""runs-metrics.jsonl から HTML レポートを生成する。"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple


def load_metrics(path: Path) -> List[Mapping[str, object]]:
    if not path.exists():
        return []
    metrics: List[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            metrics.append(json.loads(line))
    return metrics


def compute_overview(metrics: List[Mapping[str, object]]) -> Dict[str, object]:
    total = len(metrics)
    if total == 0:
        return {"total": 0, "success_rate": 0.0, "avg_latency": 0.0, "median_latency": 0.0, "total_cost": 0.0, "avg_cost": 0.0}
    latencies = [m.get("latency_ms", 0) for m in metrics]
    costs = [m.get("cost_usd", 0.0) for m in metrics]
    successes = sum(1 for m in metrics if m.get("status") == "ok")
    return {
        "total": total,
        "success_rate": round(successes / total * 100, 2),
        "avg_latency": round(mean(latencies), 2),
        "median_latency": round(median(latencies), 2),
        "total_cost": round(sum(costs), 4),
        "avg_cost": round(mean(costs), 4),
    }


def build_comparison_table(metrics: List[Mapping[str, object]]) -> List[Dict[str, object]]:
    groups: Dict[tuple, List[Mapping[str, object]]] = {}
    for metric in metrics:
        key = (metric.get("provider"), metric.get("model"), metric.get("prompt_id"))
        groups.setdefault(key, []).append(metric)
    table: List[Dict[str, object]] = []
    for (provider, model, prompt_id), rows in sorted(groups.items()):
        attempts = len(rows)
        ok_count = sum(1 for row in rows if row.get("status") == "ok")
        avg_latency = mean(row.get("latency_ms", 0) for row in rows)
        avg_cost = mean(row.get("cost_usd", 0.0) for row in rows)
        diff_rates = [row.get("eval", {}).get("diff_rate") for row in rows if row.get("eval", {}).get("diff_rate") is not None]
        avg_diff = mean(diff_rates) if diff_rates else None
        table.append(
            {
                "provider": provider,
                "model": model,
                "prompt_id": prompt_id,
                "attempts": attempts,
                "ok_rate": round(ok_count / attempts * 100, 2) if attempts else 0.0,
                "avg_latency": round(avg_latency, 2) if attempts else 0.0,
                "avg_cost": round(avg_cost, 4) if attempts else 0.0,
                "avg_diff_rate": round(avg_diff, 4) if avg_diff is not None else None,
            }
        )
    return table


def build_latency_histogram_data(metrics: List[Mapping[str, object]]) -> Dict[str, List[float]]:
    hist: Dict[str, List[float]] = {}
    for metric in metrics:
        provider = str(metric.get("provider"))
        hist.setdefault(provider, []).append(float(metric.get("latency_ms", 0)))
    return hist


def build_scatter_data(metrics: List[Mapping[str, object]]) -> Dict[str, List[Dict[str, object]]]:
    scatter: Dict[str, List[Dict[str, object]]] = {}
    for metric in metrics:
        provider = str(metric.get("provider"))
        scatter.setdefault(provider, []).append(
            {
                "latency": float(metric.get("latency_ms", 0)),
                "cost": float(metric.get("cost_usd", 0.0)),
                "prompt_id": metric.get("prompt_id"),
            }
        )
    return scatter


def build_failure_summary(
    metrics: Sequence[Mapping[str, object]]
) -> tuple[int, List[Dict[str, object]]]:
    counter: Counter[str] = Counter()
    for metric in metrics:
        failure = metric.get("failure_kind")
        if failure:
            counter[str(failure)] += 1
    total = sum(counter.values())
    summary = [
        {"failure_kind": name, "count": count}
        for name, count in counter.most_common(3)
    ]
    return total, summary


def build_determinism_alerts(
    metrics: Sequence[Mapping[str, object]]
) -> List[Dict[str, object]]:
    alerts: Dict[tuple, int] = {}
    for metric in metrics:
        if metric.get("failure_kind") != "non_deterministic":
            continue
        key = (
            metric.get("provider"),
            metric.get("model"),
            metric.get("prompt_id"),
        )
        alerts[key] = alerts.get(key, 0) + 1
    rows: List[Dict[str, object]] = []
    for (provider, model, prompt_id), count in sorted(alerts.items()):
        rows.append(
            {
                "provider": provider,
                "model": model,
                "prompt_id": prompt_id,
                "count": count,
            }
        )
    return rows


def load_baseline_expectations(baseline_dir: Path) -> List[Mapping[str, object]]:
    entries: List[Mapping[str, object]] = []
    if not baseline_dir.exists():
        return entries
    for path in sorted(baseline_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if isinstance(data, Mapping):
                    entries.append(data)
    json_path = baseline_dir / "expectations.json"
    if json_path.exists():
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping):
                    entries.append(item)
        elif isinstance(raw, Mapping):
            entries.append(raw)
    return entries


def _parse_iso_ts(value: object) -> datetime:
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _coerce_optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_metrics_by_key(
    metrics: Sequence[Mapping[str, object]]
) -> Dict[Tuple[str, str, str], Mapping[str, object]]:
    latest: Dict[Tuple[str, str, str], Tuple[datetime, Mapping[str, object]]] = {}
    for metric in metrics:
        provider = metric.get("provider")
        model = metric.get("model")
        prompt_id = metric.get("prompt_id")
        if provider is None or model is None or prompt_id is None:
            continue
        key = (str(provider), str(model), str(prompt_id))
        ts = _parse_iso_ts(metric.get("ts"))
        existing = latest.get(key)
        if existing is None or ts >= existing[0]:
            latest[key] = (ts, metric)
    return {key: value for key, (_, value) in latest.items()}


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
    latest_map = _latest_metrics_by_key(metrics)
    rows: List[Dict[str, object]] = []
    seen_keys: Set[Tuple[str, str, str]] = set()
    for expectation in expectations:
        provider = str(expectation.get("provider", "")).strip()
        model = str(expectation.get("model", "")).strip()
        prompt_id = str(expectation.get("prompt_id", "")).strip()
        if not provider or not model or not prompt_id:
            continue
        key = (provider, model, prompt_id)
        seen_keys.add(key)
        threshold = _coerce_optional_float(expectation.get("max_diff_rate"))
        baseline_diff = _coerce_optional_float(expectation.get("baseline_diff_rate"))
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


def _format_rate(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}"


def render_html(
    overview: Mapping[str, object],
    comparison_table: List[Mapping[str, object]],
    hist_data: Mapping[str, List[float]],
    scatter_data: Mapping[str, List[Mapping[str, object]]],
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
    template = """<!DOCTYPE html>
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
    {overview_html}
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
        {comparison_rows}
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
    {failure_html}
  </section>
  <section>
    <h2>Determinism Alerts</h2>
    {determinism_html}
  </section>
  <section>
    <h2>Baseline Regression</h2>
    {regression_html}
  </section>
  <script>
    const histData = {hist_json};
    const histTraces = Object.keys(histData).map(provider => ({{
      type: 'histogram',
      name: provider,
      x: histData[provider],
      opacity: 0.6,
    }}));
    Plotly.newPlot('latency_hist', histTraces, {{barmode: 'overlay', title: 'Latency Histogram'}});

    const scatterRaw = {scatter_json};
    const scatterTraces = Object.keys(scatterRaw).map(provider => ({{
      x: scatterRaw[provider].map(p => p.latency),
      y: scatterRaw[provider].map(p => p.cost),
      mode: 'markers',
      type: 'scatter',
      name: provider,
      text: scatterRaw[provider].map(p => p.prompt_id),
    }}));
    Plotly.newPlot('cost_latency_scatter', scatterTraces, {{
      title: 'Cost vs Latency',
      xaxis: {{title: 'Latency (ms)'}},
      yaxis: {{title: 'Cost (USD)'}},
    }});
  </script>
</body>
</html>
"""
    return template.format(
        overview_html=overview_html,
        comparison_rows=comparison_rows,
        regression_html=regression_html,
        hist_json=hist_json,
        scatter_json=scatter_json,
        failure_html=failure_html,
        determinism_html=determinism_html,
    )


def generate_report(
    metrics_path: Path,
    golden_dir: Optional[Path],
    out_path: Path,
    weekly_summary_path: Optional[Path] = None,
) -> None:
    metrics = load_metrics(metrics_path)
    overview = compute_overview(metrics)
    comparison_table = build_comparison_table(metrics)
    hist_data = build_latency_histogram_data(metrics)
    scatter_data = build_scatter_data(metrics)
    regression_html = build_regression_summary(metrics, golden_dir)
    failure_total, failure_summary = build_failure_summary(metrics)
    determinism_alerts = build_determinism_alerts(metrics)
    html = render_html(
        overview,
        comparison_table,
        hist_data,
        scatter_data,
        regression_html,
        failure_total,
        failure_summary,
        determinism_alerts,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    if weekly_summary_path is not None:
        update_weekly_summary(weekly_summary_path, failure_total, failure_summary)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="JSONL メトリクスから HTML を生成")
    parser.add_argument("--metrics", required=True, help="runs-metrics.jsonl のパス")
    parser.add_argument("--golden", default=None, help="ゴールデンディレクトリ")
    parser.add_argument("--out", required=True, help="出力 HTML パス")
    parser.add_argument("--weekly-summary", default=None, help="週次サマリ Markdown の出力パス")
    args = parser.parse_args()

    metrics_path = Path(args.metrics).expanduser().resolve()
    golden_dir = Path(args.golden).expanduser().resolve() if args.golden else None
    out_path = Path(args.out).expanduser().resolve()
    weekly_summary = Path(args.weekly_summary).expanduser().resolve() if args.weekly_summary else None

    generate_report(metrics_path, golden_dir, out_path, weekly_summary)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
