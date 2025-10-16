> 各マイルストンは1〜1.5週想定。SRS要求を「機能ブロック→成果物→Exit Criteria」で分解し、DoDにCI緑・再現手順・Evidence更新を含める。

## ✔ Milestone Overview
| Milestone | Week (JST) | 目的 | 主な成果物 | 進捗 |
| --- | --- | --- | --- | --- |
| **M0 — SRS確定 & 骨子固定** | Week40: 2025-09-29〜10-05 | SRS最終化 | `docs/04/llm-adapter-srs.md`最終版 / 参照アーキ図 / M1〜M6 Exit Criteria | ✅ 完了（2025-10-04 SRS v1.0確定・用語集統合完了） |
| **M1 — Core SPI & Runner** | Week40-41: 〜10-12 | SPI/Runner骨格 | ProviderSPI/Request/Response安定化 / `SequentialAttemptExecutor` / 最小UT | ✅ 完了（`projects/04-llm-adapter/tests/runner_retry/test_rate_limit_failover.py`でレート制限リトライとフォールバック遷移を検証済） |
| **M2 — Shadow & Metrics** | Week41: 10-06〜10-12 | 影実行+計測 | `ShadowRunner`経由の影計測 / `artifacts/runs-metrics.jsonl`スキーマ / 異常系テスト | ✅ 完了（比較実行APIとJSONLスキーマv1を`projects/04-llm-adapter`へ反映） |
| **M3 — Providers** | Week42: 10-13〜10-19 | 実プロバイダ実装 | Simulated/OpenAI/Gemini登録 / ストリーミング透過 / 契約テスト（OpenRouter 429/5xx 週次集計とストリーミングプローブ運用を完了） | ✅ 完了（OpenRouter 429/5xx 週次集計パイプラインとストリーミングプローブを導入し、Evidence を docs/spec/v0.2/TASKS.md に統合済[^provider-registry]） |
| **M4 — Parallel & Consensus** | Week43: 10-20〜10-26 | 並列実行＋合議 | `runner_execution_parallel.py` / `AggregationController` / 合議テスト | ✅ 完了（`runner_execution_parallel.py`と`aggregation_controller.py`で多数決・タイブレーク・差分記録を実装しイベント検証も通過） |
| **M5 — Telemetry & QA Integration** | Week44: 10-27〜11-02 | 可視化＋QA連携 | OTLP/JSON変換 / `projects/04-llm-adapter/tools/report/metrics/weekly_summary.py` / Evidence更新 | ✅ 完了（OTLP JSONエクスポータを`projects/04-llm-adapter-shadow/src/llm_adapter/{metrics_otlp.py,metrics.py,shadow_metrics.py}`で維持しつつ、週次サマリ生成ツールを`projects/04-llm-adapter/tools/report/metrics/{data.py,weekly_summary.py}`へ移行して`just report`から実行） |
| **M6 — CLI/Docs/Release 0.1.0** | Week45: 11-03〜11-09 | デモ〜配布 | `just`/CLI / README(JP/EN) / `pyproject.toml` / CHANGELOG / v0.1.0 | ✅ 完了（`docs/releases/v0.1.0.md` を整備し、OpenRouter 運用ガイドとタグ発行手順を最新化済。CLI は `prompt_runner` の RateLimiter テストや `prompts.py` 再構成で運用ガードを追加）[^m6-cli-flow] |

### 未完了タスク（v0.2 保守）
- v0.2 の未完了タスク一覧は空であり、旧ブリッジ削除待ちなどの保留事項は存在しない。差分が発生した場合は `docs/spec/v0.2/TASKS.md`（「未完了タスク一覧」節）を更新し、本ロードマップと相互に同期する。[^v02-maintenance]

---

## M0 — SRS確定 & 骨子固定
**進捗**: ✅ SRS v1.0（2025-09-30）を公開し、用語集・JSONL互換方針を`docs/04/llm-adapter-srs.md`へ反映済。
**成果物**: SRS最終版・参照アーキ図・Exit Criteria併記。
**Exit Criteria**: 用語(Shadow/フォールバック/JSONL/異常)を一意定義、M1〜M6受け入れ条件を明文化、`docs/04/`にSRSと図版格納・リンク健全。
**タスク**: 用語集統合 / 例外→共通例外マップ表追加 / JSONLスキーマv1＋後方互換方針記述。

