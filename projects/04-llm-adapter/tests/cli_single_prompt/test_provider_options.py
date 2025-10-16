from __future__ import annotations


def test_cli_fake_provider(
    run_cli_main,
    expect_successful_echo,
    provider_config_builder,
    echo_provider,
) -> None:
    config_path = provider_config_builder(
        options={"foo": "bar"},
        max_tokens=128,
    )

    result = run_cli_main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )

    request = expect_successful_echo(result, prompt="hello")
    assert request.max_tokens == 128
    assert request.options == {"foo": "bar"}


def test_cli_provider_option_coerces_types(
    run_cli_main,
    expect_successful_echo,
    provider_config_builder,
    echo_provider,
) -> None:
    config_path = provider_config_builder()

    result = run_cli_main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--provider-option",
            "stream=true",
            "--provider-option",
            "max_tokens=42",
        ]
    )

    request = expect_successful_echo(result, prompt="hello")
    assert request.options["stream"] is True
    assert request.options["max_tokens"] == 42
    assert isinstance(request.options["max_tokens"], int)


def test_run_prompts_provider_option_coerces_types(
    run_cli_prompts,
    expect_successful_echo,
    provider_config_builder,
    echo_provider,
) -> None:
    config_path = provider_config_builder(options={"foo": "bar"})

    result = run_cli_prompts(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--provider-option",
            "stream=true",
            "--provider-option",
            "max_tokens=42",
        ]
    )

    request = expect_successful_echo(result, prompt="hello")
    assert request.options["foo"] == "bar"
    assert request.options["stream"] is True
    assert request.options["max_tokens"] == 42
    assert isinstance(request.options["max_tokens"], int)
