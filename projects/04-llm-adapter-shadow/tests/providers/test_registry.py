from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

from adapter.core.aggregation.builtin.majority_vote import MajorityVoteStrategy
from adapter.core.aggregation.builtin.max_score import MaxScoreStrategy
from adapter.core.aggregation.builtin.registry import resolve_builtin_strategy
from adapter.core.aggregation.builtin.weighted_vote import WeightedVoteStrategy


@pytest.mark.parametrize(
    ("kind", "expected_type"),
    [
        ("majority_vote", MajorityVoteStrategy),
        ("max_score", MaxScoreStrategy),
        ("weighted_vote", WeightedVoteStrategy),
    ],
)
def test_resolve_builtin_strategy_creates_builtin(kind: str, expected_type: type[object]) -> None:
    strategy = resolve_builtin_strategy(kind)
    assert isinstance(strategy, expected_type)
    assert strategy.name == expected_type.name  # type: ignore[attr-defined]


def test_provider_factory_available_stable_when_optional_missing() -> None:
    module_name = "adapter.core.providers"
    original_gemini = sys.modules.get("adapter.core.providers.gemini")
    first_module = importlib.import_module(module_name)
    reloaded_module = first_module
    try:
        sys.modules["adapter.core.providers.gemini"] = ModuleType(
            "adapter.core.providers.gemini"
        )
        sys.modules.pop(module_name, None)
        first_module = importlib.import_module(module_name)
        baseline = first_module.ProviderFactory.available()
        sys.modules.pop(module_name, None)
        reloaded_module = importlib.import_module(module_name)
        assert reloaded_module.ProviderFactory.available() == baseline
    finally:
        if original_gemini is not None:
            sys.modules["adapter.core.providers.gemini"] = original_gemini
        else:
            sys.modules.pop("adapter.core.providers.gemini", None)
        importlib.reload(reloaded_module)
