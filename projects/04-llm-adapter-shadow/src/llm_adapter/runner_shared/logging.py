"""Legacy compatibility shim for :mod:`llm_adapter.runner_shared.logging`.

新モジュール移行チェックリスト (全チェック済みで削除可):
- [ ] `logging` パッケージから `base`/`status`/`events` を直接 import しているか
- [ ] 依存モジュールの循環が解消されているか
- [ ] 新 API でのメトリクス出力が監視基盤で確認済みか
"""
from __future__ import annotations

# NOTE: 新構成へ移行済みの場合、このファイルの利用箇所を削除してください。
from .logging.base import MetricsPath, resolve_event_logger
from .logging.events import log_provider_call, log_provider_skipped, log_run_metric
from .logging.status import error_family

__all__ = [
    "MetricsPath",
    "resolve_event_logger",
    "error_family",
    "log_provider_skipped",
    "log_provider_call",
    "log_run_metric",
]
