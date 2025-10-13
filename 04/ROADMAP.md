# 04 / ROADMAP — LLM Adapter (Shadow Execution)

> Source of truth: `04/llm-adapter-srs.md`  |  Start: **2025-10-01 JST**  |  Target: **v0.1.0 / 2025-11-09**
> 各マイルストンは1〜1.5週想定。SRS要求を「機能ブロック→成果物→Exit Criteria」で分解し、DoDにCI緑・再現手順・Evidence更新を含める。

## ✔ Milestone Overview
| Milestone | Week (JST) | 目的 | 主な成果物 | 進捗 |
| --- | --- | --- | --- | --- |
| **M0 — SRS確定 & 骨子固定** | Week40: 2025-09-29〜10-05 | SRS最終化 | `04/llm-adapter-srs.md`最終版 / 参照アーキ図 / M1〜M6 Exit Criteria | ✅ 完了（2025-10-04 SRS v1.0確定・用語集統合完了） |
| **M1 — Core SPI & Runner** | Week40-41: 〜10-12 | SPI/Runner骨格 | ProviderSPI/Request/Response安定化 / `SequentialAttemptExecutor` / 最小UT | ✅ 完了（`projects/04-llm-adapter/adapter/core/runner_execution_attempts.py`でSPI型と直列Executorテストを確定） |
| **M2 — Shadow & Metrics** | Week41: 10-06〜10-12 | 影実行+計測 | `ShadowRunner`経由の影計測 / `artifacts/runs-metrics.jsonl`スキーマ / 異常系テスト | ✅ 完了（比較実行APIとJSONLスキーマv1を`projects/04-llm-adapter`へ反映） |
| **M3 — Providers** | Week42: 10-13〜10-19 | 実プロバイダ実装 | Simulated/OpenAI/Gemini登録 / ストリーミング透過 / 契約テスト（OpenRouter 429/5xx 週次集計とストリーミングプローブ運用を完了） | ✅ 完了（OpenRouter 429/5xx 週次集計パイプラインとストリーミングプローブを導入し、Evidence を docs/spec/v0.2/TASKS.md に統合済[^provider-registry]） |
| **M4 — Parallel & Consensus** | Week43: 10-20〜10-26 | 並列実行＋合議 | `runner_execution_parallel.py` / `AggregationController` / 合議テスト | ✅ 完了（`runner_execution_parallel.py`と`aggregation_controller.py`で多数決・タイブレーク・差分記録を実装しイベント検証も通過） |
| **M5 — Telemetry & QA Integration** | Week44: 10-27〜11-02 | 可視化＋QA連携 | OTLP/JSON変換 / `projects/04-llm-adapter/tools/report/metrics/weekly_summary.py` / Evidence更新 | ✅ 完了（OTLP JSONエクスポータを`projects/04-llm-adapter-shadow/src/llm_adapter/metrics_otlp.py`に集約し、週次サマリ生成ツールを`projects/04-llm-adapter`の`just report`へ統合） |
| **M6 — CLI/Docs/Release 0.1.0** | Week45: 11-03〜11-09 | デモ〜配布 | `just`/CLI / README(JP/EN) / `pyproject.toml` / CHANGELOG / v0.1.0 | ✅ 完了（`docs/releases/v0.1.0.md` を整備し、OpenRouter 運用ガイドとタグ発行手順を最新化済） |

---

## M0 — SRS確定 & 骨子固定
**進捗**: ✅ SRS v1.0（2025-09-30）を公開し、用語集・JSONL互換方針を`04/llm-adapter-srs.md`へ反映済。
**成果物**: SRS最終版・参照アーキ図・Exit Criteria併記。 **Exit Criteria**: 用語(Shadow/フォールバック/JSONL/異常)を一意定義、M1〜M6受け入れ条件を明文化、`04/`にSRSと図版格納・リンク健全。 **タスク**: 用語集統合 / 例外→共通例外マップ表追加 / JSONLスキーマv1＋後方互換方針記述。

## M1 — Core SPI & Runner
**進捗**: ✅ ProviderSPI型・例外マッピング・`SequentialAttemptExecutor`のUTを`projects/04-llm-adapter/adapter/core/runner_execution_attempts.py`で整備済。
**成果物**: ProviderSPI/Request/Responseの安定化(`model`必須)・直列Executor・例外マッピングUT。 **Exit Criteria**: 1次失敗時に2次以降へ確実委譲、共通例外マップ整合、CI緑＋README最小例(`just test`)。 **タスク**: `ProviderRequest.model`必須化 / 例外→Timeout・RateLimit・Retriable・ProviderSkip整合 / 直列Executor成功・失敗・フェイルオーバーテスト。

