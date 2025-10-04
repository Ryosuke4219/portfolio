"""async_runner.test_parallel の後方互換シム。

新規テストは ``projects/04-llm-adapter-shadow/tests/async_runner/parallel`` に追加すること。
互換性が不要になった段階でこのシムを削除する。
"""

from __future__ import annotations

from .parallel import *  # noqa: F401,F403
