from __future__ import annotations


def test_cli_model_override_argument(
    run_cli_main,
    expect_successful_echo,
    provider_config_builder,
    echo_provider,
) -> None:
    config_path = provider_config_builder(model="dummy-config", max_tokens=128)

    result = run_cli_main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--model",
            "cli-model",
        ]
    )

    request = expect_successful_echo(result, prompt="hello")
    assert request.model == "cli-model"


def test_run_prompts_model_override_argument(
    run_cli_prompts,
    expect_successful_echo,
    expect_single_config,
    provider_config_builder,
    echo_provider,
) -> None:
    config_path = provider_config_builder(model="dummy-config", max_tokens=64)

    result = run_cli_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--model",
            "cli-model",
        ]
    )

    request = expect_successful_echo(result, prompt="hello")
    assert request.model == "cli-model"

    config = expect_single_config(model="cli-model")
    assert config.raw.get("model") == "cli-model"
