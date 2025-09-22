---

# QA × SDET × LLM ポートフォリオハブ

> **仕様 → テスト → CI → レポート** を最小構成でつなぎ、品質を「再現可能なプロダクト」として提示するためのサイトです。
> GitHub Pages で公開されるこのハブから、仕様書・生成テスト・CI 解析・LLM フォールバック設計までを一気通貫で辿れます。

このドキュメントは、ポートフォリオの価値を常設的に共有するためのハブです。GitHub Pages で公開し、週次サマリや HTML レポートへの導線を集約します。設計から運用までのストーリーを一貫して追えるよう、**概要 → 仕様 → 設計 → 運用** の順に整理しています。

---

## 目次（Table of Contents）

* [概要（Overview）](overview.md)
* 仕様

  * [#1 仕様 → 構造化テスト（決定的生成）](specs/01-spec2cases.md)
  * [#2 AC → E2E 雛形生成（HITL 支援）](specs/02-ac-to-e2e.md)
  * [#3 CI ログ解析 → フレーク検知](specs/03-ci-flaky.md)
  * [#4 LLM Adapter（影実行・フォールバック）](specs/04-llm-adapter-shadow.md)
* 設計

  * [全体アーキテクチャ](design/architecture.md)
  * [データ契約](design/data-contracts.md)
  * [CI/CD 設計](design/ci-cd.md)
  * [リスク・運用](design/risks-and-ops.md)
* 追加資料

  * [最新の週次サマリ](../reports/weekly-summary.md) ※必要に応じて更新してください。
  * [HTML レポート](../reports/index.html) ※生成された成果物をここに配置できます。
  * [リポジトリトップ](../README.md)

---

## ハイライト（Highlights）

* **仕様 → テスト → CI → レポート** の最小パイプラインを段階的に実装するためのドキュメントセット。
* 各仕様は**データ契約**と**AC**を明記し、ツール実装時のブレを抑制。
* **CI/CD と運用ガイド**で、Pages 公開やメトリクス分析までを一本化。

**機能ハイライト**

* **仕様からテストまでの自動変換** — Markdown 仕様を静的テストケースへ構造化し、差分レビューや再実行が容易に。
* **HITL を前提にした E2E 雛形生成** — 受け入れ基準から Playwright 互換のテストを素早く下書きし、TODO コメントで不確実性を可視化。
* **CI ログ解析によるフレーク検知** — JUnit 履歴から flaky なテストを抽出し、再実行ポリシーや失敗ログを自動整理。
* **LLM Adapter の影実行とフォールバック** — 本番影響なく並走させ、異常系を観測しながら Null-safe にクローズ。

---

## ビジュアルサマリ

| フェーズ  | 主要アーティファクト                                  | ゴール              | 関連ドキュメント                                                                        |
| ----- | ------------------------------------------- | ---------------- | ------------------------------------------------------------------------------- |
| 仕様策定  | `spec.md`, `ac.md`                          | 必須情報が揃ったユースケース定義 | [Overview](overview.md)                                                         |
| テスト生成 | `cases.generated.json`, `generated.spec.ts` | 再現可能なテスト資産       | [#1 Spec → Cases](specs/01-spec2cases.md), [#2 AC → E2E](specs/02-ac-to-e2e.md) |
| 実行/計測 | `junit.xml`, Coverage                       | 品質の定量化と flaky 把握 | [#3 CI ログ解析](specs/03-ci-flaky.md), [Data Contracts](design/data-contracts.md)  |
| 影実行   | `runs-metrics.jsonl`                        | LLM の信頼性を継続監視    | [#4 LLM Adapter](specs/04-llm-adapter-shadow.md)                                |
| 運用/改善 | レポート, KPI                                   | 継続的な改善サイクル       | [Architecture](design/architecture.md), [Risks & Ops](design/risks-and-ops.md)  |

---

## 3 分で追えるストーリー（ドキュメント活用方法）

1. **Overview で全体像を把握** — なぜ QA × SDET × LLM を束ねるのか、想定アウトプットとスコープを確認。
2. **Specs で要件を読む** — 各仕様ドキュメントが入力・出力・AC を明文化。実装の指針とガードレールを提示。
3. **Design セクションで実装と運用を想像** — アーキ図・データ契約・CI/CD 設計を参照し、どのように仕組み化するかを把握。
4. **運用フェーズ** — [リスク・運用](design/risks-and-ops.md) を参照し、KPI とインシデント対応フローを準備。

---

## アーティファクトギャラリー

* ✅ **仕様テンプレート**：`projects/01-spec2cases/spec.md` などのプレースホルダからテストを生成。
* ✅ **生成テストケース**：`cases.generated.json` は Git で差分レビューできる最小粒度。
* ✅ **JUnit + Coverage HTML**：CI から Pages へ公開可能な形式で自動収集。
* ✅ **Flaky レポート**：`flaky/index.html` を想定し、再現条件や信頼度スコアを可視化。
* ✅ **LLM Metrics JSONL**：影実行で得た `runs-metrics.jsonl` を Pages でデータ可視化。

アーティファクトはすべて **GitHub Actions のワークフロー**で生成し、同じパイプラインでレビュー・共有します。

---

## 体験の仕方（How to Explore）

1. リポジトリを Clone し、Node 24.x と Python をセットアップ。
2. `python -m http.server 8000 --directory docs` でドキュメントをローカルプレビュー。
3. `docs/specs/` や `docs/design/` のリンクから、仕様〜設計の詳細へ辿ってください。
4. GitHub Pages を有効化すると、このハブが [https://ryosuke4219.github.io/portfolio/](https://ryosuke4219.github.io/portfolio/) に常設されます。

---

## ドキュメントマップ（Deep Dive）

* [Overview](overview.md) — 目的・スコープ・成果物のサマリ。
* [Specs](specs/01-spec2cases.md) — 各ユースケースの要件と AC。
* [Design](design/architecture.md) — アーキテクチャ、データ契約、CI/CD、リスクと運用。
* [README](../README.md) — リポジトリ全体の背景と操作手順。

> **Tip:** GitHub Pages のナビゲーションにこのマップを残しておくと、外部閲覧者が迷わずに目的の資料へアクセスできます。

---

## 公開手順メモ

1. ドキュメントを更新したら `main` ブランチへマージします。
2. Publish Docs ワークフローが自動で実行され、GitHub Pages に最新の内容が公開されます。
3. 公開 URL は GitHub リポジトリの「About → Website」に設定しておくと便利です。

---

## 次のステップ（Next Actions）

* 📌 `specs/` をもとに PoC 実装を進め、生成テストの実サンプルを公開。
* 📌 JUnit ログを蓄積し、`flaky-summary.json` を用いた実データ解析を記事化。
* 📌 LLM Adapter にメトリクスダッシュボードを追加し、影実行の可視化を強化。

---

### Contact

* GitHub: [@Ryosuke4219](https://github.com/Ryosuke4219)
* LinkedIn / Speaker Deck 等のリンクは README のヒーロースニペットを参照してください。

このサイトは GitHub Pages（`docs/` ディレクトリ）から自動配信されています。更新 PR は CI・CodeQL・Docs の各ワークフローで検証され、`main` マージ後に公開されます。
