from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
from typing import cast, TYPE_CHECKING

import pytest

from llm_adapter.parallel_exec import run_parallel_all_async, run_parallel_any_async

ADAPTER_ROOT = Path(__file__).resolve().parents[2] / "04-llm-adapter"
if (adapter_root_str := str(ADAPTER_ROOT)) not in sys.path:
    sys.path.insert(0, adapter_root_str)

if TYPE_CHECKING:
    from adapter.core.errors import AllFailedError as AllFailedErrorType
else:
    class AllFailedErrorType(Exception):
        failures: list[object]


def _load_all_failed_error() -> type[AllFailedErrorType]:
    try:
        from adapter.core.errors import AllFailedError as loaded

        return cast(type[AllFailedErrorType], loaded)
    except ModuleNotFoundError:
        adapter_pkg = sys.modules.setdefault("adapter", types.ModuleType("adapter"))
        adapter_pkg.__path__ = [str(ADAPTER_ROOT / "adapter")]
        core_pkg = sys.modules.setdefault("adapter.core", types.ModuleType("adapter.core"))
        core_pkg.__path__ = [str(ADAPTER_ROOT / "adapter" / "core")]
        spec = spec_from_file_location(
            "adapter.core.errors", ADAPTER_ROOT / "adapter" / "core" / "errors.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover - defensive fallback
            pytest.skip("adapter.core.errors is unavailable", allow_module_level=True)
        module = module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        loaded_cls = cast(type[AllFailedErrorType], module.AllFailedError)
        return loaded_cls


AllFailedError: type[AllFailedErrorType]
AllFailedError = cast(type[AllFailedErrorType], _load_all_failed_error())


@pytest.mark.asyncio
async def test_run_parallel_any_async_retries_until_success() -> None:
    attempts: list[int] = []

    async def worker() -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise ValueError("boom")
        return "ok"

    calls: list[tuple[int, int, type[BaseException]]] = []

    async def on_retry(index: int, attempt: int, exc: BaseException) -> float:
        calls.append((index, attempt, type(exc)))
        return 0.0

    result = await run_parallel_any_async(
        [worker],
        max_attempts=5,
        on_retry=on_retry,
    )

    assert result == "ok"
    assert attempts == [1, 1]
    assert calls == [(0, 1, ValueError)]


@pytest.mark.asyncio
async def test_run_parallel_all_async_retry_directive_abort() -> None:
    async def worker() -> None:
        raise RuntimeError("fail")

    call_count = 0

    async def on_retry(index: int, attempt: int, exc: BaseException) -> float:
        nonlocal call_count
        call_count += 1
        return -1.0

    with pytest.raises(RuntimeError):
        await run_parallel_all_async(
            [worker],
            max_attempts=3,
            on_retry=on_retry,
        )

    assert call_count == 1


def test_all_failed_error_exposes_failures_list() -> None:
    error = AllFailedError("boom")

    assert isinstance(error.failures, list)
    assert error.failures == []
