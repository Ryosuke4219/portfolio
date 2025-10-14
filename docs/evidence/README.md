# QA Evidence Catalog

本カタログは RTM に記載された `EvidenceLink` の遷移先をまとめ、検証時に参照する一次情報を一覧化する。

## 01. Spec to Cases
- ケース設計テンプレ: `../examples/spec2cases/spec.sample.md`
- 自動生成スクリプト: `../../projects/01-spec2cases-md2json/scripts/spec2cases.mjs`
- サンプルケース: `../examples/spec2cases/cases.sample.json`

## 02. LLM to Playwright
- テスト概要: `../../projects/02-blueprint-to-playwright/tests/README.md`
- サンプルブループリント: `../examples/llm2pw/blueprint.sample.json`
- デモHTML: `../examples/llm2pw/demo`
- 自動生成シナリオ: `../../projects/02-blueprint-to-playwright/tests/generated`
- ビジュアル差分: `../../projects/02-blueprint-to-playwright/tests/generated/__snapshots__`

## 03. CI Flaky Analyzer
- プロダクト README: `../../projects/03-ci-flaky/README.md`
- 仕様書: `../../projects/03-ci-flaky/docs/spec_flaky_analyzer.md`
- 解析ストア: `../../projects/03-ci-flaky/data/runs.jsonl` — `npx flaky parse --input <junit-xml>` で追記
- サマリ HTML: `npx flaky analyze` で生成される `../../projects/03-ci-flaky/out/index.html`（CI からダウンロード可能）

## 04. LLM Adapter
- プロダクト README: `../../projects/04-llm-adapter/README.md`
- エビデンス詳細: `./llm-adapter.md`
- プロバイダ設定サンプル: `../../projects/04-llm-adapter/adapter/config/providers`
- ゴールデンタスク: `../../projects/04-llm-adapter/datasets/golden`

## Docs Cross Reference
- テスト計画: {{ '/test-plan.html' | relative_url }}
- 欠陥レポ例: {{ '/defect-report-sample.html' | relative_url }}
- 週次サマリ: {{ '/weekly-summary.html' | relative_url }}

> [English version]({{ '/en/evidence/README.html' | relative_url }})
