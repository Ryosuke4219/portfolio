from __future__ import annotations

import pytest

from adapter.core import aggregation as aggregation_module
from adapter.core.aggregation import (
    AggregationCandidate,
    AggregationResult,
    AggregationStrategy,
)
from adapter.core.aggregation_controller import AggregationController
from adapter.core.providers import ProviderResponse
from adapter.core.runner_api import RunnerConfig


def _candidate(index: int, provider: str, text: str) -> AggregationCandidate:
    response = ProviderResponse(output_text=text)
    return AggregationCandidate(
        index=index,
        provider=provider,
        response=response,
        text=text,
    )


def test_weighted_vote_strategy_prefers_heavier_bucket() -> None:
    weights = {"openai": 2.0, "anthropic": 0.5}
    strategy = AggregationStrategy.from_string("weighted_vote", provider_weights=weights)
    candidates = [
        _candidate(0, "openai", "answer"),
        _candidate(1, "azure", "answer"),
        _candidate(2, "anthropic", "alt"),
    ]
    result = strategy.aggregate(candidates)
    assert result.chosen.provider == "openai"
    assert result.strategy == "weighted_vote"
    assert result.reason == "weight=3.0"
    assert result.tie_breaker_used == "first"
    assert result.metadata == {"bucket_weight": 3.0}


class _FakeStrategy:
    name = "fake"

    def aggregate(
        self,
        _candidates: list[AggregationCandidate],
        *,
        tiebreaker: object | None = None,
    ) -> AggregationResult:
        raise AssertionError("aggregate should not be invoked")


def test_aggregation_controller_passes_provider_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = AggregationController()
    config = RunnerConfig(
        mode="consensus",
        aggregate="weighted_vote",
        provider_weights={"openai": 1.5},
    )
    captured: dict[str, object] = {}

    def fake_from_string(kind: str, **kwargs: object) -> _FakeStrategy:
        captured["kind"] = kind
        captured["kwargs"] = kwargs
        return _FakeStrategy()

    monkeypatch.setattr(
        aggregation_module.AggregationStrategy,
        "from_string",
        staticmethod(fake_from_string),
    )

    strategy = controller._resolve_aggregation_strategy(
        "consensus",
        config,
        default_judge_config=None,
    )

    assert isinstance(strategy, _FakeStrategy)
    assert captured["kind"] == "weighted_vote"
    assert captured["kwargs"]["provider_weights"] == {"openai": 1.5}
    assert "model" not in captured["kwargs"]

