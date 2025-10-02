import pytest

from src.llm_adapter.errors import RetriableError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner_config import ConsensusConfig, RunnerConfig, RunnerMode
from src.llm_adapter.runner_sync import ProviderInvocationResult, Runner


def test_runner_consensus_failure_details(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        MockProvider("timeout", base_latency_ms=1, error_markers=set()),
        MockProvider("invalid", base_latency_ms=1, error_markers=set()),
    ]
    runner = Runner(
        providers,
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=2,
        ),
    )
    request = ProviderRequest(
        prompt="consensus failure",
        model="consensus-failure",
    )

    errors = [TimeoutError("simulated timeout"), RetriableError("simulated invalid JSON")]
    invocations = [
        ProviderInvocationResult(
            provider=provider,
            attempt=index,
            total_providers=len(providers),
            response=None,
            error=error,
            latency_ms=25,
            tokens_in=None,
            tokens_out=None,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        )
        for index, (provider, error) in enumerate(zip(providers, errors, strict=True), start=1)
    ]

    def _fake_run_parallel_all_sync(workers, *, max_concurrency=None):
        return invocations

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync.run_parallel_all_sync",
        _fake_run_parallel_all_sync,
    )

    with pytest.raises(ParallelExecutionError) as exc_info:
        runner.run(request)

    error = exc_info.value
    failures = error.failures if hasattr(error, "failures") else None
    expected = [
        {
            "provider": invocation.provider.name(),
            "attempt": str(invocation.attempt),
            "summary": f"{type(invocation.error).__name__}: {invocation.error}",
        }
        for invocation in invocations
    ]
    assert failures == expected
    message = str(error)
    for detail in expected:
        assert detail["provider"] in message
        assert detail["attempt"] in message
        assert detail["summary"] in message


def test_runner_consensus_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        MockProvider("alpha", base_latency_ms=1, error_markers=set()),
        MockProvider("bravo", base_latency_ms=1, error_markers=set()),
        MockProvider("charlie", base_latency_ms=1, error_markers=set()),
    ]
    runner = Runner(
        providers,
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(strategy="majority", quorum=2),
        ),
    )
    request = ProviderRequest(
        prompt="consensus partial", model="consensus-partial"
    )

    response_alpha = ProviderResponse(
        text="A", latency_ms=10, token_usage=TokenUsage(prompt=1, completion=1)
    )
    response_charlie = ProviderResponse(
        text="A", latency_ms=12, token_usage=TokenUsage(prompt=1, completion=1)
    )
    invocations = [
        ProviderInvocationResult(
            provider=providers[0],
            attempt=1,
            total_providers=len(providers),
            response=response_alpha,
            error=None,
            latency_ms=10,
            tokens_in=1,
            tokens_out=1,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
        ProviderInvocationResult(
            provider=providers[1],
            attempt=2,
            total_providers=len(providers),
            response=None,
            error=TimeoutError("simulated timeout"),
            latency_ms=15,
            tokens_in=None,
            tokens_out=None,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
        ProviderInvocationResult(
            provider=providers[2],
            attempt=3,
            total_providers=len(providers),
            response=response_charlie,
            error=None,
            latency_ms=12,
            tokens_in=1,
            tokens_out=1,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
    ]

    def _fake_run_parallel_all_sync(workers, *, max_concurrency=None):
        return invocations

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync.run_parallel_all_sync",
        _fake_run_parallel_all_sync,
    )

    response = runner.run(request)
    assert response.text == "A"


def test_runner_consensus_weighted_vote_prefers_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [
        MockProvider("alpha", base_latency_ms=1, error_markers=set()),
        MockProvider("bravo", base_latency_ms=1, error_markers=set()),
    ]
    runner = Runner(
        providers,
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=2,
            consensus=ConsensusConfig(
                strategy="weighted_vote",
                provider_weights={"alpha": 3.0, "bravo": 0.5},
                tie_breaker="min_latency",
                quorum=1,
            ),
        ),
    )
    request = ProviderRequest(prompt="weighted", model="weighted-consensus")

    response_alpha = ProviderResponse(
        text="alpha answer",
        latency_ms=120,
        token_usage=TokenUsage(prompt=1, completion=1),
    )
    response_bravo = ProviderResponse(
        text="bravo answer",
        latency_ms=20,
        token_usage=TokenUsage(prompt=1, completion=1),
    )

    invocations = [
        ProviderInvocationResult(
            provider=providers[0],
            attempt=1,
            total_providers=len(providers),
            response=response_alpha,
            error=None,
            latency_ms=response_alpha.latency_ms,
            tokens_in=1,
            tokens_out=1,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
        ProviderInvocationResult(
            provider=providers[1],
            attempt=2,
            total_providers=len(providers),
            response=response_bravo,
            error=None,
            latency_ms=response_bravo.latency_ms,
            tokens_in=1,
            tokens_out=1,
            shadow_metrics=None,
            shadow_metrics_extra=None,
            provider_call_logged=True,
        ),
    ]

    def _fake_run_parallel_all_sync(workers, *, max_concurrency=None):  # noqa: ANN001
        return invocations

    monkeypatch.setattr(
        "src.llm_adapter.runner_sync.run_parallel_all_sync",
        _fake_run_parallel_all_sync,
    )

    response = runner.run(request)
    assert response.text == "alpha answer"
