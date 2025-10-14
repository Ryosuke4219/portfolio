import json
from pathlib import Path
from typing import Any

import pytest
from llm_adapter.errors import AllFailedError, TimeoutError
from llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from llm_adapter.providers.mock import MockProvider
from llm_adapter.runner import Runner


def _providers_for(marker: str) -> tuple[MockProvider, MockProvider]:
    failing = MockProvider("p1", base_latency_ms=5, error_markers={marker})
    fallback = MockProvider("p2", base_latency_ms=5, error_markers=set())
    return failing, fallback


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _require_token_usage(response: ProviderResponse) -> TokenUsage:
    assert response.token_usage is not None
    return response.token_usage


def test_timeout_fallback() -> None:
    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    request = ProviderRequest(prompt="[TIMEOUT] hello", model="fallback-model")
    response = runner.run(request)
    assert isinstance(response, ProviderResponse)

    _require_token_usage(response)
    assert response.text.startswith("echo(p2):")
    assert response.model == "fallback-model"


def test_ratelimit_retry_fallback() -> None:
    p1, p2 = _providers_for("[RATELIMIT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[RATELIMIT] test", model="fallback-model"))
    assert isinstance(response, ProviderResponse)
    assert response.text.startswith("echo(p2):")


def test_ratelimit_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    def fake_runner_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("time.sleep", fake_runner_sleep)

    p1, p2 = _providers_for("[RATELIMIT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[RATELIMIT] backoff", model="fallback-model"))
    assert isinstance(response, ProviderResponse)

    _require_token_usage(response)
    assert response.text.startswith("echo(p2):")
    assert sleep_calls.count(0.05) == 1


def test_invalid_json_fallback() -> None:
    p1, p2 = _providers_for("[INVALID_JSON]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[INVALID_JSON] test", model="fallback-model"))
    assert isinstance(response, ProviderResponse)
    assert response.text.startswith("echo(p2):")


def test_timeout_no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    def fake_runner_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("time.sleep", fake_runner_sleep)

    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    response = runner.run(ProviderRequest(prompt="[TIMEOUT] no-wait", model="fallback-model"))
    assert isinstance(response, ProviderResponse)

    _require_token_usage(response)
    assert response.text.startswith("echo(p2):")
    assert all(abs(delay - 0.05) > 1e-9 for delay in sleep_calls)


def test_timeout_fallback_records_metrics(tmp_path: Path) -> None:
    p1, p2 = _providers_for("[TIMEOUT]")
    runner = Runner([p1, p2])

    metrics_path = tmp_path / "fallback.jsonl"
    response = runner.run(
        ProviderRequest(prompt="[TIMEOUT] metrics", model="fallback-model"),
        shadow=None,
        shadow_metrics_path=metrics_path,
    )
    assert isinstance(response, ProviderResponse)

    token_usage = _require_token_usage(response)
    assert response.text.startswith("echo(p2):")

    payloads = _read_metrics(metrics_path)
    call_events = [item for item in payloads if item["event"] == "provider_call"]
    error_event = next(
        item for item in call_events if item["provider"] == "p1" and item["status"] == "error"
    )
    success_event = next(
        item for item in call_events if item["provider"] == "p2" and item["status"] == "ok"
    )

    assert error_event["provider"] == "p1"
    assert error_event["attempt"] == 1
    assert error_event["error_type"] == "TimeoutError"
    assert error_event["request_fingerprint"]
    assert error_event["latency_ms"] >= 0

    assert success_event["provider"] == "p2"
    assert success_event["attempt"] == 2
    assert success_event["shadow_used"] is False
    assert success_event["tokens_out"] == token_usage.completion


def test_runner_emits_chain_failed_metric(tmp_path: Path) -> None:
    failing1 = MockProvider("p1", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    failing2 = MockProvider("p2", base_latency_ms=5, error_markers={"[TIMEOUT]"})
    runner = Runner([failing1, failing2])

    metrics_path = tmp_path / "failure.jsonl"

    with pytest.raises(AllFailedError) as exc_info:
        runner.run(
            ProviderRequest(prompt="[TIMEOUT] hard", model="fallback-model"),
            shadow=None,
            shadow_metrics_path=metrics_path,
        )
    assert isinstance(exc_info.value.__cause__, TimeoutError)

    payloads = _read_metrics(metrics_path)
    call_events = [item for item in payloads if item["event"] == "provider_call"]
    assert {event["provider"] for event in call_events} == {"p1", "p2"}
    assert all(event["status"] == "error" for event in call_events)

    chain_event = next(item for item in payloads if item["event"] == "provider_chain_failed")
    assert chain_event["provider_attempts"] == 2
    assert chain_event["last_error_type"] == "TimeoutError"
