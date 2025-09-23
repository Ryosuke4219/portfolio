---
layout: default
title: Portfolio Gallery
description: QA × SDET × LLM の成果物と週次サマリをまとめた常設ギャラリー
---

# Portfolio Gallery

成果物の常設ギャラリーです。週次サマリと各プロジェクトのハイライト、関連アーティファクトへのリンクをまとめています。

## Weekly Summary

{% include weekly-summary-card.md %}

[全ての週次サマリを見る →]({{ '/weekly-summary.html' | relative_url }})

## Projects Showcase

### 01. Spec to Cases
- 仕様書からテストケースを自動生成するパイプラインの最小構成。
- 成果物: [cases.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases/cases.sample.json)
- 追加資料: [spec.sample.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases/spec.sample.md)

### 02. LLM to Playwright
- LLMで受け入れ基準を拡張し、Playwrightテストを自動生成するPoC。
- 成果物: [tests/generated/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/02-llm-to-playwright/tests/generated)
- 参考資料: [tests/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/tests/README.md)

### 03. CI Flaky Analyzer
- CIログからflakyテストを検知し再実行・自動起票までを一気通貫にする仕組み。
- 生成手順と最新スクショ: [docs/examples/ci-flaky/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/ci-flaky/README.md)
- CLI: [`projects/03-ci-flaky/scripts/flaky.mjs`](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/scripts/flaky.mjs)

### 04. LLM Adapter — Shadow Execution
- プライマリと影（shadow）実行を並走させ、差分メトリクスを収集するLLMアダプタの最小実装。
- 生成手順と最新スクショ: [docs/examples/llm-adapter/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/llm-adapter/README.md)
- 詳細資料: [README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/README.md)

## Evidence Library
- [QA Evidence Catalog](./evidence/README.md) — RTMや欠陥レポートと連携する検証一次情報の索引。
- [テスト計画書](./test-plan.md)
- [欠陥レポートサンプル](./defect-report-sample.md)

## 運用メモ
- `weekly-qa-summary.yml` ワークフローが `docs/weekly-summary.md` を自動更新（入力データは `docs/examples/ci-flaky/README.md` 記載の手順で生成）。
- `tools/generate_gallery_snippets.py` が週次サマリからハイライトカードを生成。
- `pages.yaml` ワークフローが `docs/` 配下を GitHub Pages に公開。
