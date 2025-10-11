from pathlib import Path


def test_eslint_config_ignores_shadow_directory() -> None:
    config_text = Path("eslint.config.js").read_text(encoding="utf-8")

    assert "'projects/04-llm-adapter/**'" in config_text
    assert "'projects/04-llm-adapter-shadow/**'" not in config_text