## M2 — Shadow Execution & Metrics
**進捗**: ✅ `projects/04-llm-adapter/adapter/core/execution/shadow_runner.py`と`_shadow_helpers.py`で比較実行とJSONL検証を整備し、影実行ON/OFF同一性テストを完了。
**成果物**: `ShadowRunner`経由の影計測、`artifacts/runs-metrics.jsonl`(ts/run_id/provider/model/status/failure_kind/ci_meta.aggregate_latency_ms/eval.diff_rate等)、TIMEOUT/429/フォーマット不正テスト。 **Exit Criteria**: 影実行ON/OFFでプライマリ応答不変、`RunMetrics.status`/`failure_kind`/`ci_meta.aggregate_*`/`eval.diff_rate` を用いたJSONLスキーマ検証通過、破壊変更時にスキーマバージョン更新。 **タスク**: 比較並走のキャンセル/タイムアウト安全化 / JSONL追記リトライ / スキーマ検証とE2Eデモ。
Shadow 版(`projects/04-llm-adapter-shadow/`)の`diff_kind`や`diff_reason`といった比較専用フィールドは廃止し、`RunMetrics`の実フィールドでプライマリ/影双方の状態を追跡するように統合した。
メトリクスは`adapter/core/runner_api.py`の`default_metrics_path()`が指す`projects/04-llm-adapter/data/runs-metrics.jsonl`へ書き出し、CIや運用集計ではこれを`artifacts/runs-metrics.jsonl`へ同期して`just weekly-summary`で週次集計・Evidence更新を行う。

## M3 — Provider 実装
**進捗**: ✅ OpenRouter 429/5xx 週次集計のバッチとダッシュボード反映を完了し、CLI 〜 Provider 経路のストリーミングプローブも本番導入。`test_cli_openrouter_accepts_provider_option_api_key` など既存回帰も緑を維持。[^provider-registry]
**成果物**: `projects/04-llm-adapter/adapter/core/providers/`にSimulated・OpenAI互換・Gemini・Ollama・OpenRouter、共通ストリーミング透過、レート制限/再試行/タイムアウト統一、契約テスト(現状4種)、OpenRouter 401/429/5xx/ネットワーク例外の正規化完了に加え、OpenRouter 429/5xx 週次集計レポートと CLI/API 透過・ストリーミング監視まで本番導入済。

**完了成果物**:

1. OpenRouter 429/5xx 週次集計 CLI — [`projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py`](../projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py) の集計検証で本番データ反映経路を担保。
2. CLI からの API キー透過 — [`projects/04-llm-adapter/tests/test_cli_single_prompt.py`](../projects/04-llm-adapter/tests/test_cli_single_prompt.py) により `ProviderRequest.options["api_key"]` までのエンドツーエンド経路を回帰確認。
3. ストリーミングプローブ運用 — [`projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py`](../projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py) のリアルタイム検証で監視体制を証跡化。
**完了した成果物のエビデンス**:
- 429/5xx 集計 CLI は [`projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py`](../projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py) で週次集計フローを検証済。
- CLI API キー透過は [`projects/04-llm-adapter/tests/test_cli_single_prompt.py`](../projects/04-llm-adapter/tests/test_cli_single_prompt.py) により `ProviderRequest.options["api_key"]` までの経路を回帰確認。
- ストリーミングプローブ検証は [`projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py`](../projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py) でリアルタイム監視フローを証跡化。
**タスク**: 完了。

[^provider-registry]: `ProviderFactory` が公開するプロバイダは `simulated`・`openai`・`gemini`・`ollama`・`openrouter`。詳細は `projects/04-llm-adapter/adapter/core/providers/__init__.py` を参照。

## M4 — Parallel & Consensus
**進捗**: ✅ `projects/04-llm-adapter/adapter/core/runner_execution_parallel.py`と`aggregation_controller.py`がparallel_all/consensusで全候補を集約し、多数決＋タイブレーク＋judgeまで備えた合議決定と`consensus_vote`イベント記録を実装。比較勝者への差分反映テストもCIで緑。
**成果物**: `runner_execution_parallel.py`・`AggregationController`・`ConsensusConfig`(多数決/スコア重み/低遅延TB/コスト上限)・合議テスト。 **Exit Criteria**: N並列勝者決定が決定的(seed固定)、多数決/スコア/低遅延TBを設定切替、影実行併用で差分メトリクスJSONL記録。 **タスク**: 完了（合議アルゴリズム／制約評価／残ジョブ中断を網羅）。

## M5 — Telemetry & QA Integration
**進捗**: ✅ `projects/04-llm-adapter-shadow/src/llm_adapter/metrics_otlp.py`で`provider_call`/`run_metric`イベントをOTLP JSONへ変換し、`projects/04-llm-adapter/tools/report/metrics/weekly_summary.py`が`runs-metrics.jsonl`から週次サマリを生成。Shadow 側に OTLP 変換ロジックが残存しており、`just weekly-summary`と`just report`が依存する CLI (`projects/04-llm-adapter-shadow/src/llm_adapter/cli`) 経由でメトリクス集計パイプラインを維持。
**成果物**: メトリクス→OTLP/JSON変換、`tools/report/metrics/weekly_summary.py`による`docs/weekly-summary.md`自動生成、Evidence更新。 **Exit Criteria**: ローカル/CIでメトリクスがダッシュボード(または静的HTML)へ反映、Evidence/Weekly Summaryリンク整合、CI緑＋`just report`と`just weekly-summary`でレポート生成。 **タスク**: 完了（OTLPエクスポータと週次サマリ自動化を導入済）。

