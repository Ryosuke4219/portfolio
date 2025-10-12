from __future__ import annotations

from tools.report.metrics.data import build_openrouter_http_failures
from tools.report.metrics.weekly_summary import update_weekly_summary


def test_build_openrouter_http_failures_counts_rate() -> None:
    metrics = [
        {"provider": "openrouter", "status": "error", "error_type": "RateLimitError"},
        {"provider": "openrouter", "status": "error", "failure_kind": "rate_limit"},
        {
            "provider": "openrouter",
            "status": "error",
            "error_type": "RateLimitError",
            "failure_kind": "retryable",
        },
        {"provider": "openrouter", "status": "error", "failure_kind": "retryable"},
        {"provider": "openrouter", "status": "ok", "error_type": "RateLimitError"},
        {"provider": "anthropic", "status": "error", "error_type": "RateLimitError"},
    ]

    total, summary = build_openrouter_http_failures(metrics)

    assert total == 4
    assert summary == [
        {
            "category": "RateLimitError",
            "label": "RateLimitError (429)",
            "count": 3,
            "rate": 75.0,
        },
        {
            "category": "RetriableError",
            "label": "RetriableError (5xx)",
            "count": 1,
            "rate": 25.0,
        },
    ]


def test_weekly_summary_includes_openrouter_table(tmp_path) -> None:
    weekly_path = tmp_path / "weekly.md"
    http_summary = [
        {
            "category": "RateLimitError",
            "label": "RateLimitError (429)",
            "count": 3,
            "rate": 60.0,
        },
        {
            "category": "RetriableError",
            "label": "RetriableError (5xx)",
            "count": 2,
            "rate": 40.0,
        },
    ]

    update_weekly_summary(
        weekly_path,
        5,
        [{"failure_kind": "rate_limit", "count": 5}],
        openrouter_http_failures=http_summary,
    )

    text = weekly_path.read_text(encoding="utf-8")
    assert "### OpenRouter HTTP Failures" in text
    assert "| 1 | RateLimitError (429) | 3 | 60.0 |" in text
    assert "| 2 | RetriableError (5xx) | 2 | 40.0 |" in text
