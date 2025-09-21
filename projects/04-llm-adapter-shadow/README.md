# 04. LLM Adapter — Shadow Execution & Error Handling (Minimal)

## Overview

**JP:** プライマリ結果はそのまま採用しつつ、裏で別プロバイダを“影実行”してメトリクスだけを記録する PoC。タイムアウト / レート制限 / 形式不正などの**異常系固定セット**も最小実装で再現します。

**EN:** Minimal adapter that keeps the primary response, mirrors the request on a shadow provider for metrics only, and purposefully reproduces timeout / rate limit / malformed-response failures.

## Motivation

- 本番の意思決定を変えずに品質・レイテンシ差分を継続測定 → ベンダ選定や回帰検知に活用。
- 異常系を**明示的に再現**できるため、フォールバックや再試行の動作確認が容易。

## Key Features

- **Shadow execution telemetry** — `run_with_shadow` でプライマリを待ちつつ、別スレッドで影プロバイダを実行。レスポンス差分やフィンガープリントを `artifacts/runs-metrics.jsonl` へ `shadow_diff` イベントとして記録。
- **Fallback runner** — `Runner` が `TimeoutError` / `RateLimitError` / `RetriableError` を捕捉し、次候補へ切り替え。成功時は `provider_success`、失敗時は `provider_error` / `provider_chain_failed` を発火。
- **Deterministic error simulation** — `MockProvider` はプロンプト中の `[TIMEOUT]` / `[RATELIMIT]` / `[INVALID_JSON]` を検知して対応する例外を投げ、異常系をテストから容易に再現。

## Directory Layout

```
projects/04-llm-adapter-shadow/
  ├─ src/llm_adapter/
  │   ├─ __init__.py
  │   ├─ provider_spi.py
  │   ├─ errors.py
  │   ├─ metrics.py
  │   ├─ utils.py
  │   ├─ runner.py
  │   └─ providers/mock.py
  ├─ tests/
  │   ├─ test_err_cases.py
  │   └─ test_shadow.py
  ├─ demo_shadow.py
  ├─ pyproject.toml
  └─ requirements.txt
```

## Usage

### Setup

```bash
# repo root
cd projects/04-llm-adapter-shadow
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Run the demo

```bash
python demo_shadow.py
```

標準出力でプライマリ結果を確認しつつ、影実行のメトリクスが `artifacts/runs-metrics.jsonl` に追記されます。

### Run the tests

```bash
pytest -q
```

## Shadow Execution Metrics

- `run_with_shadow(primary, shadow, request)` はプライマリ結果をそのまま返し、影実行はデーモンスレッドで並列に実行。
- 影実行が完了すると、`shadow_diff` イベントが記録され、主なフィールドとして以下を含みます:
  - `request_hash` / `request_fingerprint` — プロバイダ固有・ランナー共通のハッシュ値。
  - `primary_provider`, `primary_latency_ms`, `primary_text_len`, `primary_token_usage_total`。
  - `shadow_provider`, `shadow_ok`, `shadow_latency_ms`, `shadow_duration_ms`, `shadow_error`。
  - 成功時のみ `latency_gap_ms`, `shadow_text_len`, `shadow_token_usage_total` を追加。
  - 例外が発生した場合は `shadow_error_message` に詳細を格納。
- `metrics_path=None` を渡すとメトリクス出力を無効化できます。

### Example `shadow_diff`

```json
{
  "ts": 1700000000000,
  "event": "shadow_diff",
  "request_hash": "7b84e1542fabe2c3",
  "request_fingerprint": "a9d58e3f21d04ce1",
  "primary_provider": "primary",
  "primary_latency_ms": 57,
  "primary_text_len": 24,
  "primary_token_usage_total": 28,
  "shadow_provider": "shadow",
  "shadow_ok": true,
  "shadow_latency_ms": 61,
  "shadow_duration_ms": 63,
  "latency_gap_ms": 4,
  "shadow_text_len": 24,
  "shadow_token_usage_total": 28
}
```

## Error Handling & Mock Providers

- `MockProvider` の `error_markers` 引数で有効化するマーカーを制御可能（未指定時は全マーカー有効）。
- `[TIMEOUT]` → `TimeoutError`
- `[RATELIMIT]` → `RateLimitError`
- `[INVALID_JSON]` → `RetriableError`（再試行向けの汎用例外）
- `Runner` は失敗を `provider_error` として記録し、最終的に全てのプロバイダが失敗した場合は `provider_chain_failed` を出力して例外を再送出します。

## Notes

- 実プロバイダ統合は意図的に含めていません（**軽量のまま**にするため）。
- メトリクスは JSONL に追記するだけの最小構成です。
- 後続の LLM Adapter OSS 本体とは**独立**して動作する、ポートフォリオ用サンプルです。

