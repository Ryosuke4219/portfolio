# LLM Adapter (Core)

複数プロバイダの LLM 応答を比較・記録・可視化する実験用アダプタです。Shadow 実行なしで本番想定のリクエストを発行し、コスト/レイテンシ/差分率・失敗分類などを JSONL に追記します。`datasets/golden/` のゴールデンタスクと `config/providers/*.yaml` を組み合わせ、基準データに対する回帰テストを高速に行えます。

## Windows PowerShell での文字化け対策

PowerShell から実行する場合は、最初に次の 3 行を流し込んで入出力の文字コードを UTF-8 に揃えてください。

```powershell
[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING="utf-8"
```

## セットアップ

```bash
cd projects/04-llm-adapter
python3 -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\\Scripts\\activate
pip install -r requirements.txt
```

Python 3.10+ を想定。仮想環境下で CLI (`adapter/run_compare.py`) やレポート生成ツールを利用します。

### 最短コマンドで試す

`pip install -e .` でパッケージをインストールすると、`llm-adapter` コマンドから即座にプロバイダを叩けます。

```bash
pip install -e .
llm-adapter --provider adapter/config/providers/openai.yaml --prompt "日本語で1行、自己紹介して"
```

JSONL のバッチを動かしたい場合は `--prompts` を指定します（内部で `adapter/run_compare.py` を呼び出します）。

### Google Gemini を利用する


実プロバイダとして Google Gemini を呼び出す場合は、API キーを `GOOGLE_API_KEY` に設定し、Gemini 用の設定ファイルを指定します。

```bash
export GOOGLE_API_KEY="<取得したAPIキー>"
python adapter/run_compare.py \
  --providers adapter/config/providers/gemini.yaml \
  --prompts datasets/golden/tasks.jsonl
```

`adapter/config/providers/gemini.yaml` では `model: gemini-1.5-flash` を既定とし、料金（入力 0.00035 USD/1k tokens、出力 0.00105 USD/1k tokens）やレートリミット（60 rpm / 60k tpm）を設定済みです。追加の `generation_config` や `safety_settings` を調整したい場合は YAML を編集してください。SDK が `safety_settings` 引数を受け付けない旧バージョンでも、自動的に同引数を除外して再試行します。

### OpenAI を利用する

OpenAI API を利用する場合は、`OPENAI_API_KEY` を設定し OpenAI 用の設定ファイルを指定します。

```bash
export OPENAI_API_KEY="<取得したAPIキー>"
python adapter/run_compare.py \
  --providers adapter/config/providers/openai.yaml \
  --prompts datasets/golden/tasks.jsonl
```

`adapter/config/providers/openai.yaml` では `model: gpt-4o-mini` を既定とし、Responses API を優先的に呼び出します。旧 Chat Completion API しか利用できない SDK バージョンでも自動的にフォールバックします。料金（入力 0.00015 USD/1k tokens、出力 0.00060 USD/1k tokens）やレートリミット（5k rpm / 500k tpm）は目安値です。Azure OpenAI 等でエンドポイントが異なる場合は `endpoint` や `request_kwargs` を適宜上書きしてください。

## コマンド一覧

| コマンド | 説明 |
| --- | --- |
| `python adapter/run_compare.py --providers adapter/config/providers/simulated.yaml --prompts datasets/golden/tasks.jsonl` | 指定プロバイダ構成とゴールデンタスクを比較実行し、`data/runs-metrics.jsonl` に追記します。 |
| `python adapter/run_compare.py --providers <a,b> --mode parallel --repeat 3 --metrics tmp/metrics.jsonl` | 複数プロバイダを並列実行し、出力先をカスタマイズします。 |
| `python tools/report/metrics_to_html.py --metrics data/runs-metrics.jsonl --out reports/index.html` | JSONL メトリクスを HTML ダッシュボードに変換します。 |

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

- 実行ごとのレイテンシ/コスト/トークン数を計測し、`eval.diff_rate` などのメトリクスで決定性を評価します。
- `datasets/golden/baseline/` の期待値と比較し、差分が閾値を超えた場合は `failure_kind` や `budget.hit_stop` を明示します。

## 生成物

- `data/runs-metrics.jsonl` : 1リクエスト=1行のメトリクスログ（既定の追記先）。
- `reports/index.html` : メトリクスを可視化したダッシュボード（Git管理外）。
- `datasets/golden/tasks.jsonl` : ゴールデンタスク定義。`baseline/expectations.jsonl` でプロバイダごとの許容差分を保持。
- `adapter/config/providers/*.yaml` / `adapter/config/budgets.yaml` : プロバイダ別のシード・料金・レート制限と実行予算設定。

## 拡張ポイント

- **Shadow 実行統合**：`projects/04-llm-adapter-shadow` の仕組みを取り込み、プライマリ応答と比較実行を同一 JSONL で記録。
- **評価モジュール追加**：`adapter/core/metrics.py` を拡張し、BLEU/ROUGE や構造比較など用途別メトリクスを追加。
- **外部連携**：`tools/report/metrics_to_html.py` を CI から呼び出し、GitHub Pages や Dashboards SaaS へ自動配信。
- **予算ポリシー強化**：`adapter/core/budgets.py` に日次/週次の複合制限や優先度キューを実装し、コスト最適化を自動化。
