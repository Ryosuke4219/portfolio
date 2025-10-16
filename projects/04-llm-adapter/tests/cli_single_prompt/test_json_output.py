from __future__ import annotations

import json


def test_cli_json_log_prompts(
    run_cli_main,
    provider_config_builder,
    echo_provider,
    expect_successful_echo,
) -> None:
    config_path = provider_config_builder(options={"foo": "bar"})

    result = run_cli_main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--format",
            "json",
            "--log-prompts",
        ]
    )

    request = expect_successful_echo(
        result,
        prompt="hello",
        check_output=False,
    )
    payload = json.loads(result.stdout)
    assert payload[0]["prompt"] == "hello"
    assert request.options == {"foo": "bar"}


def test_cli_json_without_prompts(
    run_cli_main,
    provider_config_builder,
    echo_provider,
    expect_successful_echo,
) -> None:
    config_path = provider_config_builder(options={"foo": "bar"})

    result = run_cli_main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
            "--format",
            "json",
        ]
    )

    expect_successful_echo(
        result,
        prompt="hello",
        check_output=False,
    )
    payload = json.loads(result.stdout)
    assert "prompt" not in payload[0]
