# QA Evidence Catalog

本カタログは RTM に記載された `EvidenceLink` の遷移先をまとめ、検証時に参照する一次情報を一覧化する。

## 01. Spec to Cases
- ケース設計テンプレ: `../examples/spec2cases/spec.sample.md`
- 自動生成スクリプト: `../projects/01-spec2cases/scripts/spec2cases.mjs`
- サンプルケース: `../examples/spec2cases/cases.sample.json`

## 02. LLM to Playwright
- テスト概要: `../projects/02-llm-to-playwright/tests/README.md`
- サンプルブループリント: `../examples/llm2pw/blueprint.sample.json`
- デモHTML: `../examples/llm2pw/demo`
- 自動生成シナリオ: `../projects/02-llm-to-playwright/tests/generated`
- ビジュアル差分: `../projects/02-llm-to-playwright/tests/generated/__snapshots__`

## 03. CI Flaky Analyzer
- プロダクト README: `../projects/03-ci-flaky/README.md`
- 仕様書: `../projects/03-ci-flaky/docs/spec_flaky_analyzer.md`
- デモ JUnit: `../projects/03-ci-flaky/demo/junit-run-fail.xml`
- サマリ HTML: `../projects/03-ci-flaky/out/index.html`

## Docs Cross Reference
- テスト計画: `../docs/test-plan.md`
- 欠陥レポ例: `../docs/defect-report-sample.md`
- 週次サマリ: `../docs/weekly-summary.md`
