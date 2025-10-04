"""Legacy shim for the parallel coordinators package."""

from __future__ import annotations

# NOTE: 旧 ``coordinators.py`` は以下のモジュールへ分割されました。
# - ``coordinators/base.py``: モード正規化ヘルパと ``_ParallelCoordinatorBase``。
# - ``coordinators/all.py``: ``ParallelAll`` 固有の並列制御ロジック。
# - ``coordinators/any.py``: ``ParallelAny`` 固有の逐次確定ロジック。
# 既存 import 互換性のため、従来のシンボルを再エクスポートします。

from .coordinators import (
    ProviderFailureSummary,
    _ParallelAllCoordinator,
    _ParallelAnyCoordinator,
    _ParallelCoordinatorBase,
    _is_parallel_any_mode,
    _normalize_mode_value,
    build_cancelled_result,
)

__all__ = [
    "ProviderFailureSummary",
    "_ParallelAllCoordinator",
    "_ParallelAnyCoordinator",
    "_ParallelCoordinatorBase",
    "_is_parallel_any_mode",
    "_normalize_mode_value",
    "build_cancelled_result",
]
