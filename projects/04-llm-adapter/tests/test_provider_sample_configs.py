"""プロバイダ設定サンプルの整合性テスト。"""

from __future__ import annotations

from pathlib import Path

from adapter.core.config import load_budget_book, load_provider_config

ALLOWED_PROVIDERS = {"simulated", "openai", "gemini"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_DIR = PROJECT_ROOT / "adapter" / "config" / "providers"
BUDGETS_PATH = PROJECT_ROOT / "adapter" / "config" / "budgets.yaml"


def test_sample_provider_configs_are_supported() -> None:
    provider_paths = sorted(PROVIDERS_DIR.glob("*.yaml"))
    assert provider_paths, "プロバイダ設定ファイルが存在しません"

    for path in provider_paths:
        config = load_provider_config(path)
        assert (
            config.provider in ALLOWED_PROVIDERS
        ), f"{path.name} の provider={config.provider} は許可されていません"


def test_budget_overrides_are_supported() -> None:
    budget_book = load_budget_book(BUDGETS_PATH)
    override_providers = set(budget_book.overrides.keys())
    assert override_providers <= ALLOWED_PROVIDERS
