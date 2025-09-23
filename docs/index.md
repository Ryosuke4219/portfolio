---
layout: default
title: Portfolio Hub
description: QA / SDET / LLM 成果物のハイライトと週次サマリを俯瞰できるポータル
---

# Demos

<div class="demo-grid">
  <article class="demo-card">
    <header>
      <p class="demo-card__id">01</p>
      <h2><a href="{{ '/evidence/spec2cases.html' | relative_url }}">Spec to Cases</a></h2>
    </header>
    <p>仕様書 Markdown からテストケース JSON を抽出する LLM + ルールベース変換パイプライン。</p>
    <ul>
      <li>スキーマ検証と type-preserving な変換ロジック。</li>
      <li>スモールスタート向けに CLI / JSON サンプルを同梱。</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/evidence/spec2cases.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>

  <article class="demo-card">
    <header>
      <p class="demo-card__id">02</p>
      <h2><a href="{{ '/evidence/llm2pw.html' | relative_url }}">LLM to Playwright</a></h2>
    </header>
    <p>LLM が受け入れ基準を補完しながら Playwright テストを自動生成する PoC。</p>
    <ul>
      <li>data-testid ベースの堅牢なセレクタ戦略と a11y スキャンを統合。</li>
      <li>JSON / CSV ドライバでデータ駆動テストを最小構成に。</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/evidence/llm2pw.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>

  <article class="demo-card">
    <header>
      <p class="demo-card__id">03</p>
      <h2><a href="{{ '/evidence/flaky.html' | relative_url }}">CI Flaky Analyzer</a></h2>
    </header>
    <p>CI ログから Flaky テストを検出し、HTML レポート / 起票テンプレまで自動生成する CLI。</p>
    <ul>
      <li>JUnit XML のストリーミング解析とスコアリングを npm ワークフロー化。</li>
      <li>HTML レポート / JSONL 履歴 / GitHub Issue テンプレをワンコマンドで生成。</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/evidence/flaky.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>

  <article class="demo-card">
    <header>
      <p class="demo-card__id">04</p>
      <h2><a href="{{ '/evidence/llm-adapter.html' | relative_url }}">LLM Adapter — Shadow Execution</a></h2>
    </header>
    <p>プライマリ応答を保持したまま影プロバイダを並走させ、異常系も再現できる LLM アダプタ。</p>
    <ul>
      <li>shadow diff メトリクスを JSONL 収集し、ベンダ比較に活用。</li>
      <li>タイムアウト / レート制限 / 形式不正をモックで再現しフォールバック検証。</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/evidence/llm-adapter.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>
</div>

## Weekly Summary

{% include weekly-summary-card.md %}

### 01. Spec to Cases
- 仕様書からテストケースを自動生成するパイプラインの最小構成。
- 成果物: [cases.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/spec2cases/cases.sample.json)
- 追加資料: [spec.sample.md](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/spec2cases/spec.sample.md)

### 02. LLM to Playwright
- LLMで受け入れ基準を拡張し、Playwrightテストを自動生成するPoC。
- 成果物: [tests/generated/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/02-llm-to-playwright/tests/generated)
- サンプル: [blueprint.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/llm2pw/blueprint.sample.json) / [demo/](https://github.com/Ryosuke4219/portfolio/tree/main/docs/examples/llm2pw/demo)
- 参考資料: [tests/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/tests/README.md)

### 03. CI Flaky Analyzer
- CIログからflakyテストを検知し再実行・自動起票までを一気通貫にする仕組み。
- 成果物: `npx flaky analyze` 実行時に `projects/03-ci-flaky/out/index.html`（HTML/CSV/JSON）が生成され、CI ではアーティファクトとして取得。
- 解析サンプル: 任意の JUnit XML を `npx flaky parse --input <path-to-xml>` で取り込み、履歴ストアに蓄積。

### 04. LLM Adapter — Shadow Execution
- 影プロバイダを並走させ、応答差分をメトリクス化（JSONL収集）して可視化。
- 異常系（タイムアウト、レート制限、フォーマット不正）をモックで再現し、フォールバック設計を検証。
- 参考資料: [evidence/llm-adapter](https://ryosuke4219.github.io/portfolio/evidence/llm-adapter.html)

[週次サマリの一覧を見る &rarr;]({{ '/weekly-summary.html' | relative_url }})

## Evidence Library

- [QA Evidence Catalog](./evidence/README.md)
- [テスト計画書](./test-plan.md)
- [欠陥レポートサンプル](./defect-report-sample.md)

## 運用メモ

- `weekly-qa-summary.yml` ワークフローが `docs/weekly-summary.md` を自動更新。
- `tools/generate_gallery_snippets.py` が週次サマリからハイライトカードを生成。
- `.github/workflows/pages.yml` が `docs/` 配下を GitHub Pages にデプロイ（別途 publish-docs ワークフローは廃止済み）。
