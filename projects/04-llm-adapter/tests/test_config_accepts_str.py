from pathlib import Path

from adapter.core.config import load_provider_config


def test_cfg_accepts_str_and_path(tmp_path: Path) -> None:
    config_path = tmp_path / "provider.yml"
    config_path.write_text(
        "provider: openai\nmodel: gpt-4o-mini\nauth_env: OPENAI_API_KEY\n",
        encoding="utf-8",
    )
    assert load_provider_config(str(config_path)).model == "gpt-4o-mini"
    assert load_provider_config(config_path).provider == "openai"
