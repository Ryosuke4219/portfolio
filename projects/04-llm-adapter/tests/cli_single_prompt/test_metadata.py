from __future__ import annotations


def test_cli_passes_metadata(
    run_cli_main,
    provider_config_builder,
    expect_successful_echo,
    echo_provider,
) -> None:
    config_path = provider_config_builder(
        metadata={"run_id": "cli-demo"},
        options={"foo": "bar"},
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
    assert request.metadata == {"run_id": "cli-demo"}


def test_cli_ignores_non_mapping_metadata(
    run_cli_main,
    provider_config_builder,
    expect_successful_echo,
    echo_provider,
) -> None:
    config_path = provider_config_builder(metadata="cli-demo")

    result = run_cli_main(
        [
            "--provider",
            str(config_path),
            "--prompt",
            "hello",
        ]
    )

    request = expect_successful_echo(result, prompt="hello")
    assert request.metadata is None
