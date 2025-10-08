"""Legacy shim for :mod:`llm_adapter.runner_async_support`.

このモジュールは ``llm_adapter.runner_async_support`` パッケージへ分割されました。
移行時は以下を確認してください:

- [ ] 新実装から直接 import しているか
- [ ] 依存ファイルの循環が解消されているか
- [ ] 不要になった shim 依存を削除できるか

将来的な削除に備えて、新パッケージから公開 API を再エクスポートしています。
"""
from __future__ import annotations

from .runner_async_support import (
    AsyncProviderInvoker,
    build_shadow_log_metadata,
    emit_consensus_failure,
)

__all__ = [
    "AsyncProviderInvoker",
    "build_shadow_log_metadata",
    "emit_consensus_failure",
]
