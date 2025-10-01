# 04 / ROADMAP — LLM Adapter (Shadow Execution)

> Source of truth: `04/llm-adapter-srs.md`  |  Start: **2025-10-01 JST**  |  Target: **v0.1.0 / 2025-11-09**
> 各マイルストンは1〜1.5週想定。SRS要求を「機能ブロック→成果物→Exit Criteria」で分解し、DoDにCI緑・再現手順・Evidence更新を含める。

## ✔ Milestone Overview
| Milestone | Week (JST) | 目的 | 主な成果物 | 進捗 |
| --- | --- | --- | --- | --- |
| **M0 — SRS確定 & 骨子固定** | Week40: 2025-09-29〜10-05 | SRS最終化 | `04/llm-adapter-srs.md`最終版 / 参照アーキ図 / M1〜M6 Exit Criteria | ✅ 完了（2025-10-04 SRS v1.0確定・用語集統合完了） |
| **M1 — Core SPI & Runner** | Week40-41: 〜10-12 | SPI/Runner骨格 | ProviderSPI/Request/Response安定化 / 直列Runner / 最小UT | ✅ 完了（SPI型定義確定・直列Runner/例外UTマージ済） |
| **M2 — Shadow & Metrics** | Week41: 10-06〜10-12 | 影実行+計測 | `run_with_shadow` / `artifacts/runs-metrics.jsonl`スキーマ / 異常系テスト | ✅ 完了（影実行APIとJSONLスキーマv1安定化） |
| **M3 — Providers** | Week42: 10-13〜10-19 | 実プロバイダ実装 | OpenAI互換/Ollama/OpenRouter / ストリーミング透過 / 契約テスト | 🟡 進行中（Gemini/Ollama完了、OpenRouter統合待ち） |
| **M4 — Parallel & Consensus** | Week43: 10-20〜10-26 | 並列実行＋合議 | `runner_parallel` / `ConsensusConfig` / 合議テスト | 🟡 進行中（並列Runner/Consensus骨格完成、評価シナリオ整備中） |
| **M5 — Telemetry & QA Integration** | Week44: 10-27〜11-02 | 可視化＋QA連携 | OTLP/JSON変換 / `docs/weekly-summary.md`自動更新 / Evidence更新 | ⚪ 未着手（CI連携と自動更新スクリプト設計段階） |
| **M6 — CLI/Docs/Release 0.1.0** | Week45: 11-03〜11-09 | デモ〜配布 | `just`/CLI / README(JP/EN) / `pyproject.toml` / CHANGELOG / v0.1.0 | ⚪ 未着手（CLI整理とリリース手順これから） |

---

## M0 — SRS確定 & 骨子固定
**進捗**: ✅ SRS v1.0（2025-09-30）を公開し、用語集・JSONL互換方針を`04/llm-adapter-srs.md`へ反映済。
**成果物**: SRS最終版・参照アーキ図・Exit Criteria併記。 **Exit Criteria**: 用語(Shadow/フォールバック/JSONL/異常)を一意定義、M1〜M6受け入れ条件を明文化、`04/`にSRSと図版格納・リンク健全。 **タスク**: 用語集統合 / 例外→共通例外マップ表追加 / JSONLスキーマv1＋後方互換方針記述。

## M1 — Core SPI & Runner
**進捗**: ✅ ProviderSPI型・例外マッピング・`runner_sync_sequential`のUTを`projects/04-llm-adapter-shadow/`に統合済。
**成果物**: ProviderSPI/Request/Responseの安定化(`model`必須)・直列Runner・例外マッピングUT。 **Exit Criteria**: 1次失敗時に2次以降へ確実委譲、共通例外マップ整合、CI緑＋README最小例(`just test`)。 **タスク**: `ProviderRequest.model`必須化 / 例外→Timeout・RateLimit・Retriable・ProviderSkip整合 / 直列Runner成功・失敗・フェイルオーバーテスト。

