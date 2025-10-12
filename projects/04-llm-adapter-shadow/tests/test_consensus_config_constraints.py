import dataclasses

import pytest
from src.llm_adapter.runner_config import ConsensusConfig


def test_consensus_config_defaults_include_constraints() -> None:
    config = ConsensusConfig()

    assert config.max_latency_ms is None
    assert config.max_cost_usd is None


def test_consensus_config_equality_accounts_for_constraints() -> None:
    base = ConsensusConfig()
    with_overrides = ConsensusConfig(max_latency_ms=100, max_cost_usd=1.5)

    assert base == ConsensusConfig()
    assert base != with_overrides


def test_consensus_config_is_frozen() -> None:
    config = ConsensusConfig()

    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        object.__setattr__(config, "max_latency_ms", 1)
