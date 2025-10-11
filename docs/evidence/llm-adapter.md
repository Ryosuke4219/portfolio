---
layout: default
title: LLM Adapter — Provider Benchmarking
description: 複数プロバイダの比較・記録・可視化を一括で担う LLM アダプタのハイライト
---

> [English version]({{ '/en/evidence/llm-adapter.html' | relative_url }})

# LLM Adapter — Provider Benchmarking

複数プロバイダの LLM 応答を比較・記録・可視化する実験用アダプタです。Shadow 実行ではなく、本番想定のプロンプトを同一条件で投げ、
レスポンス差分・レイテンシ・コスト・失敗分類を JSONL に追記します。`datasets/golden/` のゴールデンタスクと `adapter/config/providers/`
の設定ファイルを組み合わせ、基準データに対する回帰テストを高速に行えます。

## Highlights

- `llm-adapter` CLI が `adapter/run_compare.py` を通じて複数プロバイダを連続・並列・合意形成モードで呼び出し、共通メトリクスを収集。
- `adapter/core/runner_execution.py` のランナーがリトライやプロバイダ固有の例外を整理し、比較用のイベントをストリーム出力。
- `adapter/core/metrics.py` が JSONL メトリクスと派生サマリを構築し、CLI の `--out` で指定した `out/metrics.jsonl` などに追記可能（既定の `adapter/run_compare.py` は `data/runs-metrics.jsonl` に保存）。

## Key Artifacts

- [README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter/README.md) — CLI と設定ファイルの詳細な説明。
- [adapter/run_compare.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter/adapter/run_compare.py) — CLI の比較モード実装とエントリポイント。
- [adapter/core/runner_execution.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter/adapter/core/runner_execution.py) — プロバイダ実行・リトライ・メトリクス集約の中心ロジック。
- [adapter/core/metrics.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter/adapter/core/metrics.py) — メトリクス構造体と JSONL 出力ユーティリティ。

## How to Reproduce

1. `cd projects/04-llm-adapter` で仮想環境を作成し、`pip install -r requirements.txt` を実行して依存関係を揃える。
2. `pip install -e .` で CLI をインストールし、`llm-adapter --provider adapter/config/providers/openai.yaml --prompt "日本語で1行、自己紹介して" --out out --json-logs` を実行。`--out` で指定したディレクトリ（例: `out/metrics.jsonl`）へ比較結果が追記される。`python adapter/run_compare.py ...` を直接呼び出す場合は既定で `data/runs-metrics.jsonl` に出力される。
3. `pytest -q` を流して CLI・ランナー・メトリクスのユニットテストが通ることを確認。

## Next Steps

- 実プロバイダ SDK を `adapter/core/providers/` に追加し、レイテンシやコストの比較軸を拡張。
- JSONL をデータ基盤に送信し、週次の影響度を [週次サマリ一覧]({{ '/weekly-summary.html' | relative_url }}) に記録。
- `adapter/core/runner_async.py` を活用して非同期ランナーとの連携やストリーム応答の評価を強化。
