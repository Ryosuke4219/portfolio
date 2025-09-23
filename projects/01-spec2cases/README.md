# Spec2Cases CLI

Markdown/テキスト仕様書から構造化テストケース(JSON)を生成し、軽量なCLIで検証・擬似実行まで行う最小パイプラインです。`docs/examples/spec2cases/` のサンプルをもとにフロー全体を再現できます。

## セットアップ

```bash
npm install
```

Node.js 18+ を想定しています。リポジトリ直下で `npm install` を実行すると、全スクリプトが `node` または `npm run ...` で利用可能になります。

## コマンド一覧

| コマンド | 説明 |
| --- | --- |
| `npm run spec:generate` | Markdown仕様 (`spec.sample.md`) から JSON テストケースを生成します。 |
| `npm run spec:from-text` | プレーンテキスト仕様 (`spec.sample.txt`) を JSON に変換し、サンプル出力を更新します。 |
| `npm run spec:validate -- <path>` | JSON 定義をスキーマチェックします。引数なしの場合はサンプルを使用。 |
| `npm run spec:run -- <cases.json> [--tag <tag>] [--id <id>]` | テストケースを読み込み、タグ/IDでフィルタしながら擬似実行レポートを表示します。 |

> CLI を直接利用する場合は `projects/01-spec2cases/scripts/*.mjs` を `node` で呼び出せます。

## 代表的な使い方

```bash
# 1. Markdown仕様からケースを生成（sample を上書き）
npm run spec:generate
# => projects/01-spec2cases/cases.generated.json

# 2. 生成物のスキーマを検証（期待・手順欠落を検出）
npm run spec:validate -- projects/01-spec2cases/cases.generated.json

# 3. タグでフィルタして擬似実行
npm run spec:run -- projects/01-spec2cases/cases.generated.json --tag smoke
```

* `spec2cases.mjs` は Markdown/テキスト/JSON を自動判別し、必要に応じて JSON を標準出力へ書き出します。
* `run_cases.mjs` は手順・期待値の欠落を失敗としてカウントし、仕様の穴を早期検出できます。

## 生成物

- `projects/01-spec2cases/cases.generated.json` : Markdown仕様から生成された最新テストケース。
- `docs/examples/spec2cases/cases.sample.json` : テキスト仕様から生成されるサンプル出力。
- CLI 実行ログ : `spec:run` 実行時のサマリ (標準出力)。

## 拡張ポイント

- **フォーマット追加**：CSV/Gherkin など別形式の仕様から同一スキーマに変換するアダプタを追加可能。
- **実行エンジン差し替え**：`run_cases.mjs` を他言語ランナーに置き換え、実際のテスト自動化に接続。
- **CI 連携**：生成→検証→擬似実行を GitHub Actions の Job として連結し、仕様変更の差分を定常的に検証。
- **メタデータ拡張**：`schema.json` を拡張して優先度やオーナー情報を付与し、テスト計画と連動。
