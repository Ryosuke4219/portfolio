# Async Runner/Parallel リファクタリングタスク

## 1. 例外ロギングの共通化
- 対象: `AsyncRunner._invoke_provider_async` と `Runner._invoke_provider_sync` の例外ハンドリング。【F:projects/04-llm-adapter-shadow/src/llm_adapter/runner_async.py†L76-L220】【F:projects/04-llm-adapter-shadow/src/llm_adapter/runner_sync.py†L74-L155】
- 内容: 例外種別ごとに重複している `log_provider_call` 呼び出しを `runner_shared` 側に共通関数として抽出し、例外→ログ出力のマッピングを一元化する。
- 期待効果: ロジック重複を排除し、エラー種別追加時に両実装へ同変更を反映するコストを削減。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/test_runner_async.py::test_async_runner_matches_sync` 等で同期・非同期挙動の整合性を確認。【F:projects/04-llm-adapter-shadow/tests/test_runner_async.py†L192-L260】

## 2. `run_async` の逐次フェーズ切り出し
- 対象: `AsyncRunner.run_async` の逐次実行ブロック。【F:projects/04-llm-adapter-shadow/src/llm_adapter/runner_async.py†L222-L332】
- 内容: 逐次フェーズを `_run_sequential_async` などのプライベート関数へ移し、戻り値（成功レスポンス/例外）とメトリクス記録を関数側で完結させる。
- 期待効果: `run_async` 本体の責務を入口制御に限定し、分岐ごとの読みやすさを向上。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/test_runner_async.py::test_async_runner_matches_sync` で逐次モードの挙動を回帰確認。【F:projects/04-llm-adapter-shadow/tests/test_runner_async.py†L192-L260】

## 3. `run_async` の並列/コンセンサスフェーズ分離
- 対象: `AsyncRunner.run_async` の並列系分岐と再試行制御ロジック。【F:projects/04-llm-adapter-shadow/src/llm_adapter/runner_async.py†L336-L605】
- 内容: 並列実行・再試行・コンセンサス集約を担当するコンテキストクラス（例: `_ParallelExecutionContext`）を導入し、ワーカー生成・再試行コールバック・メトリクス送出をクラスメソッドに整理する。
- 期待効果: ネストした内部関数を削減し、並列制御の単体テスト容易性を向上。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/test_runner_async.py` 全体および `tests/test_runner_consensus.py` のCIシナリオで後方互換を保証。【F:projects/04-llm-adapter-shadow/tests/test_runner_async.py†L1-L360】【F:projects/04-llm-adapter-shadow/tests/test_runner_consensus.py†L1-L220】

## 4. 並列ヘルパーの再試行制御共通化
- 対象: `run_parallel_any_async` と `run_parallel_all_async` の再試行・attempt管理ロジック。【F:projects/04-llm-adapter-shadow/src/llm_adapter/runner_parallel.py†L166-L320】
- 内容: `_reserve_attempt` / `_record_failure` / `_normalize_retry_directive` など重複する内部関数群を `ParallelRetryController`（仮称）にまとめ、ANY/ALL 双方が同じ状態管理を利用できるようにする。
- 期待効果: 並列系APIの振る舞い差異を明確化し、再試行ポリシー変更時の改修範囲を局所化。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/test_runner_async.py::test_parallel_any_fallbacks` 系と `tests/test_runner_consensus.py` を中心に再試行パスの回帰確認。【F:projects/04-llm-adapter-shadow/tests/test_runner_async.py†L340-L620】【F:projects/04-llm-adapter-shadow/tests/test_runner_consensus.py†L1-L220】
