"""Import 時に明示的な廃止メッセージを投げる旧 shim。"""
from __future__ import annotations

raise ModuleNotFoundError(
    "llm_adapter.runner_shared.logging は廃止されました。"
    " adapter.core.metrics や adapter.core.runner_shared.* を直接参照してください。",
    name="llm_adapter.runner_shared.logging",
)
