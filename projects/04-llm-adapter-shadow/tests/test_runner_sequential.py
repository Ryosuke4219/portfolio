from __future__ import annotations

import pytest

from src.llm_adapter.errors import AllFailedError, TimeoutError
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse
from src.llm_adapter.runner_config import RunnerConfig
from src.llm_adapter.runner_sync import Runner


class _FailingProvider:
    def __init__(self, name: str, error: Exception) -> None:
        self._name = name
        self._error = error
        self.calls = 0

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return set()

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        raise self._error


def test_sequential_raises_all_failed_error_with_cause() -> None:
    request = ProviderRequest(model="gpt-test", prompt="hello")
    first_error = TimeoutError("slow")
    second_error = TimeoutError("boom")
    providers = [
        _FailingProvider("first", first_error),
        _FailingProvider("second", second_error),
    ]
    runner = Runner(providers, config=RunnerConfig())

    with pytest.raises(AllFailedError) as exc_info:
        runner.run(request)

    error = exc_info.value
    assert error.__cause__ is second_error
    assert providers[0].calls == 1
    assert providers[1].calls == 1
