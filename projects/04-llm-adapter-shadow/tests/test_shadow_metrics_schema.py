from __future__ import annotations

import json
from pathlib import Path

from llm_adapter.provider_spi import ProviderRequest
from llm_adapter.providers.mock import MockProvider
from llm_adapter.runner import Runner


def _load_shadow_diff(metrics_path: Path) -> dict[str, object]:
    payloads = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]
    return next(item for item in payloads if item["event"] == "shadow_diff")


def test_shadow_metrics_include_provider_id_and_outcome_success(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    request = ProviderRequest(prompt="hello", model="primary-model")
    runner.run(request, shadow=shadow, shadow_metrics_path=metrics_path)

    event = _load_shadow_diff(metrics_path)
    assert event["shadow_provider"] == "shadow"
    assert event["shadow_provider_id"] == "shadow"
    assert event["shadow_outcome"] == "success"


def test_shadow_metrics_include_provider_id_and_outcome_error(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    request = ProviderRequest(prompt="[TIMEOUT] boom", model="primary-model")
    runner.run(request, shadow=shadow, shadow_metrics_path=metrics_path)

    event = _load_shadow_diff(metrics_path)
    assert event["shadow_provider"] == "shadow"
    assert event["shadow_provider_id"] == "shadow"
    assert event["shadow_outcome"] == "error"


def test_shadow_metrics_diff_kind_match(tmp_path: Path) -> None:
    primary = MockProvider("mirror", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("mirror", base_latency_ms=5, error_markers=set())
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    request = ProviderRequest(prompt="hello", model="primary-model")
    runner.run(request, shadow=shadow, shadow_metrics_path=metrics_path)

    event = _load_shadow_diff(metrics_path)
    assert event["shadow_outcome"] == "success"
    assert event["diff_kind"] == "match"


def test_shadow_metrics_diff_kind_mismatch(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers=set())
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    request = ProviderRequest(prompt="hello", model="primary-model")
    runner.run(request, shadow=shadow, shadow_metrics_path=metrics_path)

    event = _load_shadow_diff(metrics_path)
    assert event["shadow_outcome"] == "success"
    assert event["diff_kind"] == "mismatch"


def test_shadow_metrics_diff_kind_shadow_error(tmp_path: Path) -> None:
    primary = MockProvider("primary", base_latency_ms=5, error_markers=set())
    shadow = MockProvider("shadow", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = Runner([primary])

    metrics_path = tmp_path / "metrics.jsonl"
    request = ProviderRequest(prompt="[TIMEOUT] boom", model="primary-model")
    runner.run(request, shadow=shadow, shadow_metrics_path=metrics_path)

    event = _load_shadow_diff(metrics_path)
    assert event["shadow_outcome"] == "error"
    assert event["diff_kind"] == "shadow_error"
