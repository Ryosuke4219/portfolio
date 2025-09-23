# LLM Adapter Lab — 生成物ガイド

影（shadow）実行とフォールバック検証で得られる JSONL / HTML レポートは都度生成し、リポジトリへはコミットしない運用です。

## 生成手順
1. 依存関係を準備:
   ```bash
   just setup        # または python3 -m venv .venv && source .venv/bin/activate
   pip install -r projects/04-llm-adapter/requirements.txt
   ```
2. 比較ランナーを実行してメトリクスを追記:
   ```bash
   python projects/04-llm-adapter/adapter/run_compare.py \
     --config projects/04-llm-adapter/adapter/config/providers/openai.yaml \
     --repeat 3
   # => projects/04-llm-adapter/data/runs-metrics.jsonl に追記
   ```
3. HTML レポートを生成:
   ```bash
   python projects/04-llm-adapter/tools/report/metrics_to_html.py \
     --input projects/04-llm-adapter/data/runs-metrics.jsonl \
     --output projects/04-llm-adapter/reports/index.html
   ```

> **Note:** `data/` と `reports/` 配下は `.gitignore` で除外されています。任意の実行結果をローカルで生成し、GitHub Pages へ公開する際は Actions からアップロードします。

## 最新スクショ
HTML レポートのレイアウトイメージです。実際の比較結果は上記手順で生成した `reports/index.html` をブラウザで開いて確認してください。

![LLM Adapter Metrics Dashboard](./latest.svg)
