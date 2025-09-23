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

[週次サマリの一覧を見る &rarr;]({{ '/weekly-summary.html' | relative_url }})

## Evidence Library

- [QA Evidence Catalog](./evidence/README.md)
- [テスト計画書](./test-plan.md)
- [欠陥レポートサンプル](./defect-report-sample.md)

## 運用メモ

- `weekly-qa-summary.yml` ワークフローが `docs/weekly-summary.md` を自動更新。
- `tools/generate_gallery_snippets.py` が週次サマリからハイライトカードを生成。
- `pages.yaml` ワークフローが `docs/` 配下を GitHub Pages に公開。
