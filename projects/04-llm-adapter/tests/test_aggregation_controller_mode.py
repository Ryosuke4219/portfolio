from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from adapter.core.aggregation_controller import AggregationController
from adapter.core.aggregation_selector import AggregationDecision
from adapter.core.metrics import RunMetrics
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult


class _ModeEnum(str, Enum):
    CONSENSUS = "consensus"


def _metrics(provider: str) -> RunMetrics:
    return RunMetrics(
        ts="2024-01-01T00:00:00Z",
        run_id="run",
        provider=provider,
        model="model",
        mode="consensus",
        prompt_id="prompt",
        prompt_name="Prompt",
        seed=0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        cost_usd=0.0,
        status="ok",
        failure_kind=None,
        error_message=None,
        output_text="Alpha",
        output_hash=None,
    )


def test_apply_records_string_mode_when_enum_input() -> None:
    controller = AggregationController()
    metrics = _metrics("p1")
    result = SingleRunResult(metrics=metrics, raw_output="Alpha")
    candidate = SimpleNamespace(
        index=0,
        provider="p1",
        response=SimpleNamespace(text="Alpha"),
        text="Alpha",
        score=1.0,
    )
    decision = SimpleNamespace(
        chosen=candidate,
        candidates=[candidate],
        strategy="majority_vote",
        reason=None,
        tie_breaker_used=None,
        metadata={"bucket_size": 1},
    )
    selection = AggregationDecision(
        decision=decision,
        lookup={0: result},
        votes=1,
    )

    class _Selector:
        def select(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return selection

    controller._selector = _Selector()  # type: ignore[attr-defined]
    config = RunnerConfig(mode="consensus", aggregate="majority", quorum=1)

    controller.apply(
        mode=_ModeEnum.CONSENSUS,
        config=config,
        batch=[(0, result)],
        default_judge_config=None,
    )

    assert result.metrics.ci_meta["aggregate_mode"] == "consensus"
    assert result.metrics.ci_meta["consensus"]["strategy"] == "majority_vote"
