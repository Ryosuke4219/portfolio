# 04. LLM Adapter — Shadow Execution & Error Handling (Minimal)

## Overview

**JP:** プライマリ結果はそのまま採用しつつ、裏で別プロバイダを“影実行”してメトリクスだけを記録する PoC。タイムアウト / レート制限 / 形式不正などの**異常系固定セット**も最小実装で再現します。

**EN:** Minimal adapter that keeps the primary response, mirrors the request on a shadow provider for metrics only, and purposefully reproduces timeout / rate limit / malformed-response failures.

> ℹ️ **本ポートフォリオで外部LLM APIを利用するのはこの04プロジェクトのみです。** 01〜03は決定的なスタブ／ルールベース処理で完結し、ネットワークやAPIキーを必要としません。

## Motivation

- 本番の意思決定を変えずに品質・レイテンシ差分を継続測定 → ベンダ選定や回帰検知に活用。
- 異常系を**明示的に再現**できるため、フォールバックや再試行の動作確認が容易。

## Key Features

- **Shadow execution telemetry** — `run_with_shadow` でプライマリを待ちつつ、別スレッドで影プロバイダを実行。レスポンス差分やフィンガープリントを `artifacts/runs-metrics.jsonl` へ `shadow_diff` イベントとして記録。
- **Fallback runner** — `Runner` が `TimeoutError` / `RateLimitError` / `RetriableError` を捕捉し、次候補へ切り替え。`RateLimitError` は 0.05 秒のバックオフを入れて再試行し、`TimeoutError` / `RetriableError` は即座に次プロバイダへ進む。成功時は `provider_success`、失敗時は `provider_error` / `provider_chain_failed` を発火。
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

### Quickstart — 04: LLM Adapter (Shadow/Fallback)

1. **セットアップ（Windows PowerShell）**

   ```powershell
   cd projects/04-llm-adapter-shadow
   python -m venv .venv
   .\.venv\Scripts\Activate
   pip install -r requirements.txt
   ```

   *PowerShell では bash のヒアドキュメントが使えないため、`python -m venv` や `pip` をそのまま実行するか、`python -c "..."` を活用してください。*

2. **健全性チェック（pytest）**

   ```powershell
   pytest -q
   ```

3. **実行 & メトリクス確認**

   ```powershell
   $env:OPENAI_API_KEY = "sk-..."        # 例: どれか1つは成功するプロバイダ
   $env:GEMINI_API_KEY = "..."          # 無しでも OK（Gemini は自動スキップ）
   python demo_shadow.py
   Get-Content .\artifacts\runs-metrics.jsonl -Last 10
   ```

   1行=1イベントの JSONL が追記されます（`provider_success` / `provider_error` / `provider_skipped` など）。

4. **Gemini（google-genai）利用時の注意**

   新SDK（`google-genai >= 1.38`）では生成パラメータとセーフティ設定を `config=GenerateContentConfig(...)` に集約します。

   ```python
   import os
   from google import genai
   from google.genai import types as gt

   client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
   cfg = gt.GenerateContentConfig(
       max_output_tokens=512,
       temperature=0.3,
       safety_settings=[...],
   )
   resp = client.models.generate_content(
       model="gemini-2.5-flash",
       contents=[{"role": "user", "parts": [{"text": "ping"}]}],
       config=cfg,
   )
   ```

   `GeminiProvider` も同仕様に準拠しており、旧SDK特有の `... unexpected keyword argument 'safety_settings'` は `ConfigError` として正規化されます。

5. **トラブルシュート**

   - `GEMINI_API_KEY` が未設定／空文字なら Gemini は `ProviderSkip` として自動スキップし、`provider_skipped` イベントを記録します。他プロバイダが成功すればチェーン全体は継続します。
   - PowerShell では bash 由来の構文（ヒアドキュメントなど）が動かないため、`python -c "..."` などで置き換えてください。
- `runs-metrics.jsonl` にイベントが追加されない場合は書き込み権限と直前の `provider_chain_failed` ログを確認してください。

> ℹ️ `ProviderResponse.token_usage`（`prompt` / `completion` / `total`）を正式APIとし、旧来の `input_tokens` / `output_tokens` は段階的に非推奨化しています。既存呼び出しは動作を維持しますが、必要に応じて `llm_adapter.provider_spi.SUPPRESS_TOKEN_USAGE_DEPRECATION = True` で警告を抑止できます。

### Provider configuration

- `PRIMARY_PROVIDER` — 形式は `"<prefix>:<model-id>"`。デフォルトは `gemini:gemini-2.5-flash`。
- `SHADOW_PROVIDER` — 影実行用。デフォルトは `ollama:gemma3n:e2b`。`none` や空文字で無効化できます。
- `OLLAMA_BASE_URL` — Ollama API のベースURL（未指定時は `http://127.0.0.1:11434`。旧名の `OLLAMA_HOST` もフォールバックとして解釈されます）。
- `GEMINI_API_KEY` — Gemini SDK が参照するAPIキー。未設定の場合、Gemini プロバイダは安全にスキップされます。


プロバイダ文字列は最初のコロンのみを区切り文字として扱うため、`ollama:gemma3n:e2b` のようにモデルIDにコロンを含めても問題ありません。`mock:foo` を指定するとモックプロバイダで簡易動作確認が可能です。

#### よく使う環境変数例

```bash
export PRIMARY_PROVIDER="gemini:gemini-2.5-flash"
export SHADOW_PROVIDER="ollama:gemma3n:e2b"
export GEMINI_API_KEY="<YOUR_GEMINI_KEY>"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"

```

ルート直下の `.env.example` をコピーして `.env` を作成すると、上記の雛形をそのまま利用できます。

Gemini の構造化出力を利用したい場合は、`generation_config` に
`{"response_mime_type": "application/json"}` や
`{"response_schema": {...}}` を指定すると JSON 固定のレスポンスを要求できます。
`demo_shadow.py` の `request_options` を編集するか、環境変数で
`PRIMARY_OPTIONS` を与えて `ProviderRequest.options` に受け渡してください。Ollama 向けには `REQUEST_TIMEOUT_S`（または小文字の `request_timeout_s`）を指定するとリクエスト単位のタイムアウトを秒数で上書きできます。

### Run the tests

```bash
pytest -q
```

## 例外毎の扱い早見表

| 例外名 | Runner での扱い | 備考 |
| --- | --- | --- |
| `RateLimitError` | 0.05 秒 `time.sleep` した後に次プロバイダで再試行 | メトリクスには `provider_call` (error) として記録 |
| `TimeoutError` | バックオフなしで次プロバイダへ即座に切り替え | 最終的に全滅した場合は `provider_chain_failed` を発火 |
| `RetriableError` | バックオフなしで次プロバイダへ即座に切り替え | 形式不正などの一時的エラーを想定 |
| `ProviderSkip` | スキップ理由のみ `provider_skipped` として記録し、次プロバイダへ進む | 失敗扱いにせずメトリクスで可視化 |

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

- ポートフォリオ全体を通じて、実LLMプロバイダ統合はこの04だけに閉じています。他のチャプターは決定的（deterministic）な処理で構成されています。
- 実プロバイダ統合は Gemini（Google AI Studio）とローカル Ollama の最小構成に限定し、Mock プロバイダでネットワーク無しのテストも維持しています。
- メトリクスは JSONL に追記するだけの最小構成です。
- 後続の LLM Adapter OSS 本体とは**独立**して動作する、ポートフォリオ用サンプルです。

