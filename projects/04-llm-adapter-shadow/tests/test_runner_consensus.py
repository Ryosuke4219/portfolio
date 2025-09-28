import json
from collections.abc import Sequence
import pytest

from src.llm_adapter.provider_spi import ProviderResponse, TokenUsage
from src.llm_adapter.runner_config import ConsensusConfig
from src.llm_adapter.runner_parallel import ParallelExecutionError, compute_consensus, resolve_consensus


def _resp(
    text: str,
    *,
    latency: int = 10,
    tokens: tuple[int, int] = (1, 1),
    raw: dict | None = None,
) -> ProviderResponse:
    return ProviderResponse(text=text, latency_ms=latency, token_usage=TokenUsage(prompt=tokens[0], completion=tokens[1]), raw=raw)


def test_compute_consensus_variants() -> None:
    cases = [
        (
            ConsensusConfig(strategy="majority", tie_breaker="latency", quorum=2),
            [_resp("A", latency=20), _resp("B", latency=15), _resp("A", latency=40), _resp("B", latency=10)],
            "B",
            "latency",
        ),
        (
            ConsensusConfig(strategy="majority", tie_breaker="cost", quorum=2),
            [_resp("A", tokens=(10, 5)), _resp("B", tokens=(1, 1)), _resp("A", tokens=(1, 1)), _resp("B", tokens=(20, 20))],
            "A",
            "cost",
        ),
        (
            ConsensusConfig(strategy="weighted", quorum=1),
            [_resp("A", raw={"weight": 1.0}), _resp("B", raw={"weight": 4.0}), _resp("A", raw={"weight": 2.0})],
            "B",
            "strategy=weighted",
        ),
    ]
    for config, responses, expected, reason_hint in cases:
        result = compute_consensus(responses, config=config)
        assert result.response.text == expected
        assert reason_hint in result.reason
        if config.strategy == "weighted":
            assert result.score == pytest.approx(4.0)


def test_resolve_consensus_schema_and_judge() -> None:
    schema = json.dumps({"type": "object", "required": ["answer"]})
    responses = [_resp(json.dumps({"answer": "A"})), _resp("not json"), _resp(json.dumps({"answer": "B"}))]
    config = ConsensusConfig(strategy="majority", schema=schema, judge="mock", max_rounds=2)

    def _judge(candidates: Sequence[ProviderResponse]) -> ProviderResponse | None:
        return next((resp for resp in candidates if "B" in resp.text), None)

    result = resolve_consensus(responses, config=config, judge=_judge)
    assert json.loads(result.response.text)["answer"] == "B"
    assert result.reason == "judge=mock"


def test_resolve_consensus_unresolved_tie() -> None:
    with pytest.raises(ParallelExecutionError):
        resolve_consensus([_resp("A"), _resp("B")], config=ConsensusConfig(strategy="majority"))
