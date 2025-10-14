from collections.abc import Callable

import pytest

from llm_adapter.provider_spi import ProviderResponse
from llm_adapter.runner_config import ConsensusConfig
from llm_adapter.runner_parallel.consensus import compute_consensus


def fake_judge(responses: list[ProviderResponse]) -> tuple[str, float]:
    winner = responses[-1].text.strip()
    return winner, 0.75


def test_schema_validation_marks_abstentions(
    make_response: Callable[..., ProviderResponse]
) -> None:
    schema = '{"type": "object", "required": ["value"]}'
    responses = [
        make_response('{"value": "ok"}', 11),
        make_response('{"value": "ok"}', 13),
        make_response("not-json", 5),
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


def test_judge_provider_handles_runoff_round(
    make_response: Callable[..., ProviderResponse]
) -> None:
    responses = [
        make_response("A", 10),
        make_response("B", 10),
        make_response("A", 20),
        make_response("B", 20),
    ]
    result = compute_consensus(
        responses,
        config=ConsensusConfig(
            strategy="majority",
            tie_breaker="latency",
            judge="tests.consensus.test_schema_and_judge:fake_judge",
            quorum=2,
            max_rounds=4,
        ),
    )
    assert result.response.text == "B"
    assert result.tie_break_applied is True
    tie_break_reason = result.tie_break_reason
    assert tie_break_reason is not None
    assert tie_break_reason == "latency(min=10)"
    assert result.judge_name == "tests.consensus.test_schema_and_judge:fake_judge"
    assert result.judge_score == pytest.approx(0.75)
    assert result.rounds == 3