## M2 — Shadow Execution & Metrics
**進捗**: ✅ `shadow.py`/`shadow_metrics.py`とJSONLスキーマ検証を整備し、影実行OFF/ON同一性テストを完了。
**成果物**: `run_with_shadow`、`artifacts/runs-metrics.jsonl`(timestamp/provider/latency_ms/token_usage/diff_kind等)、TIMEOUT/429/フォーマット不正テスト。 **Exit Criteria**: 影実行ON/OFFでプライマリ応答不変、JSONLスキーマ検証通過、破壊変更時にスキーマバージョン更新。 **タスク**: 影並走のキャンセル/タイムアウト安全化 / JSONL追記リトライ / スキーマ検証とE2Eデモ。

## M3 — Provider 実装
**進捗**: 🟡 Gemini/Ollama実装と契約テストを完了。OpenRouter/汎用OpenAI互換レイヤは結合テスト前で待機。
**成果物**: `providers/`配下にOpenAI互換・Ollama・OpenRouter、ストリーミング透過、レート制限/再試行/タイムアウト統一、契約テスト。 **Exit Criteria**: 同一SPIで3種動作、ストリーミング指定を下層へ伝播(アサート)、429/5xx/ネットワークを共通例外へ正規化。 **タスク**: OpenAI互換(チャット/補完) / Ollama pull&stream透過 / OpenRouterルーティング差異吸収。

## M4 — Parallel & Consensus
**進捗**: 🟡 `runner_parallel`/`runner_sync_consensus`を追加済。性能ベンチと差分メトリクス記録の自動化が残課題。
**成果物**: `runner_parallel`・`compute_consensus`・`ConsensusConfig`(多数決/スコア重み/低遅延TB/コスト上限)・合議テスト。 **Exit Criteria**: N並列勝者決定が決定的(seed固定)、多数決/スコア/低遅延TBを設定切替、影実行併用で差分メトリクスJSONL記録。 **タスク**: 合議アルゴリズム(majority/score/tie-break) / 勝者決定後の残ジョブ中断 / コスト&遅延制約設定。

## M5 — Telemetry & QA Integration
**進捗**: ⚪ OTLP/CI連携は未着手。`docs/weekly-summary.md`試作版の手動更新のみ。
**成果物**: メトリクス→OTLP/JSON変換、`tools/`による`docs/weekly-summary.md`自動生成、Evidence更新。 **Exit Criteria**: ローカル/CIでメトリクスがダッシュボード(または静的HTML)へ反映、Evidence/Weekly Summaryリンク整合、CI緑＋`just report`でレポート生成。 **タスク**: OTLP/JSON変換器 / `weekly-summary`スクリプト(失敗率・遅延分布・差分) / Evidence更新(スクショ・リンク検査)。

## M6 — CLI/Docs/Release 0.1.0
**進捗**: ⚪ `cli.py`骨格は存在するが、コマンド束ねとリリース手順は未着手。v0.1.0向けCHANGELOG草案なし。
**成果物**: `just`/CLI(`setup|test|demo|report|bench`)、README(JP/EN)・サンプル・トラブルシュート、セマンティックバージョン・CHANGELOG・`pyproject.toml`。 **Exit Criteria**: `pip install -e . && just demo`で影実行→JSONL→週次サマリを一気通貫、v0.1.0タグと公開API安定宣言、CI緑＋リリースノートにKnown Issues/Next Steps。 **タスク**: CLI Help/例/Exit Code設計 / JP-EN README同期(生成タスク) / ReleaseノートとCHANGELOG生成。

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
src/llm_adapter/
  provider_spi.py
  runner.py
  runner_parallel.py
  providers/
  shadow.py
artifacts/runs-metrics.jsonl
docs/weekly-summary.md
```

## 進行管理 (共通DoD)
CI緑(ruff/mypy/pytest/node:test) / Repro手順(`just`コマンド)をREADME反映 / Evidence更新 / リリースノート&CHANGELOG更新。

### 備考
M1とM2は依存が薄く並走可。仕様変更はSRS先行で実装を追随。スキーマ破壊時はメジャーバンプ、軽微拡張はマイナー/パッチ。
