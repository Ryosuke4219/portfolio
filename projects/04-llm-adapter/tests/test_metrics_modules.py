from __future__ import annotations

# ruff: noqa: I001

import sys
import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

metrics_mod = importlib.import_module("adapter.core.metrics")
metrics_models_mod = importlib.import_module("adapter.core.metrics.models")
metrics_update_mod = importlib.import_module("adapter.core.metrics.update")
metrics_costs_mod = importlib.import_module("adapter.core.metrics.costs")
metrics_diff_mod = importlib.import_module("adapter.core.metrics.diff")
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
            "cost_estimate": 0.2,
            "status": "ok",
            "eval": {"diff_rate": 0.1},
        },
        {
            "provider": "openai",
            "model": "gpt",
            "prompt_id": "p1",
            "latency_ms": 300,
            "cost_usd": 0.4,
            "cost_estimate": 0.4,
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


def test_compute_overview_handles_success_status() -> None:
    metrics = [
        {
            "provider": "openai",
            "model": "gpt",
            "prompt_id": "p2",
            "latency_ms": 150,
            "cost_usd": 0.1,
            "status": "success",
        }
    ]

    overview = data_mod.compute_overview(metrics)
    assert overview["success_rate"] == 100.0

    table = data_mod.build_comparison_table(metrics)
    assert table == [
        {
            "provider": "openai",
            "model": "gpt",
            "prompt_id": "p2",
            "attempts": 1,
            "ok_rate": 100.0,
            "avg_latency": 150.0,
            "avg_cost": 0.1,
            "avg_diff_rate": None,
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


def test_run_metrics_to_json_dict_includes_cost_estimate() -> None:
    run = metrics_mod.RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id="run-1",
        provider="openai",
        model="gpt-4",
        mode="chat",
        prompt_id="prompt-1",
        prompt_name="Sample",
        seed=42,
        temperature=0.1,
        top_p=1.0,
        max_tokens=256,
        input_tokens=128,
        output_tokens=64,
        latency_ms=1234,
        cost_usd=0.5,
        status="ok",
        failure_kind=None,
        error_message=None,
        output_text="Hello",
        output_hash="deadbeef",
    )
    payload = run.to_json_dict()
    assert payload["cost_usd"] == pytest.approx(0.5)
    assert payload["cost_estimate"] == pytest.approx(0.5)

    run_with_estimate = metrics_mod.RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id="run-2",
        provider="openai",
        model="gpt-4",
        mode="chat",
        prompt_id="prompt-1",
        prompt_name="Sample",
        seed=42,
        temperature=0.1,
        top_p=1.0,
        max_tokens=256,
        input_tokens=128,
        output_tokens=64,
        latency_ms=1234,
        cost_usd=0.5,
        cost_estimate=0.75,
        status="ok",
        failure_kind=None,
        error_message=None,
        output_text="Hello",
        output_hash="deadbeef",
    )
    payload_with_estimate = run_with_estimate.to_json_dict()
    assert payload_with_estimate["cost_usd"] == pytest.approx(0.5)
    assert payload_with_estimate["cost_estimate"] == pytest.approx(0.75)


def test_metrics_module_reexports_public_api() -> None:
    assert metrics_mod.RunMetric is metrics_models_mod.RunMetric
    assert metrics_mod.RunMetrics is metrics_models_mod.RunMetrics
    assert metrics_mod.EvalMetrics is metrics_models_mod.EvalMetrics
    assert metrics_mod.finalize_run_metrics is metrics_update_mod.finalize_run_metrics
    assert metrics_mod.apply_shadow_metrics is metrics_update_mod.apply_shadow_metrics
    assert metrics_mod.compute_cost_usd is metrics_costs_mod.compute_cost_usd
    assert metrics_mod.estimate_cost is metrics_costs_mod.estimate_cost
    assert metrics_mod.tokenize is metrics_diff_mod.tokenize
    assert metrics_mod.compute_diff_rate is metrics_diff_mod.compute_diff_rate
