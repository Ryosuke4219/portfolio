---
layout: default
title: CI Flaky Analyzer
description: CI ログから Flaky テストを検知・可視化する CLI のハイライト
---

> [English version]({{ '/en/evidence/flaky.html' | relative_url }})

# CI Flaky Analyzer

JUnit 形式のテスト結果を継続取り込みし、Flaky テストをスコアリングして可視化する CLI ツールです。CI パイプラインでの自動実行を想定した npm スクリプトと、週次レポート連携までを一気通貫で提供します。

## Highlights

- `flaky parse` / `flaky analyze` / `flaky issue` など、ログ収集からレポーティングまでを CLI サブコマンドで分離。
- ストリーミング解析で大型 JUnit XML も取り扱い可能。解析結果は JSONL と HTML で保存。
- `weekly` コマンドで `docs/weekly-summary.md` を更新し、ナレッジ化を自動化。

## Key Artifacts

- [README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/README.md) — CLI のセットアップとコマンド一覧。
- [config/flaky.yml](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/config/flaky.yml) — スコアリングやウィンドウ設定。
- [demo/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/03-ci-flaky/demo) — サンプル JUnit ログと HTML レポートの入力データ。
- [out/index.html](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/out/index.html) — 解析結果の可視化レポート。

## How to Reproduce

1. `projects/03-ci-flaky/` で `npm install` を実行。
2. デモログを取り込む場合は `npm run demo:parse` → `npm run demo:analyze` を実行し、`out/` 配下を確認。
3. 実運用では CI から JUnit XML を投入し、`npm run ci:analyze` や `npm run ci:issue` をワークフローに組み込む。

## Next Steps

- Slack Webhook や GitHub Issue API と連携し、`flaky issue` の Dry-run を本番起票へ拡張。
- 解析結果の CSV (`out/summary.csv`) を BI ツールへ連携し、長期トレンドを可視化。
- 週次更新の詳細は [週次サマリ一覧]({{ '/weekly-summary.html' | relative_url }}) を参照。
