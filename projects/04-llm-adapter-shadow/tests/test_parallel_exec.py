import pytest

from src.llm_adapter.parallel_exec import run_parallel_all_async, run_parallel_any_async


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
