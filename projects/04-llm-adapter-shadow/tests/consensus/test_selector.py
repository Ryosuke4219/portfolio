from __future__ import annotations

import json

from adapter.core.aggregation_selector import AggregationSelector
from adapter.core.metrics import RunMetrics
from adapter.core.runner_api import RunnerConfig
from adapter.core.runner_execution import SingleRunResult


_BASE_METRICS = dict(
    ts="2024-01-01T00:00:00Z", run_id="run", mode="consensus", prompt_id="prompt",
    prompt_name="Prompt", seed=0, temperature=0.0, top_p=1.0, max_tokens=16,
    input_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0.0, status="ok",
    failure_kind=None, error_message=None, output_hash=None,
)


def _metrics(provider: str, text: str) -> RunMetrics:
    return RunMetrics(provider=provider, model=f"{provider}-model", output_text=text, **_BASE_METRICS)


def test_weighted_consensus_selection_serializes_metadata() -> None:
    selector = AggregationSelector()
    batch = [
        (0, SingleRunResult(metrics=_metrics("p1", "Alpha"), raw_output="Alpha")),
        (1, SingleRunResult(metrics=_metrics("p2", "Beta"), raw_output="Beta")),
        (2, SingleRunResult(metrics=_metrics("p3", "Alpha"), raw_output="Alpha")),
    ]

    for aggregate in ("weighted_vote", "weighted"):
        config = RunnerConfig(
            mode="consensus",
            aggregate=aggregate,
            provider_weights={"p1": 2.0, "p2": 0.5},
        )
        decision = selector.select("consensus", config, batch, default_judge_config=None)
        assert decision is not None
        assert decision.decision.metadata is not None

        payload = {"votes": decision.votes, "metadata": decision.decision.metadata}
        decoded = json.loads(json.dumps(payload))

        assert decoded["votes"] == 3.0
        assert isinstance(decoded["metadata"], dict)
        assert decoded["metadata"]["weighted_votes"] == {"Alpha": 3.0, "Beta": 0.5}
