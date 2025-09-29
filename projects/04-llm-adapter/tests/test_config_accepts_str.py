from pathlib import Path

import pytest
from adapter.core.config import ConfigError, load_provider_config


def test_cfg_accepts_str_and_path(tmp_path: Path) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "schema_version: 1\nprovider: openai\nmodel: gpt-4o-mini\nauth_env: OPENAI_API_KEY\n",
        encoding="utf-8",
    )
    assert load_provider_config(str(config_path)).model == "gpt-4o-mini"
    assert load_provider_config(config_path).provider == "openai"
    assert load_provider_config(config_path).schema_version == 1


def test_cfg_missing_required_field(tmp_path: Path) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_provider_config(config_path)
    assert "model" in str(exc.value)


def test_cfg_invalid_type(tmp_path: Path) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: openai\nmodel: gpt-4o\nmax_tokens: not-an-int\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_provider_config(config_path)
    assert "max_tokens" in str(exc.value)
