---
layout: default
title: LLM to Playwright
description: 受け入れ基準を拡張して自動生成 Playwright テストへ落とし込む PoC のハイライト
---

> [English version]({{ '/en/evidence/llm2pw.html' | relative_url }})

# LLM to Playwright

要求仕様の文章を LLM が補完し、Playwright テストコードへ自動変換する PoC です。堅牢なセレクタ戦略と a11y スキャン、データ駆動実行を最小構成で確認できます。

## Highlights

- `data-testid` を最優先するセレクタ戦略と、ARIA / role でのフォールバックをガイドライン化。
- `tests/generated/` 配下のスナップショットや a11y ルールを含むサンプルテストを自動生成。
- JSON / CSV を読み込んでテストケースをループ生成し、追加時はデータファイルの編集のみで済む設計。

## Key Artifacts

- [tests/generated/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/02-llm-to-playwright/tests/generated) — 自動生成された Playwright テスト群。
- [tests/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/tests/README.md) — セレクタ / スナップショット / a11y 方針の詳細メモ。
- [blueprint.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/blueprint.sample.json) — LLM が拡張する元データのサンプル。
- [scripts/generate-tests.mjs](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/scripts/generate-tests.mjs) — LLM 呼び出しとコード生成のドライバ。

## How to Reproduce

1. `projects/02-llm-to-playwright/` で `npm install` を実行して依存関係を取得。
2. `npm run generate`（サンプル設定）で Playwright テストを再生成。
3. `npx playwright test` で自動生成テストを実行し、a11y / スナップショット検証を確認。

## Next Steps

- 追加の受け入れ基準を `blueprint.sample.json` に追記し、LLM の生成幅をコントロール。
- 生成コードの差分レビューを GitHub Actions で自動化し、週次の変化を `weekly-summary` に反映。
- 実案件へ組み込む際は Secrets 管理を強化し、Playwright の `--update-snapshots` を CI に統合。
