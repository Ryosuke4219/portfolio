# 概要（Overview）

## 目的
QA × SDET × LLM を軸に、**仕様 → テスト → CI → レポート**までの最小パイプラインを公開し、
「工数削減」「フレーク検知」「品質の再現性」を実務レベルで示す。

## スコープ
- #1 仕様テキスト → 構造化テスト（決定的生成 / Deterministic）
- #2 受け入れ基準（AC）→ E2E 雛形（HITL 支援 / 人手レビュー前提）
- #3 CI ログ解析 → フレーク検知・再実行
- #4 LLM Adapter（直列/並列・影実行）→ 異常系注入とフォールバック設計

## 非スコープ（現時点）
- 本番 Web アプリの実装・大規模 UI。  
- 組織固有の Jira/Slack 連携などの私有ワークフロー。

## 成果物（想定）
- デモ用の spec.md / cases.json / generated.spec.ts / JUnit XML
- Coverage HTML、Flaky 集計表、LLM metrics（JSONL）
- アーキ図・データ契約（本書）

## 対象読者
- **QA リード / SDET**：仕様レビューとテスト資産の整備・自動化を主導する役割。
- **LLM / 自動化エンジニア**：プロンプト設計や Adapter 実装で並走運用を構築する役割。
- **プロダクトマネージャー**：品質保証フローの透明性と成果指標を把握する役割。

## 進行フェーズの全体感
| フェーズ | 主担当 | 主なアウトプット | 完了条件 |
| --- | --- | --- | --- |
| Plan | QA / PM | `spec.md`, `ac.md` の整備、Lint パス | 仕様レビューが完了し、必須項目が埋まっている |
| Build | SDET / Automation | cases.json, generated.spec.ts, JUnit | CLI で決定的に再現できる状態 |
| Measure | QA / DevOps | flaky-summary.json, metrics JSONL | CI 履歴からの解析が自動で行える |
| Learn | QA / PM | 週次レポート、改善タスク | KPI をレビューし、再計画に反映 |

## 成果物マップ
```
spec.md ─┐
         ├─▶ Spec Parser (#1) ─▶ cases.generated.json ─▶ CI 実行 ─▶ junit.xml
ac.md  ──┘                               │                         │
                                          ▼                         ▼
                                   デルタレビュー              CI Analyzer (#3)
                                          │                         │
                                          └────▶ flaky-summary.json │
                                                                │   ▼
                                                                └▶ Pages 公開

LLM Adapter (#4) ─▶ runs-metrics.jsonl ─▶ Pages 可視化 ─▶ KPI レビュー
```

## 次の一歩
1. 各仕様書をテンプレに沿ってリポジトリへ追加し、Lint をパスさせる。
2. Spec Parser / E2E Scaffolder の PoC を作成し、cases.json と generated.spec.ts を得る。
3. GitHub Actions に JUnit 解析と Pages 生成ステップを組み込み、成果物を常設公開する。
4. LLM Adapter の影実行ログを収集し、コスト・品質指標を週次でレビューする。
