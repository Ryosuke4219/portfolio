from collections.abc import Callable
import dataclasses

import pytest
from src.llm_adapter.parallel_exec import ParallelExecutionError
from src.llm_adapter.provider_spi import ProviderResponse
from src.llm_adapter.runner_config import ConsensusConfig
from src.llm_adapter.runner_parallel.consensus import (
    compute_consensus,
    ConsensusObservation,
)


def test_constraints_filter_candidates_before_consensus(
    make_observation: Callable[..., ConsensusObservation]
) -> None:
    observations = [
        make_observation("slow", "A", 45, cost_estimate=0.35),
        make_observation("fast-1", "B", 12, cost_estimate=0.05),
        make_observation("fast-2", "B", 14, cost_estimate=0.08),
    ]
    config = dataclasses.replace(
        ConsensusConfig(strategy="majority", quorum=2),
        max_latency_ms=20,
        max_cost_usd=0.2,
    )

    result = compute_consensus(observations, config=config)

    assert result.response.text == "B"
    assert result.votes == 2
    assert result.rounds == 1
    assert result.tally["B"] == 2


def test_constraints_exhaust_candidates_with_failures(
    make_observation: Callable[..., ConsensusObservation]
) -> None:
    observations = [
        make_observation("slow", "A", 45, cost_estimate=0.35),
        make_observation("pricy", "B", 18, cost_estimate=0.5),
        make_observation("both", "C", 60, cost_estimate=0.45),
    ]
    config = dataclasses.replace(
        ConsensusConfig(strategy="majority", quorum=2),
        max_latency_ms=20,
        max_cost_usd=0.2,
    )

    with pytest.raises(ParallelExecutionError) as excinfo:
        compute_consensus(observations, config=config)

    error = excinfo.value
    assert isinstance(error, ParallelExecutionError)
    assert str(error) == "no responses satisfied consensus constraints"
    failures = error.failures
    assert failures is not None
    assert {entry["provider"] for entry in failures} == {"slow", "pricy", "both"}
    summaries = {entry["summary"] for entry in failures}
    assert any("latency" in summary for summary in summaries)
    assert any("cost" in summary for summary in summaries)


def test_max_rounds_exhausted_before_judge_round(
    make_response: Callable[..., ProviderResponse]
) -> None:
    responses = [
        make_response("A", 10),
        make_response("B", 10),
        make_response("A", 20),
        make_response("B", 20),
    ]
    with pytest.raises(ParallelExecutionError):
        compute_consensus(
            responses,
            config=ConsensusConfig(
                strategy="majority",
                tie_breaker="latency",
                judge="tests.consensus.test_schema_and_judge:fake_judge",
                max_rounds=2,
            ),
        )
