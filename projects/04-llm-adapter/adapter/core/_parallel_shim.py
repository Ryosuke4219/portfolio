"""並列実行のフォールバック実装。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TypeVar

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
        T = TypeVar("T")

        class ParallelExecutionError(RuntimeError):
            """並列実行時エラーのフォールバック。"""

        def run_parallel_all_sync(
            workers: Sequence[Callable[[], T]], *, max_concurrency: int | None = None
        ) -> list[T]:
            return [worker() for worker in workers]

        def run_parallel_any_sync(
            workers: Sequence[Callable[[], T]], *, max_concurrency: int | None = None
        ) -> T:
            last_error: Exception | None = None
            for worker in workers:
                try:
                    return worker()
                except Exception as exc:  # pragma: no cover - テスト環境でのみ到達
                    last_error = exc
            if last_error is not None:
                raise ParallelExecutionError(str(last_error)) from last_error
            raise ParallelExecutionError("no worker executed successfully")


__all__ = [
    "ParallelExecutionError",
    "run_parallel_all_sync",
    "run_parallel_any_sync",
]
