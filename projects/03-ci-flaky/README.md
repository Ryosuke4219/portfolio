# Flaky Analyzer CLI

`flaky` コマンドは JUnit 形式のテスト結果から Flaky テストを検出・可視化・レポートする最小構成のツールです。以下は代表的なサブコマンドです。

## セットアップ

```bash
npm install
```

## コマンド一覧

| コマンド | 説明 |
| --- | --- |
| `flaky parse` | JUnit XML をストリーミング解析して JSONL ストアへ追記します。 |
| `flaky analyze` | 直近ウィンドウの履歴からスコア集計・ランキング・HTML レポートを生成します。 |
| `flaky report` | `analyze` と同等。HTML レポートを再生成したいときに利用します。 |
| `flaky issue` | 閾値超のテストを Markdown 形式で起票テンプレート化します（Dry-run 対応）。 |
| `flaky weekly` | 週次サマリを `docs/weekly-summary.md` に追記します。 |

## 代表的な使い方

```bash
# 1. JUnit XML を取り込む（CI から取得した XML or ローカルの `test-results/**/*.xml` を指定）
flaky parse --input ./path/to/junit-xml/ \
  --run-id ci_2025_001 --branch main --commit deadbeef

# 2. 解析・レポート生成
flaky analyze --config projects/03-ci-flaky/config/flaky.yml

# 3. GitHub Issue テンプレ生成（dry-run）
flaky issue --top-n 10
```

## 設定ファイル

`projects/03-ci-flaky/config/flaky.yml` でウィンドウサイズ、スコア重み、出力先ディレクトリなどを調整できます。

## 生成物

- `data/runs.jsonl` : 履歴ストア（1 Attempt = 1 行）
- `out/summary.json` / `out/summary.csv`
- `out/flaky_rank.json` / `out/flaky_rank.csv`
- `out/index.html`
- `out/issues/*.md` （Dry-run 時）

CI での利用例は `npm run ci:analyze` および `npm run ci:issue` を参照してください。

> ℹ️ `out/` 配下の HTML/CSV はコマンド実行時に生成される成果物であり、リポジトリには含めていません。必要に応じて CI アーティファクトやローカル実行で再取得してください。
