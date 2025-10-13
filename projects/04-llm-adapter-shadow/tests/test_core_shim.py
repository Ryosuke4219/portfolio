"""adapter.core への shim を保証するテスト。"""

from adapter.core import errors as core_errors
from adapter.core import provider_spi as core_provider_spi


def test_provider_spi_reuses_core_types() -> None:
    from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, TokenUsage

    assert issubclass(ProviderRequest, core_provider_spi.ProviderRequest)
    assert issubclass(ProviderResponse, core_provider_spi.ProviderResponse)
    assert issubclass(TokenUsage, core_provider_spi.TokenUsage)


def test_errors_reuse_core_hierarchy() -> None:
    from src.llm_adapter.errors import RateLimitError, RetriableError, TimeoutError

    assert RateLimitError is core_errors.RateLimitError
    assert RetriableError is core_errors.RetriableError
    assert TimeoutError is core_errors.TimeoutError
