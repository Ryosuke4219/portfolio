````markdown
# LLM Adapter (Core)

- [概要](#概要)
- [Windows PowerShell での文字化け対策](#windows-powershell-での文字化け対策)
- [セットアップ](#セットアップ)
- [CLI クイックスタート](#cli-クイックスタート)
- [サンプル設定とプロンプト](#サンプル設定とプロンプト)
- [Troubleshooting](#troubleshooting)
- [コマンド一覧](#コマンド一覧)
- [代表的な使い方](#代表的な使い方)
- [生成物](#生成物)
- [拡張ポイント](#拡張ポイント)

# 概要

複数プロバイダの LLM 応答を比較・記録・可視化する実験用アダプタです。Shadow 実行なしで本番想定のリクエストを発行し、コスト/レイテンシ/差分率・失敗分類などを JSONL に追記します。`datasets/golden/` のゴールデンタスクと `adapter/config/providers/*.yaml` を組み合わせ、基準データに対する回帰テストを高速に行えます。

## Windows PowerShell での文字化け対策

PowerShell から実行する場合は、最初に次の 3 行を流し込んで入出力の文字コードを UTF-8 に揃えてください。

```powershell
[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING="utf-8"
````

## セットアップ

```bash
cd projects/04-llm-adapter
python3 -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.10+ を想定。仮想環境下で CLI (`adapter/run_compare.py`) やレポート生成ツールを利用します。

## CLI クイックスタート

`pip install -e .` でパッケージをインストールすると、`llm-adapter` コマンドから即座にプロバイダを叩けます。

```bash
pip install -e .
llm-adapter --provider adapter/config/providers/openai.yaml --prompt "日本語で1行、自己紹介して"
```

### 出力フォーマットを選ぶ

`--format {text,json,jsonl}` で出力形式を選択できます（既定: `text`）。`json`/`jsonl` では `provider` / `model` / `endpoint` / `latency_ms` / `input_tokens` / `output_tokens` / `cost_usd` / `status` / `error` / `prompt_sha256` を含むメトリクスを出力します。

```bash
llm-adapter --provider adapter/config/providers/openai.yaml \
  --prompt "関西弁で今日の天気を一言" --format json
```

### ログと保存をまとめる

* `--json-logs` : 標準エラーに JSON 形式の進捗ログを出力。
* `--out out/` : `out/metrics.jsonl` にメトリクスを追記。
* `--log-prompts` : JSON/JSONL 出力やメトリクス書き出しにプロンプト本文を含める（既定では非表示）。

```bash
llm-adapter --provider adapter/config/providers/openai.yaml \
  --prompts examples/prompts/ja_one_liner.jsonl \
  --format jsonl --out out --json-logs
```

### プロンプト入力の選択肢

* `--prompt` : コマンドラインで直接指定。
* `--prompt-file` : テキストファイル全体を 1 プロンプトとして送信。
* `--prompts` : JSONL ファイルから複数プロンプトを読み込む（`{"prompt": "..."}` 形式）。

いずれも内部で同じ処理パイプラインに流れ、メトリクスを取得します。

### プロンプトを安全に扱う

既定では JSON/JSONL やログにプロンプト本文を出力せず、`prompt_sha256` のみを公開します。後続処理で本文が必要な場合は `--log-prompts` を明示してください。例外ログ内の URL クエリや Authorization ヘッダは自動的にマスクされます。

### 並列実行とレート制御

* `--parallel` : CPU コア数に合わせて最大 8 並列で実行。
* `--rpm 60` : 1 分あたりの実行回数を制限（トークンベースの制御は今後追加予定）。

### .env の読み込み

Windows で環境変数を毎回設定する手間を省くため、`--env .env` で必要なキーを読み込み可能です。`python-dotenv` が未インストールの場合は、インストール方法を案内します。

### エラーメッセージの言語切替

`--lang ja|en` または環境変数 `LLM_ADAPTER_LANG` で CLI のメッセージを日本語/英語に切り替えられます。ログを共有する際に便利です。

### 既知の落とし穴を自動検知

* API キー未設定時には、必要な環境変数名を明示。
* OpenAI の 429 / quota 超過時には、請求・使用量・プロジェクトキーの確認ポイントを案内。

失敗してもメトリクスは `status=error` として記録され、JSON 出力や `--out` から後続処理に利用できます。

### 環境診断（doctor）

`llm-adapter doctor` で Python バージョン・仮想環境・API キー・DNS/HTTPS 接続・エンコーディング・`.env` 依存関係・RPM 上限を一括チェックできます。問題が見つかると ❌ と対処法を 1 行で表示し、終了コード 3 を返します。

### JSONL バッチ実行（run_compare 併用）

`--prompts` を指定すると JSONL バッチを実行できます（内部で `adapter/run_compare.py` を呼び出します）。

### Google Gemini を利用する

実プロバイダとして Google Gemini を呼び出す場合は、API キーを `GOOGLE_API_KEY` に設定し、Gemini 用の設定ファイルを指定します。

```bash
export GOOGLE_API_KEY="<取得したAPIキー>"
python adapter/run_compare.py \
  --providers adapter/config/providers/gemini.yaml \
  --prompts datasets/golden/tasks.jsonl
```

`adapter/config/providers/gemini.yaml` では `model: gemini-1.5-flash` を既定とし、料金やレートリミットは目安値として記載しています（最新は各社の公式を参照）。追加の `generation_config` や `safety_settings` を調整したい場合は YAML を編集してください。SDK が `safety_settings` 引数を受け付けない旧バージョンでも、自動的に同引数を除外して再試行します。

### OpenAI を利用する

OpenAI API を利用する場合は、`OPENAI_API_KEY` を設定し OpenAI 用の設定ファイルを指定します。

```bash
export OPENAI_API_KEY="<取得したAPIキー>"
python adapter/run_compare.py \
  --providers adapter/config/providers/openai.yaml \
  --prompts datasets/golden/tasks.jsonl
```

`adapter/config/providers/openai.yaml` では `model: gpt-4o-mini` を既定とし、Responses API を優先的に呼び出します。旧 Chat Completion API しか利用できない SDK バージョンでも自動的にフォールバックします。料金やレートリミットは目安値です。Azure OpenAI 等でエンドポイントが異なる場合は `endpoint` や `request_kwargs` を適宜上書きしてください。

## サンプル設定とプロンプト

* `examples/providers/openai.yml` : OpenAI Responses API 用の最小構成。
* `examples/providers/gemini.yml` : Gemini 1.5 Flash 用のサンプル。
* `examples/prompts/ja_one_liner.jsonl` : 日本語 1 行プロンプトの JSONL テンプレート。
* `scripts/windows/setup.ps1` : UTF-8 設定・仮想環境作成・`pip install -e .`・サンプル実行までを 1 コマンドで整える PowerShell スクリプト。

必要な API キーは `.env.example` をコピーして `.env` を作成し、`--env .env` で読み込むと便利です。

## Troubleshooting

* **事前に `llm-adapter doctor` を実行**: ネットワークや API キー、エンコーディング設定を自動チェックできます。
* **API キーが未設定**: `RuntimeError` を検出すると、CLI が「環境変数 `<KEY>` を設定してください」と案内します。`.env` を作成し `--env .env` で読み込みましょう。
* **OpenAI の quota / 429**: `OpenAI quota exceeded` エラー時は、ダッシュボードの請求・使用量・プロジェクトキーのクォータを確認してください。CLI も同旨のメッセージを表示します。
* **Windows での文字化け**: 冒頭の UTF-8 設定を実施するか、`scripts/windows/setup.ps1` を実行します。
* **PYTHONPATH の設定が必要?**: `pip install -e .` 済みなら不要です。CLI も仮想環境内から直接利用できます。
* **Gemini での safety_settings エラー**: 旧 SDK では自動で該当引数を除外して再試行します。それでも失敗する場合は `adapter/config/providers/gemini.yaml` の設定を調整してください。

## 終了コード早見表

| Exit Code | 意味                |
| --------- | ----------------- |
| 0         | 正常終了              |
| 2         | 入力エラー（引数やファイル不備）  |
| 3         | 環境問題（API キー未設定など） |
| 4         | ネットワーク障害          |
| 5         | プロバイダ起因の失敗        |
| 6         | レート/クォータ上限に到達     |

## コマンド一覧

| コマンド                                                                                                                      | 説明                                                         |
| ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `python adapter/run_compare.py --providers adapter/config/providers/simulated.yaml --prompts datasets/golden/tasks.jsonl` | 指定プロバイダ構成とゴールデンタスクを比較実行し、`data/runs-metrics.jsonl` に追記します。 |
| `python adapter/run_compare.py --providers <a,b> --mode parallel --repeat 3 --metrics tmp/metrics.jsonl`                  | 複数プロバイダを並列実行し、出力先をカスタマイズします。                               |
| `python tools/report/metrics_to_html.py --metrics data/runs-metrics.jsonl --out reports/index.html`                       | JSONL メトリクスを HTML ダッシュボードに変換します。                           |

> `--budgets` で `adapter/config/budgets.yaml` を差し替えると、実行ごとのコスト上限や停止条件を変更できます。

## 代表的な使い方

```bash
# 1. 仮想環境を有効化し、サンプル設定で比較実行
python adapter/run_compare.py \
  --providers adapter/config/providers/simulated.yaml \
  --prompts datasets/golden/tasks.jsonl \
  --repeat 2 \
  --mode serial
# => data/runs-metrics.jsonl に追記（プロジェクト直下に data/ が自動生成されます）

# 2. 収集したメトリクスを HTML に変換
python tools/report/metrics_to_html.py \
  --metrics data/runs-metrics.jsonl \
  --golden datasets/golden/baseline \
  --out reports/index.html
```

* 実行ごとのレイテンシ/コスト/トークン数を計測し、`eval.diff_rate` などのメトリクスで決定性を評価します。
* `datasets/golden/baseline/` の期待値と比較し、差分が閾値を超えた場合は `failure_kind` や `budget.hit_stop` を明示します。

## 生成物

* `data/runs-metrics.jsonl` : 1リクエスト=1行のメトリクスログ（既定の追記先）。
* `reports/index.html` : メトリクスを可視化したダッシュボード（Git管理外）。
* `datasets/golden/tasks.jsonl` : ゴールデンタスク定義。`baseline/expectations.jsonl` でプロバイダごとの許容差分を保持。
* `adapter/config/providers/*.yaml` / `adapter/config/budgets.yaml` : プロバイダ別のシード・料金・レート制限と実行予算設定。

## 拡張ポイント

* **Shadow 実行統合**：`projects/04-llm-adapter-shadow` の仕組みを取り込み、プライマリ応答と比較実行を同一 JSONL で記録。
* **評価モジュール追加**：`adapter/core/metrics.py` を拡張し、BLEU/ROUGE や構造比較など用途別メトリクスを追加。
* **外部連携**：`tools/report/metrics_to_html.py` を CI から呼び出し、GitHub Pages や Dashboards SaaS へ自動配信。
* **予算ポリシー強化**：`adapter/core/budgets.py` に日次/週次の複合制限や優先度キューを実装し、コスト最適化を自動化。

```
