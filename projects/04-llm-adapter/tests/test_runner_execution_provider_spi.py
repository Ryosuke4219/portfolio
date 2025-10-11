"""RunnerExecution が provider SPI を adapter 実装に依存することを確認するテスト。"""

from adapter.core import provider_spi, runner_execution


def test_runner_execution_uses_adapter_provider_spi_protocol() -> None:
    """RunnerExecution が adapter.core.provider_spi.ProviderSPI を利用することを検証。"""

    assert runner_execution.ProviderSPI is provider_spi.ProviderSPI
