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

- `llm-adapter --provider ...` での単体実行は Typer ベースの CLI (`adapter/cli/app.py`) から `adapter/cli/prompts.py` を経由して `adapter/cli/prompt_runner.py` に入り、プロンプト並列実行・メトリクス採取・ストレージ書き込みを担う。
- `adapter/run_compare.py` は上記と同一メトリクス形式を用いて複数プロバイダを連続・並列・合意形成モードで呼び出し、共通メトリクスを収集。
- `adapter/core/runner_execution.py` のランナーがリトライやプロバイダ固有の例外を整理し、比較用のイベントをストリーム出力。
- `adapter/core/metrics/update.py` と `adapter/core/metrics/models.py` が JSONL メトリクスと派生サマリを構築し、CLI の `--out` で指定した `out/metrics.jsonl` などに追記可能（既定の `adapter/run_compare.py` は `data/runs-metrics.jsonl` に保存）。

## Key Artifacts

- [projects/04-llm-adapter/README.md](../../projects/04-llm-adapter/README.md) — CLI と設定ファイルの詳細な説明。
- [projects/04-llm-adapter/adapter/cli/prompt_runner.py](../../projects/04-llm-adapter/adapter/cli/prompt_runner.py) — `llm-adapter --provider ...` 実行時のプロンプトループとメトリクス生成。
- [projects/04-llm-adapter/adapter/run_compare.py](../../projects/04-llm-adapter/adapter/run_compare.py) — CLI の比較モード実装とエントリポイント。
- [projects/04-llm-adapter/adapter/core/runner_execution.py](../../projects/04-llm-adapter/adapter/core/runner_execution.py) — プロバイダ実行・リトライ・メトリクス集約の中心ロジック。
- [projects/04-llm-adapter/adapter/core/metrics/update.py](../../projects/04-llm-adapter/adapter/core/metrics/update.py) — JSONL メトリクス更新ユーティリティ。
- [projects/04-llm-adapter/adapter/core/metrics/models.py](../../projects/04-llm-adapter/adapter/core/metrics/models.py) — メトリクス構造体とシリアライズモデル。

## How to Reproduce

1. `cd projects/04-llm-adapter` で仮想環境を作成し、`pip install -r requirements.txt` を実行して依存関係を揃える。
2. `pip install -e .` で CLI をインストールし、`llm-adapter --provider adapter/config/providers/openai.yaml --prompt "日本語で1行、自己紹介して" --out out --json-logs` を実行。Typer CLI (`adapter/cli/app.py`) から `adapter/cli/prompts.py` を通じて `adapter/cli/prompt_runner.py` が呼ばれ、`--provider` で指定した設定を元にプロンプトを実行し、`--out` で指定したディレクトリ（例: `out/metrics.jsonl`）へメトリクスを追記する。内部処理をデバッグしたい場合は `python -m adapter.cli.prompts --provider ...` で同じフローを再現でき、`python adapter/run_compare.py ...` を呼ぶ場合は既定で `data/runs-metrics.jsonl` に出力される。
3. `pytest -q` を流して CLI・ランナー・メトリクスのユニットテストが通ることを確認。

## Next Steps

- `tools/report/metrics/cli.py` と `tools/report/metrics/weekly_summary.py` を CI ジョブに組み込み、`reports/index.html` と `docs/weekly-summary.md` を自動生成。
- `datasets/golden/` と `datasets/golden/baseline/` を拡充し、`tools/report/metrics/regression_summary.py` を通じて回帰検知を自動化。
- `adapter/core/metrics/diff.py` を拡張し、構造化応答向けメトリクスを `RunMetrics.eval` に取り込む。
