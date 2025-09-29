"""HTML report templating utilities for metrics outputs."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from string import Template


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
    rows_html: list[str] = []
    for row in comparison_table:
        diff_value = row.get("avg_diff_rate")
        diff_text = diff_value if diff_value is not None else "-"
        rows_html.append(
            "".join(
                (
                    "<tr>",
                    f"<td>{row['provider']}</td>",
                    f"<td>{row['model']}</td>",
                    f"<td>{row['prompt_id']}</td>",
                    f"<td>{row['attempts']}</td>",
                    f"<td>{row['ok_rate']}%</td>",
                    f"<td>{row['avg_latency']} ms</td>",
                    f"<td>${row['avg_cost']}</td>",
                    f"<td>{diff_text}</td>",
                    "</tr>",
                )
            )
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


__all__ = ["render_html"]
