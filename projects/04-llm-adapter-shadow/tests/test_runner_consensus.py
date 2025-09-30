import pytest

import src.llm_adapter.runner_parallel as runner_parallel
from src.llm_adapter.errors import RetriableError, TimeoutError
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import (
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
)
from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.runner_config import ConsensusConfig, RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import (
    compute_consensus,
    ConsensusResult,
)
from src.llm_adapter.runner_sync import ProviderInvocationResult, Runner


def _response(
    text: str,
    latency: int,
    *,
    tokens_in: int = 1,
    tokens_out: int = 1,
    score: float | None = None,
) -> ProviderResponse:
    raw: dict[str, object] | None = None
    if score is not None:
        raw = {"score": float(score)}
    return ProviderResponse(
        text=text,
        latency_ms=latency,
        token_usage=TokenUsage(prompt=tokens_in, completion=tokens_out),
        raw=raw,
    )


def fake_judge(responses: list[ProviderResponse]) -> tuple[str, float]:
    winner = responses[-1].text.strip()
    return winner, 0.75


def _observation(
    provider_id: str,
    text: str,
    latency: int,
    *,
    tokens_in: int = 1,
    tokens_out: int = 1,
    cost_estimate: float | None = None,
) -> object:
    observation_type = getattr(runner_parallel, "ConsensusObservation", None)
    assert observation_type is not None, "ConsensusObservation must be defined"
    annotations = getattr(observation_type, "__annotations__", {})
    response = _response(text, latency, tokens_in=tokens_in, tokens_out=tokens_out)
    token_usage = TokenUsage(prompt=tokens_in, completion=tokens_out)
    kwargs: dict[str, object] = {
        "provider_id": provider_id,
        "response": response,
    }
    latency_field = next(
        (name for name in ("latency", "latency_ms") if name in annotations), None
    )
    assert latency_field is not None, "ConsensusObservation missing latency field"
    kwargs[latency_field] = latency
    if tokens_field := next(
        (name for name in ("tokens", "token_usage") if name in annotations), None
    ):
        kwargs[tokens_field] = token_usage
    if (
        cost_field := next(
            (name for name in ("cost_estimate", "cost") if name in annotations), None
        )
    ) or cost_estimate is not None:
        kwargs[cost_field or "cost_estimate"] = (
            cost_estimate if cost_estimate is not None else float(tokens_in + tokens_out)
        )
    if "error" in annotations:
        kwargs.setdefault("error", None)
    return observation_type(**kwargs)


def test_majority_with_latency_tie_breaker() -> None:
    responses = [
        _response("A", 40),
        _response("B", 5),
        _response("A", 35),
        _response("B", 7),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="majority", tie_breaker="latency", quorum=2),
    )
    assert isinstance(result, ConsensusResult)
    assert result.response.text == "B"
    assert result.votes == 2
    assert result.tie_break_applied is True
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason.startswith("latency")
    tie_breaker_selected = result.tie_breaker_selected
    assert tie_breaker_selected is not None
    assert tie_breaker_selected == "latency"
    assert result.rounds == 2


def test_weighted_strategy_records_scores() -> None:
    responses = [
        _response("A", 10, tokens_in=5, tokens_out=5, score=0.4),
        _response("A", 12, tokens_in=4, tokens_out=4, score=0.2),
        _response("B", 9, tokens_in=1, tokens_out=1, score=0.3),
        _response("B", 8, tokens_in=1, tokens_out=1, score=0.3),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="weighted", tie_breaker="cost", quorum=2),
    )
    assert result.response.text == "B"
    assert result.scores is not None
    assert result.scores["A"] == pytest.approx(0.6)
    assert result.scores["B"] == pytest.approx(0.6)
    assert result.winner_score == pytest.approx(0.6)
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason == "cost(min)"
    tie_breaker_selected = result.tie_breaker_selected
    assert tie_breaker_selected is not None
    assert tie_breaker_selected == "cost"