## M6 — CLI/Docs/Release 0.1.0
**進捗**: ✅ `projects/04-llm-adapter`の`pyproject.toml`と`llm_adapter.__init__`を`0.1.0`へ引き上げ、`CHANGELOG.md`にv0.1.0リリースノートを反映。README/justコマンドのCLI導線を整理し、日本語/英語ドキュメントの差分同期と OpenRouter 運用ガイド（`just openrouter-stats -- --since ...` / `llm-adapter-openrouter-probe`）の整備まで完了。
**成果物**: `just`/CLI(`setup|test|demo|report|bench`)、README(JP/EN)・サンプル・トラブルシュート、セマンティックバージョン・CHANGELOG・`pyproject.toml`・`docs/releases/v0.1.0.md` チェックリスト。 **Exit Criteria**: `pip install -e . && just demo`で比較実行→JSONL→週次サマリを一気通貫、v0.1.0タグと公開API安定宣言、CI緑＋リリースノートにKnown Issues/Next Steps。 **タスク**: 完了（タグ発行手順と Evidence 更新を `docs/releases/v0.1.0.md` / `docs/spec/v0.2/TASKS.md` に反映済）。

### 移行メモ（Shadow 由来項目）
- 影実行・差分計測のコードは `projects/04-llm-adapter/adapter/core/execution/shadow_runner.py` と `_shadow_helpers.py` へ移設済で、旧 `04-llm-adapter-shadow` はアーカイブ予定。
- CLI から `ProviderRequest` を構築する経路は v0.2 タスク（[docs/spec/v0.2/TASKS.md#タスク8](../docs/spec/v0.2/TASKS.md#タスク8-cli-から-providerrequest-への移行を完了する) / [タスク9](../docs/spec/v0.2/TASKS.md#タスク9-cli-入力パイプラインに-ollamaopenrouter-の設定項目を追加する)）で追従。

## Stretch (Week46-47 任意)
コスト計測&予算内選択(token単価×速度×品質)、プロバイダ健全性ヘルスチェック(プローブ/自動フェイルアウト)、影差分可視化UIと回帰検知。

## 受け入れ基準 (SRS由来)
**機能**: 影実行ONでもプライマリ応答不変 / 直列フォールバックと並列合議が設定で選択可能 / 異常系(Timeout/RateLimit/フォーマット不正)をモックで再現・テスト可能。 **非機能**: 影実行ON時P95レイテンシ上乗せ≤15% / JSONLスキーマ後方互換維持(破壊時メジャーバンプ) / CI緑＋週次サマリへ影響度反映。

## リポジトリ運用
Milestones: `M0-SRS`, `M1-CoreRunner`, `M2-ShadowMetrics`, `M3-Providers`, `M4-Consensus`, `M5-Telemetry`, `M6-Release`。 Labels: `type:feat`, `type:test`, `type:refactor`, `type:docs`, `prio:high`, `area:runner`, `area:providers`, `area:metrics`。 Issue Seeds: Runner直列フォールバック例外伝播 / `ProviderRequest.model`必須化影響 / JSONLスキーマv1確定 / 異常系マーカー統一 / Ollamaストリーミング透過検証 / 429バックオフポリシー / 多数決・スコア・低遅延タイブレーク切替テスト / OTLP変換＋最小ダッシュボード / 週次サマリ自動生成。

## ディレクトリ指針
```
04/
  llm-adapter-srs.md
  ROADMAP.md
  diagrams/
projects/04-llm-adapter/
  adapter/
    core/
      provider_spi.py
      runner_execution.py
      runner_execution_parallel.py
      execution/
        shadow_runner.py
      providers/
        __init__.py
        openai.py ...
  data/
    runs-metrics.jsonl               # runner_api.default_metrics_path() の既定出力
  tools/
    report/
      metrics/
        weekly_summary.py
docs/weekly-summary.md                # just weekly-summary で再生成
artifacts/runs-metrics.jsonl          # CI 取り込み用のステージング[^metrics-layout]
```

[^metrics-layout]: `projects/04-llm-adapter/data/runs-metrics.jsonl` はコードベース内の既定シンク。CI やローカル集計では `artifacts/runs-metrics.jsonl` にメトリクスを収集した後、`just weekly-summary` / `just report` で週次サマリと Evidence を更新する。

## 進行管理 (共通DoD)
CI緑(ruff/mypy/pytest/node:test) / Repro手順(`just`コマンド)をREADME反映 / Evidence更新 / リリースノート&CHANGELOG更新。

### 備考
M1とM2は依存が薄く並走可。仕様変更はSRS先行で実装を追随。スキーマ破壊時はメジャーバンプ、軽微拡張はマイナー/パッチ。
