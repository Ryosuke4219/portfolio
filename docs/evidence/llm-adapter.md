---
layout: default
title: LLM Adapter — Shadow Execution
description: 影実行でメトリクスを収集し異常系も再現する LLM アダプタのハイライト
---

# LLM Adapter — Shadow Execution

メインの LLM プロバイダを維持したまま、影（shadow）実行で別プロバイダを並走させるアダプタです。レスポンス差分や異常系イベントを JSONL に記録し、フォールバックやベンダ比較のための計測基盤を最小構成で提供します。

## Highlights

- `run_with_shadow` でプライマリ結果を返しつつ、影プロバイダのメトリクスを非同期収集。
- タイムアウト / レート制限 / 形式不正を `[TIMEOUT]` などのマーカーで再現し、フォールバック挙動をテスト可能。
- `Runner` が例外ハンドリングとプロバイダ切り替えを担い、イベントログを `artifacts/runs-metrics.jsonl` へ蓄積。

## Key Artifacts

- [README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/README.md) — アダプタの概要と使い方。
- [src/llm_adapter/runner.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/src/llm_adapter/runner.py) — フォールバック制御の中核ロジック。
- [src/llm_adapter/metrics.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/src/llm_adapter/metrics.py) — JSONL でのメトリクス記録。
- [demo_shadow.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/demo_shadow.py) — 影実行デモとイベント出力。

## How to Reproduce

1. `projects/04-llm-adapter-shadow/` で仮想環境を作成し、`pip install -r requirements.txt` を実行。
2. `python demo_shadow.py` で影実行の動作と `artifacts/runs-metrics.jsonl` のログを確認。
3. `pytest -q` で shadow diff / error handling に関するテストを実行。

## Next Steps

- 実プロバイダ SDK を `providers/` に追加し、メトリクスの比較軸（レイテンシ・トークン使用量）を拡張。
- JSONL をデータ基盤に送信し、週次の影響度を [週次サマリ一覧]({{ '/weekly-summary.html' | relative_url }}) に記録。
- `Runner` のイベント出力を OpenTelemetry 形式に変換し、監視ツールとの連携を強化。
