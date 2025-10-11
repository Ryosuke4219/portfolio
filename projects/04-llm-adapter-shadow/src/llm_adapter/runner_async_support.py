"""Legacy shim for :mod:`llm_adapter.runner_async_support`.

この shim は廃止され、本体の ``adapter.core.runner_async_support`` へ直接 import
する必要があります。
"""
from __future__ import annotations

raise ImportError(
    "llm_adapter.runner_async_support shim は廃止されました。"
    "adapter.core.runner_async_support から直接 import してください。"
)
