from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

data_mod = importlib.import_module("tools.report.metrics.data")
regression_mod = importlib.import_module("tools.report.metrics.regression_summary")
weekly_mod = importlib.import_module("tools.report.metrics.weekly_summary")


def test_load_metrics_handles_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    assert data_mod.load_metrics(path) == []


def test_compute_overview_and_comparison_table() -> None:
    metrics = [
        {
            "provider": "openai",
            "model": "gpt",
            "prompt_id": "p1",
            "latency_ms": 100,
            "cost_usd": 0.2,
            "status": "ok",
            "eval": {"diff_rate": 0.1},
        },
        {
            "provider": "openai",
            "model": "gpt",
            "prompt_id": "p1",
            "latency_ms": 300,
            "cost_usd": 0.4,
            "status": "error",
            "eval": {"diff_rate": 0.3},
        },
    ]
    overview = data_mod.compute_overview(metrics)
    assert overview == {
        "total": 2,
        "success_rate": 50.0,
        "avg_latency": 200.0,
        "median_latency": 200.0,
        "total_cost": 0.6,
        "avg_cost": 0.3,
    }
    table = data_mod.build_comparison_table(metrics)
    assert table == [
        {
            "provider": "openai",
            "model": "gpt",
            "prompt_id": "p1",
            "attempts": 2,
            "ok_rate": 50.0,
            "avg_latency": 200.0,
            "avg_cost": 0.3,
            "avg_diff_rate": 0.2,
        }
    ]


def test_failure_summary_and_alerts() -> None:
    metrics = [
        {"failure_kind": "timeout"},
        {"failure_kind": "timeout"},
        {"failure_kind": "non_deterministic", "provider": "a", "model": "b", "prompt_id": "c"},
        {"failure_kind": "non_deterministic", "provider": "a", "model": "b", "prompt_id": "c"},
        {"failure_kind": "non_deterministic", "provider": "a", "model": "b", "prompt_id": "c"},
    ]
    total, summary = data_mod.build_failure_summary(metrics)
    assert total == 5
    assert summary[0] == {"failure_kind": "non_deterministic", "count": 3}
    alerts = data_mod.build_determinism_alerts(metrics)
    assert alerts == [
        {"provider": "a", "model": "b", "prompt_id": "c", "count": 3}
    ]


def test_load_baseline_expectations(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    (baseline_dir / "sample.jsonl").write_text(
        "{\"provider\": \"p\", \"model\": \"m\", \"prompt_id\": \"q\"}\n",
        encoding="utf-8",
    )
    (baseline_dir / "expectations.json").write_text(
        "[{\"provider\": \"p2\", \"model\": \"m2\", \"prompt_id\": \"q2\"}]",
        encoding="utf-8",
    )
    expectations = data_mod.load_baseline_expectations(baseline_dir)
    assert len(expectations) == 2


def test_build_regression_summary_and_weekly_summary(tmp_path: Path) -> None:
    golden_dir = tmp_path / "golden"
    baseline_dir = golden_dir / "baseline"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "expectations.json").write_text(
        "[{\"provider\": \"p\", \"model\": \"m\", \"prompt_id\": \"id\", \"max_diff_rate\": 0.5}]",
        encoding="utf-8",
    )
    metrics = [
        {
            "provider": "p",
            "model": "m",
            "prompt_id": "id",
            "status": "ok",
            "eval": {"diff_rate": 0.3},
            "ts": "2024-01-01T00:00:00Z",
        }
    ]
    regression_html = regression_mod.build_regression_summary(metrics, golden_dir)
    assert "PASS" in regression_html

    weekly_path = tmp_path / "summary.md"
    weekly_mod.update_weekly_summary(
        weekly_path, 1, [{"failure_kind": "timeout", "count": 1}]
    )
    content = weekly_path.read_text(encoding="utf-8")
    assert "週次サマリ" in content
    # Ensure the Markdown table header is present when failures exist.
    assert "| Rank | Failure Kind | Count |" in content


@pytest.mark.parametrize(
    "golden_dir, expected",
    [
        (None, "baseline データが指定されていません"),
        (Path("nonexistent"), "baseline ディレクトリが見つかりません"),
    ],
)
def test_build_regression_summary_handles_missing_baseline(
    tmp_path: Path, golden_dir: Path | None, expected: str
) -> None:
    metrics: list[dict[str, object]] = []
    actual = regression_mod.build_regression_summary(metrics, golden_dir)
    assert expected in actual