def test_max_score_strategy_prefers_best_latency() -> None:
    responses = [
        _response("A", 18, score=0.6),
        _response("B", 9, score=0.5),
        _response("A", 22, score=0.4),
        _response("B", 7, score=0.6),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="max_score", tie_breaker="latency", quorum=2),
    )
    assert result.response.text == "B"
    assert result.tie_break_applied is True
    tie_breaker_selected = result.tie_breaker_selected
    assert tie_breaker_selected is not None
    assert tie_breaker_selected == "latency"
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason.startswith("latency")
    assert result.scores is not None
    assert result.scores["A"] == pytest.approx(0.6)
    assert result.scores["B"] == pytest.approx(0.6)
    assert result.winner_score == pytest.approx(0.6)


def test_schema_validation_marks_abstentions() -> None:
    schema = '{"type": "object", "required": ["value"]}'
    responses = [
        _response('{"value": "ok"}', 11),
        _response('{"value": "ok"}', 13),
        _response("not-json", 5),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(strategy="majority", schema=schema),
    )
    assert result.response.text == '{"value": "ok"}'
    assert result.abstained == 1
    assert result.schema_checked is True
    assert result.rounds == 1
    assert result.schema_failures[2].startswith("invalid json")


def test_judge_provider_handles_runoff_round() -> None:
    responses = [
        _response("A", 10),
        _response("B", 10),
        _response("A", 20),
        _response("B", 20),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(
            strategy="majority",
            tie_breaker="latency",
            judge="tests.test_runner_consensus:fake_judge",
            quorum=2,
            max_rounds=4,
        ),
    )
    assert result.response.text == "B"
    assert result.tie_break_applied is True
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason == "latency(min=10)"
    assert result.judge_name == "tests.test_runner_consensus:fake_judge"
    assert result.judge_score == pytest.approx(0.75)
    assert result.rounds == 3


def test_max_rounds_exhausted_before_judge_round() -> None:
    responses = [
        _response("A", 10),
        _response("B", 10),
        _response("A", 20),
        _response("B", 20),
    ]
    with pytest.raises(ParallelExecutionError):
        compute_consensus(
            responses,
            config=ConsensusConfig(
                strategy="majority",
                tie_breaker="latency",
                judge="tests.test_runner_consensus:fake_judge",
                max_rounds=2,
            ),
        )


def test_weighted_vote_uses_provider_weights_and_srs_names() -> None:
    observations = [
        _observation(provider, text, latency, tokens_in=1, tokens_out=1)
        for provider, text, latency in (
            ("alpha", "A", 80),
            ("bravo", "B", 25),
            ("charlie", "B", 20),
        )
    ]
    result = compute_consensus(
        observations,
        config=ConsensusConfig(
            strategy="weighted_vote",
            tie_breaker="min_latency",
            quorum=1,
            provider_weights={"alpha": 2.0, "bravo": 0.5, "charlie": 0.5},
        ),
    )
    assert result.response.text == "A"


def test_default_tie_break_order() -> None:
    cases = [(("alpha", "A", 90, 5.0), ("bravo", "B", 35, 1.0), "B", "min_latency", "latency"), (("alpha", "A", 40, 4.0), ("bravo", "B", 40, 1.5), "B", "min_cost", "cost")]
    for entry_a, entry_b, expected, tie_breaker, fragment in cases:
        observations = [
            _observation(*entry, tokens_in=1, tokens_out=1, cost_estimate=entry[3])
            for entry in (entry_a, entry_b)
        ]
        result = compute_consensus(
            observations,
            config=ConsensusConfig(strategy="majority_vote", quorum=1),
        )
        assert result.response.text == expected
        assert result.tie_break_applied is True
        assert result.tie_breaker_selected == tie_breaker
        assert fragment in result.tie_break_reason


def test_stable_order_makes_tie_resolution_deterministic() -> None:
    observations = [
        _observation("alpha", "A", 25, tokens_in=1, tokens_out=1, cost_estimate=1.0),
        _observation("bravo", "B", 25, tokens_in=1, tokens_out=1, cost_estimate=1.0),
    ]
    flipped = list(reversed(observations))
    first = compute_consensus(
        observations,
        config=ConsensusConfig(strategy="majority_vote", quorum=1),
    )
    second = compute_consensus(
        flipped,
        config=ConsensusConfig(strategy="majority_vote", quorum=1),
    )
    assert first.response.text == second.response.text
    assert first.tie_breaker_selected == "stable_order"
    assert second.tie_breaker_selected == "stable_order"


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
