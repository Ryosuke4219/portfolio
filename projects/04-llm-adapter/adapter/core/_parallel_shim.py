"""並列実行のフォールバック実装。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.parallel_exec import (  # type: ignore[import-not-found]
        ParallelExecutionError as _ParallelExecutionError,
        run_parallel_all_sync as _run_parallel_all_sync,
        run_parallel_any_sync as _run_parallel_any_sync,
    )

    ParallelExecutionError = _ParallelExecutionError
    run_parallel_all_sync = _run_parallel_all_sync
    run_parallel_any_sync = _run_parallel_any_sync
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.parallel_exec import (  # type: ignore[import-not-found]
            ParallelExecutionError,
            run_parallel_all_sync,
            run_parallel_any_sync,
        )
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        from concurrent.futures import (
            FIRST_COMPLETED,
            Future,
            ThreadPoolExecutor,
            as_completed,
            wait,
        )

        T = TypeVar("T")

        class ParallelExecutionError(RuntimeError):
            """並列実行時エラーのフォールバック。"""

            def __init__(
                self,
                message: str,
                *,
                failures: Iterable[BaseException] | None = None,
                batch: Any | None = None,
            ) -> None:
                super().__init__(message)
                self.failures = list(failures) if failures is not None else None
                self.batch = batch

        def _normalize_concurrency(total: int, limit: int | None) -> int:
            if limit is None or limit <= 0:
                return max(total, 1)
            return max(min(limit, total), 1)

        def run_parallel_all_sync(
            workers: Sequence[Callable[[], T]], *, max_concurrency: int | None = None
        ) -> list[T]:
            if not workers:
                raise ValueError("workers must not be empty")
            max_workers = _normalize_concurrency(len(workers), max_concurrency)
            results: list[T] = [None] * len(workers)  # type: ignore[list-item]
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(worker): index for index, worker in enumerate(workers)
                }
                try:
                    for future in as_completed(future_map):
                        results[future_map[future]] = future.result()
                except BaseException:  # noqa: BLE001
                    for pending in future_map:
                        pending.cancel()
                    raise
            return results

        def run_parallel_any_sync(
            workers: Sequence[Callable[[], T]], *, max_concurrency: int | None = None
        ) -> T:
            if not workers:
                raise ValueError("workers must not be empty")
            total_workers = len(workers)
            max_workers = _normalize_concurrency(total_workers, max_concurrency)
            errors: list[BaseException] = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map: dict[Future[T], int] = {}
                next_index = 0

                def _submit_next() -> None:
                    nonlocal next_index
                    if next_index >= total_workers:
                        return
                    index = next_index
                    next_index += 1
                    future_map[executor.submit(workers[index])] = index

                for _ in range(min(max_workers, total_workers)):
                    _submit_next()

                while future_map:
                    done, _ = wait(future_map, return_when=FIRST_COMPLETED)
                    for future in done:
                        index = future_map.pop(future, None)
                        if index is None:
                            continue
                        try:
                            return future.result()
                        except BaseException as exc:  # noqa: BLE001
                            errors.append(exc)
                            _submit_next()
            if errors:
                raise ParallelExecutionError("all workers failed", failures=errors) from errors[-1]
            raise ParallelExecutionError("all workers failed")


__all__ = [
    "ParallelExecutionError",
    "run_parallel_all_sync",
    "run_parallel_any_sync",
]