## M1 — Core SPI & Runner
**進捗**: ✅ ProviderSPI型・例外マッピング・`SequentialAttemptExecutor`のUTを`projects/04-llm-adapter/tests/runner_retry/test_rate_limit_failover.py`（トークンバケット呼び出し回数とリトライ上限後の次プロバイダ移行を検証）で整備済。
**成果物**: ProviderSPI/Request/Responseの安定化(`model`必須)・直列Executor・例外マッピングUT。
**Exit Criteria**: 1次失敗時に2次以降へ確実委譲、共通例外マップ整合、CI緑＋README最小例(`just test`)。
**タスク**: `ProviderRequest.model`必須化 / 例外→Timeout・RateLimit・Retriable・ProviderSkip整合 / 直列Executor成功・失敗・フェイルオーバーテスト。

## M2 — Shadow Execution & Metrics
**進捗**: ✅ `projects/04-llm-adapter/adapter/core/execution/shadow_runner.py`と`_shadow_helpers.py`で比較実行とJSONL検証を整備し、実行ON/OFF同一性テストを完了。Shadow 側の Python パッケージは `llm_adapter` 名前空間へ移行し、`projects/04-llm-adapter-shadow/src/llm_adapter/__init__.py` のメタパスエイリアスと `projects/04-llm-adapter-shadow/tests/test_no_src_imports.py` のガードで旧 `src.llm_adapter` 参照を排除した。【F:projects/04-llm-adapter-shadow/src/llm_adapter/__init__.py†L1-L80】【F:projects/04-llm-adapter-shadow/tests/test_no_src_imports.py†L1-L46】
**成果物**: `ShadowRunner`経由の影計測、`artifacts/runs-metrics.jsonl`(ts/run_id/provider/model/status/failure_kind/shadow_provider_id/shadow_status/shadow_latency_ms/shadow_outcome/shadow_error_message/ci_meta.aggregate_mode・aggregate_strategy・aggregate_votes・consensus/eval.diff_rate等)、TIMEOUT/429/フォーマット不正テスト。
**Exit Criteria**: 影実行ON/OFFでプライマリ応答不変、`RunMetrics.status`/`failure_kind`/`ci_meta.aggregate_*`/`eval.diff_rate` を用いたJSONLスキーマ検証通過、破壊変更時にスキーマバージョン更新。
**タスク**: 比較並走のキャンセル/タイムアウト安全化 / JSONL追記リトライ / スキーマ検証とE2Eデモ。
Shadow 版(`projects/04-llm-adapter-shadow/`)は`diff_kind`などの比較指標を保持しつつ、`RunMetrics.shadow_*`フィールド（`shadow_outcome`/`shadow_error_message`含む）へマッピングしてプライマリ/影双方の状態を共通JSONLへ転記する。
メトリクスは`adapter/core/runner_api.py`の`default_metrics_path()`が指す`projects/04-llm-adapter/data/runs-metrics.jsonl`へ書き出し、CIや運用集計ではこれを`artifacts/runs-metrics.jsonl`へ同期して`just weekly-summary`で週次集計・Evidence更新を行う。
JSONLスキーマは`projects/04-llm-adapter/adapter/core/metrics/models.py`と`projects/04-llm-adapter/adapter/core/metrics/update.py`で維持され、Runner実行時に同モジュール経由で最新項目へ更新される。

## M3 — Provider 実装
**進捗**: ✅ OpenRouter 429/5xx 週次集計のバッチとダッシュボード反映を完了し、CLI 〜 Provider 経路のストリーミングプローブも本番導入。`test_cli_openrouter_accepts_provider_option_api_key` など既存回帰も緑を維持。[^provider-registry]
**成果物**: `projects/04-llm-adapter/adapter/core/providers/`にSimulated・OpenAI互換・Gemini・Ollama・OpenRouter、共通ストリーミング透過、レート制限/再試行/タイムアウト統一、契約テスト(現状4種)、OpenRouter 401/429/5xx/ネットワーク例外の正規化完了に加え、OpenRouter 429/5xx 週次集計レポートと CLI/API 透過・ストリーミング監視まで本番導入済。

**完了成果物**:

