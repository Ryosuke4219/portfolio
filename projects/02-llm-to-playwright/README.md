# LLM → Playwright Pipeline

LLM から受け取ったブループリント(JSON)を検証し、Playwright 互換のテストコードを生成・実行・可視化する PoC です。静的デモ (`docs/examples/llm2pw/demo/`) とスタブランナーを同梱し、LLM 補完から CI 連携までの一連の流れを再現できます。

## セットアップ

```bash
npm install
```

Node.js 18+ を想定。依存解決後は `npm run e2e:gen` / `npm test` などの npm script を利用できます。

## コマンド一覧

| コマンド | 説明 |
| --- | --- |
| `npm run e2e:gen` | ブループリント (`blueprint.sample.json`) を検証し、Playwright テストコードを `tests/generated/` に生成します。 |
| `npm test` | Playwright スタブランナーで生成済みテストを実行し、`junit-results.xml` / `test-results/` を出力します。 |
| `node projects/02-llm-to-playwright/server.mjs` | デモ HTML をローカル配信し、UI/セレクタの挙動をブラウザで確認できます。 |

> `scripts/blueprint_to_code.mjs` を直接実行すると、任意のブループリントファイルを指定してコード生成できます。

## ワークフロー

1. **LLM 補完** — 受け入れ基準やシナリオをプロンプトとして投げ、`scenarios[]` を含むブループリント JSON を取得。
2. **テスト生成** — `blueprint_to_code.mjs` がセレクタ/データ/アサーションを検証しつつ `.spec.ts` を生成。重複 ID や欠損時はエラーで停止。
3. **テスト実行** — `npm test` がスタブ化された Playwright ランナーを呼び出し、DOM のテキスト検証・フォーム操作・ビジュアル/アクセシビリティスモークを実施。
4. **成果物活用** — JUnit XML / `test-results/` / スナップショット差分を `projects/03-ci-flaky` の解析コマンドへ渡し、履歴や Issue 起票に利用。

## 生成物

- `projects/02-llm-to-playwright/tests/generated/*.spec.ts` : ブループリントから生成された Playwright テスト。
- `projects/02-llm-to-playwright/tests/generated/__snapshots__/` : ビジュアルスモークのゴールデンファイル。
- `junit-results.xml`, `test-results/` : スタブランナーによる実行ログ (CI でアーティファクト化)。

詳細なセレクタガイドや a11y/ビジュアル運用メモは [`tests/README.md`](tests/README.md) を参照してください。

## 拡張ポイント

- **HITL レビュー支援**：ブループリントを PR コメントに埋め込み、差分レビューツールとして活用。
- **UI カバレッジ拡張**：`login-cases.json` や `a11y-pages.csv` を増やし、データドリブンでシナリオを追加。
- **実ブラウザ統合**：スタブを本物の Playwright ランナーに差し替え、`server.mjs` で配信するデモや外部環境に接続。
- **生成ガード強化**：セレクタ命名規則やアクセシビリティ要件を追加検証し、LLM 生成物の品質を自動診断。
