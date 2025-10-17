from __future__ import annotations

import json
from enum import Enum
from typing import Any
from types import SimpleNamespace

import pytest

from adapter.core.aggregation import AggregationCandidate, AggregationResult, MajorityVoteStrategy, WeightedVoteStrategy
from adapter.core.aggregation_controller import AggregationController
from adapter.core.aggregation_selector import AggregationDecision
from adapter.core.metrics import RunMetrics
from adapter.core.providers import ProviderResponse
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult

hypothesis = pytest.importorskip("hypothesis"); st = hypothesis.strategies; given = hypothesis.given

_RUN_BASE = dict(
    ts="2024-01-01T00:00:00Z", run_id="run", mode="consensus", prompt_id="prompt", prompt_name="Prompt", seed=0,
    temperature=0.0, top_p=1.0, max_tokens=16, input_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0.0,
    status="ok", failure_kind=None, error_message=None, output_text="", output_hash=None,
)

def _candidate(index: int, provider: str, text: str) -> AggregationCandidate:
    return AggregationCandidate(index=index, provider=provider, response=ProviderResponse(text=text), text=text, score=None)

def _metrics(provider: str) -> RunMetrics:
    return RunMetrics(provider=provider, model=f"{provider}-model", **_RUN_BASE)
@st.composite
def _json_payloads(draw: Any) -> tuple[dict[str, Any], str, str]:
    required = draw(st.lists(st.text(min_size=1, max_size=6), min_size=1, max_size=3, unique=True))
    missing = draw(st.sampled_from(required))
    entries = {key: draw(st.text(min_size=1, max_size=6)) for key in required}
    complete = json.dumps(entries)
    partial = json.dumps({k: v for k, v in entries.items() if k != missing})
    return {"type": "object", "required": required}, complete, partial
def _text_variants() -> st.SearchStrategy[tuple[str, str]]:
    alpha = st.characters(min_codepoint=97, max_codepoint=122)
    base = st.text(alpha, min_size=1, max_size=8)
    space = st.text(" \t\n", max_size=2)
    transforms = st.sampled_from([str.lower, str.upper, str.title, lambda value: value])
    return st.builds(lambda raw, pre, suf, fn: (raw, f"{pre}{fn(raw)}{suf}"), base, space, space, transforms)
@given(_text_variants())
def test_vote_strategies_normalize_bucket_keys(pair: tuple[str, str]) -> None:
    candidates = [_candidate(0, "p0", pair[0]), _candidate(1, "p1", pair[1])]
    majority = MajorityVoteStrategy().aggregate(candidates)
    weighted = WeightedVoteStrategy().aggregate(candidates)
    assert majority.metadata == {"bucket_size": 2}
    assert weighted.metadata is not None and weighted.metadata.get("bucket_size") == 2
@given(_json_payloads())
def test_vote_strategies_prefer_complete_json_bucket(data: tuple[dict[str, Any], str, str]) -> None:
    schema, complete, partial = data
    candidates = [_candidate(0, "p0", partial), _candidate(1, "p1", complete)]
    majority = MajorityVoteStrategy(schema=schema).aggregate(candidates)
    weighted = WeightedVoteStrategy(schema=schema).aggregate(candidates)
    assert majority.chosen.text == complete
    assert weighted.chosen.text == complete
class _Mode(Enum):
    CONSENSUS = "consensus"
@pytest.mark.parametrize("mode_input", ["consensus", _Mode.CONSENSUS])
def test_controller_apply_normalizes_mode_and_updates_metadata(mode_input: str | Enum) -> None:
    controller = AggregationController()
    run = SingleRunResult(metrics=_metrics("p0"), raw_output="Alpha")
    candidate = _candidate(0, "p0", "Alpha")
    decision = AggregationResult(
        chosen=candidate,
        candidates=[candidate],
        strategy="majority_vote",
        reason="majority_vote(1)",
        tie_breaker_used=None,
        metadata={"bucket_size": 1},
    )
    selection = AggregationDecision(decision=decision, lookup={0: run}, votes=1)
    calls: list[str] = []
    controller._selector = SimpleNamespace(select=lambda mode, *args, **kwargs: calls.append(mode) or selection)  # type: ignore[attr-defined]
    config = RunnerConfig(mode="consensus", aggregate="majority")
    controller.apply(mode=mode_input, config=config, batch=[(0, run)], default_judge_config=None)
    assert calls == ["consensus"]
    assert run.metrics.ci_meta["aggregate_mode"] == "consensus"
    assert run.metrics.ci_meta["aggregate_strategy"] == "majority_vote"
def test_controller_apply_returns_when_no_selection() -> None:
    controller = AggregationController()
    run = SingleRunResult(metrics=_metrics("p0"), raw_output="Alpha")
    calls: list[str] = []
    controller._selector = SimpleNamespace(select=lambda mode, *args, **kwargs: calls.append(mode) or None)  # type: ignore[attr-defined]
    config = RunnerConfig(mode="consensus", aggregate="majority")
    controller.apply(mode="consensus", config=config, batch=[(0, run)], default_judge_config=None)
    assert calls == ["consensus"]
    assert run.metrics.ci_meta == {}
def test_controller_apply_propagates_selector_errors() -> None:
    controller = AggregationController()
    run = SingleRunResult(metrics=_metrics("p0"), raw_output="Alpha")

    controller._selector = SimpleNamespace(select=lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("invalid mode")))  # type: ignore[attr-defined]
    config = RunnerConfig(mode="consensus", aggregate="majority")
    with pytest.raises(ValueError, match="invalid mode"):
        controller.apply(mode="consensus", config=config, batch=[(0, run)], default_judge_config=None)
