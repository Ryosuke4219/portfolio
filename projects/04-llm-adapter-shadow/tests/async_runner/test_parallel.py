"""レガシー互換シム。

チェックリスト:
- [ ] 新規テストは ``projects/04-llm-adapter-shadow/tests/async_runner/parallel`` に追加する
- [ ] 互換性が不要になったらこのシムを削除する
"""

from __future__ import annotations

from .parallel import *  # noqa: F401,F403
