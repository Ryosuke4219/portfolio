from typing import Any, Mapping

import pytest

from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage
from src.llm_adapter.runner_config import ConsensusConfig, RunnerConfig, RunnerMode
from src.llm_adapter.runner_parallel import (
    ConsensusFailure,
    ConsensusResult,
    ParallelExecutionError,
    compute_consensus,
)
from src.llm_adapter.runner_sync import Runner


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, record: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(record)))


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
    assert result.tie_break_reason.startswith("latency")
    assert result.tie_breaker_selected == "latency"
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
    assert result.tie_break_reason == "cost(min)"
    assert result.tie_breaker_selected == "cost"


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
    assert result.tie_breaker_selected == "latency"
    assert result.tie_break_reason.startswith("latency")
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
    assert result.tie_break_reason == "latency(min=10)"
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


def test_compute_consensus_records_failures() -> None:
    responses = [_response("A", 10), _response("A", 11)]
    failures = [
        ConsensusFailure(
            provider="fail",
            attempt=1,
            error_type="RuntimeError",
            error_message="boom",
        )
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(quorum=2),
        failures=failures,
    )
    assert result.response.text == "A"
    assert result.failures == tuple(failures)


def test_runner_consensus_logs_partial_failures() -> None:
    class _StaticProvider:
        def __init__(self, name: str, text: str, latency_ms: int) -> None:
            self._name = name
            self._text = text
            self._latency = latency_ms

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                text=self._text,
                latency_ms=self._latency,
                token_usage=TokenUsage(prompt=1, completion=1),
                model=request.model,
                finish_reason="stop",
            )

    class _FailingProvider:
        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request: ProviderRequest) -> ProviderResponse:
            raise RuntimeError("boom")

    providers = [
        _StaticProvider("p1", "agree", latency_ms=5),
        _FailingProvider("fail"),
        _StaticProvider("p2", "agree", latency_ms=7),
    ]
    logger = _CapturingLogger()
    runner = Runner(
        providers,
        logger=logger,
        config=RunnerConfig(
            mode=RunnerMode.CONSENSUS,
            max_concurrency=3,
            consensus=ConsensusConfig(quorum=2),
        ),
    )

    request = ProviderRequest(prompt="hello", model="m-consensus")
    response = runner.run(request)

    assert response.text == "agree"

    consensus_event = next(
        record for record in logger.events if record[0] == "consensus_vote"
    )[1]
    assert consensus_event["failures_total"] == 1
    failure_entry = consensus_event["failures"][0]
    assert failure_entry["provider"] == "fail"
    assert failure_entry["error_type"] == "RuntimeError"

