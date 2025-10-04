"""async_runner.test_parallel の後方互換シム。

# チェックリスト:
# - [ ] 新規テストは ``projects/04-llm-adapter-shadow/tests/async_runner/parallel`` に追加する
# - [ ] 互換性が不要になったらこのシムを削除する

from .parallel import *  # noqa: F401,F403
