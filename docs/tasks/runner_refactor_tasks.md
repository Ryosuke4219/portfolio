# Async Runner/Parallel リファクタリングタスク

## 1. AsyncRunner のイベント記録共通化
- 対象: `AsyncRunner.run_async` と `_emit_provider_call` / `_emit_chain_failed` のイベント構築処理。【F:projects/04-llm-adapter/adapter/core/runner_async.py†L40-L126】
- 内容: 成功・失敗・チェーン失敗イベントで共通化できるペイロード整形をヘルパに切り出し、イベント種別ごとの差分だけを個別メソッドに残す。
- 期待効果: ロギング仕様変更時にイベント間の整合性を維持しやすくし、`test_async_runner` 系で検証される `error_family` などのフィールド重複定義を排除できる。【F:projects/04-llm-adapter/tests/runner_async/test_async_runner.py†L57-L117】
- 検証: `pytest projects/04-llm-adapter/tests/runner_async/test_async_runner.py::test_async_rate_limit_triggers_backoff` などでイベント内容の後方互換を確認。

## 2. AsyncRunner の逐次/コンセンサス制御分離
- 対象: `AsyncRunner.run_async` の逐次ループおよびコンセンサス分岐。【F:projects/04-llm-adapter/adapter/core/runner_async.py†L56-L90】
- 内容: プロバイダ逐次試行とコンセンサス完了判定を `_run_sequential_once` / `_finalize_consensus` などに分離し、`errors` 集約や `ParallelExecutionError` 生成を責務ごとに整理する。
- 期待効果: リトライ戦略の追加時に逐次フローとコンセンサス例外処理を独立してテスト可能にし、タイムアウト伝播の仕様を明確化する。【F:projects/04-llm-adapter/tests/runner_async/test_async_runner.py†L106-L117】
- 検証: `pytest projects/04-llm-adapter/tests/runner_async/test_async_runner.py::test_async_consensus_all_timeout_propagates_original_error`。

## 3. RunnerExecution の単一実行パイプライン整理
- 対象: `RunnerExecution._run_single` と関連ヘルパ（シャドウ記録・メトリクス集計・スキーマ検証）。【F:projects/04-llm-adapter/adapter/core/runner_execution.py†L96-L236】
- 内容: 予算評価→スキーマ検証→メトリクス確定の順序を組み替え、`finalize_run_metrics` 呼び出しに渡すパラメータを小さなデータクラスへまとめる。シャドウ結果や停止理由の伝播も同データクラスで扱う。
- 期待効果: シャドウプロバイダ/スキーマ違反/予算停止の分岐が明確になり、`test_runner_execution_records_shadow_budget_and_schema` の期待値更新が局所化する。【F:projects/04-llm-adapter/tests/compare_runner_parallel/test_budgeting.py†L20-L130】
- 検証: `pytest projects/04-llm-adapter/tests/compare_runner_parallel/test_budgeting.py::test_runner_execution_records_shadow_budget_and_schema`。

## 4. Attempt Executor の再試行結果集約改善
- 対象: `SequentialAttemptExecutor.run` および `ParallelAttemptExecutor.run` の失敗記録とキャンセル結果生成。【F:projects/04-llm-adapter/adapter/core/runner_execution_attempts.py†L28-L72】【F:projects/04-llm-adapter/adapter/core/runner_execution_parallel.py†L57-L112】
- 内容: 逐次・並列双方で利用できる `AttemptFailureRecorder`（仮称）を導入し、`ProviderFailureSummary` と `AllFailedError` 付随情報の組み立てを一元化する。並列 ANY/ALL モード固有のキャンセル結果も同レイヤで注入する。
- 期待効果: 再試行上限やキャンセル分岐の仕様差を明示し、`test_rate_limit_retry_*` と `test_parallel_any_*` のメトリクス検証コードから重複した失敗集約ロジックを排除できる。【F:projects/04-llm-adapter/tests/runner_retry/test_rate_limit_failover.py†L79-L154】【F:projects/04-llm-adapter/tests/compare_runner_parallel/failures/test_parallel_any_runner.py†L27-L174】
- 検証: `pytest projects/04-llm-adapter/tests/runner_retry/test_rate_limit_failover.py` と `pytest projects/04-llm-adapter/tests/compare_runner_parallel/failures/test_parallel_any_runner.py`。
