"""プロバイダ設定サンプルの整合性テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapter.core.loader import load_budget_book, load_provider_config

ALLOWED_PROVIDERS = {"simulated", "openai", "gemini", "ollama", "openrouter"}
AUTH_REQUIRED_PROVIDERS = {"openai", "gemini", "openrouter"}


@pytest.mark.parametrize(
    "config_path",
    sorted(
        (Path(__file__).resolve().parents[1] / "adapter" / "config" / "providers").glob("*.yaml")
    ),
)
def test_provider_configs_use_allowed_providers(config_path: Path) -> None:
    config = load_provider_config(config_path)
    assert config.provider in ALLOWED_PROVIDERS
    if config.provider in {"openai", "gemini", "openrouter"}:
        assert config.auth_env, "認証環境変数が未設定です"
    if config.provider in AUTH_REQUIRED_PROVIDERS:
        assert isinstance(config.auth_env, str) and config.auth_env.strip()


def test_budget_overrides_use_allowed_providers() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    budget_book = load_budget_book(root_dir / "adapter" / "config" / "budgets.yaml")
    assert set(budget_book.overrides) <= ALLOWED_PROVIDERS


def test_openrouter_config_declares_auth_and_base_url_env() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = load_provider_config(root_dir / "adapter" / "config" / "providers" / "openrouter.yaml")
    assert config.auth_env == "OPENROUTER_API_KEY"
    assert config.raw.get("base_url_env") == "OPENROUTER_BASE_URL"
    env_info = config.raw.get("env")
    assert isinstance(env_info, dict)
    assert env_info.get("OPENROUTER_API_KEY") == "OPENROUTER_API_KEY"
    assert env_info.get("OPENROUTER_BASE_URL") == "https://openrouter.ai/api/v1"
