from __future__ import annotations

import pytest

from src.llm_adapter.errors import RetriableError
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner_async import AllFailedError, AsyncRunner
from tests.shadow._runner_test_helpers import _ErrorProvider, _SuccessProvider, FakeLogger

pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.mark.asyncio
async def test_all_failed_error_is_raised_and_wrapped() -> None:
    logger = FakeLogger()
    first_error = RetriableError("nope")
    runner = AsyncRunner(
        [
            _ErrorProvider("first", first_error),
            _ErrorProvider("second", RetriableError("still nope")),
        ],
        logger=logger,
    )
    request = ProviderRequest(prompt="hello", model="demo-model")

    with pytest.raises(AllFailedError) as excinfo:
        await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    assert isinstance(excinfo.value.__cause__, RetriableError)
    run_event = logger.of_type("run_metric")[0]
    assert run_event["status"] == "error"
    assert run_event["run_id"] == run_event["request_fingerprint"]
    assert run_event["mode"] == "sequential"
    assert run_event["providers"] == ["first", "second"]


@pytest.mark.asyncio
async def test_run_metric_success_includes_extended_metadata() -> None:
    logger = FakeLogger()
    runner = AsyncRunner([_SuccessProvider("primary")], logger=logger)
    request = ProviderRequest(prompt="hello", model="demo-model")

    await runner.run_async(request, shadow_metrics_path="unused.jsonl")

    run_event = logger.of_type("run_metric")[0]
    assert run_event["status"] == "ok"
    assert run_event["run_id"] == run_event["request_fingerprint"]
    assert run_event["mode"] == "sequential"
    assert run_event["providers"] == ["primary"]
