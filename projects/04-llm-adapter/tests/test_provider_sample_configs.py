"""プロバイダ設定サンプルの整合性テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core.loader import load_budget_book, load_provider_config

ALLOWED_PROVIDERS = {"simulated", "openai", "gemini", "ollama", "openrouter"}


@pytest.mark.parametrize(
    "config_path",
    sorted(
        (Path(__file__).resolve().parents[1] / "adapter" / "config" / "providers").glob("*.yaml")
    ),
)
def test_provider_configs_use_allowed_providers(config_path: Path) -> None:
    config = load_provider_config(config_path)
    assert config.provider in ALLOWED_PROVIDERS


def test_budget_overrides_use_allowed_providers() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    budget_book = load_budget_book(root_dir / "adapter" / "config" / "budgets.yaml")
    assert set(budget_book.overrides) <= ALLOWED_PROVIDERS