1. OpenRouter 429/5xx 週次集計 CLI — [`projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py`](../../projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py) の集計検証で本番データ反映経路を担保。
2. CLI からの API キー透過 — [`projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py::test_cli_literal_api_key_option`](../../projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py#L81-L115) により `ProviderRequest.options["api_key"]` までのエンドツーエンド経路を回帰確認。
3. ストリーミングプローブ運用 — [`projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py`](../../projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py) のリアルタイム検証で監視体制を証跡化。

**完了した成果物のエビデンス**:
- 429/5xx 集計 CLI は [`projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py`](../../projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py) で週次集計フローを検証済。
- CLI API キー透過は [`projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py::test_cli_literal_api_key_option`](../../projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py#L81-L115) により `ProviderRequest.options["api_key"]` までの経路を回帰確認。
- ストリーミングプローブ検証は [`projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py`](../../projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py) でリアルタイム監視フローを証跡化。

**タスク**:
- OpenRouter の 429/5xx エラー統計を週次で集計し、バックオフ/RPM 調整の指標に取り込む。
- CLI でリテラル指定された OpenRouter API キーが `ProviderRequest.options["api_key"]` まで透過する経路を整備し、ギャップを再現する回帰テストを追加する。
- OpenRouter 用の env/CLI マッピングと参照ドキュメントを更新し、`OPENROUTER_API_KEY` などのリテラル指定と必須項目の整合、および `options["api_key"]` 配線手順の明示を保証する。

[^provider-registry]: `ProviderFactory` が公開するプロバイダは `simulated`・`openai`・`gemini`・`ollama`・`openrouter`。詳細は`projects/04-llm-adapter/adapter/core/providers/__init__.py` を参照。

[^m6-cli-flow]: CLI は [`projects/04-llm-adapter/adapter/cli/prompt_runner.py`](../../projects/04-llm-adapter/adapter/cli/prompt_runner.py) の `_process_prompt` で `invoke = getattr(provider, "invoke")` を検証したのち `_build_request()` で `ProviderRequest` を生成し、同期実装の `invoke(request)` を実行する一連のフローを採用している。`ProviderRequest` 必須化は [`projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py::test_cli_errors_when_provider_lacks_invoke`](../../projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py#L11-L44)・[`projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py::test_cli_errors_when_provider_factory_returns_non_invoke_provider`](../../projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py#L46-L71)・[`tests/cli_single_prompt/test_provider_options.py::test_cli_fake_provider`](../../projects/04-llm-adapter/tests/cli_single_prompt/test_provider_options.py#L4-L27) が証跡となり、`test_cli_fake_provider` では `ProviderRequest` に `max_tokens` と `options` が構築されることを確認している。

[^v02-maintenance]: `docs/spec/v0.2/TASKS.md` の「未完了タスク一覧」は v0.2 時点で空である。

## M4 — Parallel & Consensus
**進捗**: ✅ `projects/04-llm-adapter/adapter/core/runner_execution_parallel.py`と`aggregation_controller.py`がparallel_all/consensusで全候補を集約し、多数決＋タイブレーク＋judgeまで備えた合議決定を実装。`AggregationController.apply` が`RunMetrics.ci_meta`へ`aggregate_mode`・`aggregate_votes`・`consensus`を追記し、比較勝者のメタデータ検証もCIで緑。
**成果物**: `runner_execution_parallel.py`・`AggregationController`・`ConsensusConfig`(多数決/スコア重み/低遅延TB/コスト上限)・合議メタデータテスト。
**Exit Criteria**: N並列勝者決定が決定的(seed固定)、多数決/スコア/低遅延TBを設定切替、影実行併用で`ci_meta.aggregate_*`と`consensus`を含むメトリクスJSONL記録。
**タスク**: 完了（合議アルゴリズム／制約評価／残ジョブ中断を網羅）。

## M5 — Telemetry & QA Integration
**進捗**: ✅ `projects/04-llm-adapter-shadow/src/llm_adapter/metrics_otlp.py`で`provider_call`/`run_metric`イベントをOTLP JSONへ変換し、Shadow 側では補助メトリクス処理（`metrics.py`/`shadow_metrics.py`）も維持。週次レポート生成は`projects/04-llm-adapter/tools/report/metrics/{data,weekly_summary}.py`を`just weekly-summary`/`just report`が直接呼び出す構成へ移行し、集計・Evidence更新はコア側ツールで完結。
**成果物**: メトリクス→OTLP/JSON変換、`tools/report/metrics/weekly_summary.py`による`docs/weekly-summary.md`自動生成、Evidence更新。
**Exit Criteria**: ローカル/CIでメトリクスがダッシュボード(または静的HTML)へ反映、Evidence/Weekly Summaryリンク整合、CI緑＋`just report`と`just weekly-summary`が`tools.report.metrics`モジュールを通じてレポート生成。
**タスク**: 完了（OTLPエクスポータと週次サマリ自動化を導入済）。
