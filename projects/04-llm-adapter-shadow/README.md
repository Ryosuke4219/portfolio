# 04. LLM Adapter — Shadow Execution & Error Handling (Minimal)

> ⚠️ **アーカイブ済み:** この Shadow 版は保存目的で維持されています。最新手順および更新情報は [projects/04-llm-adapter](../04-llm-adapter/README.md) 配下の本体 README を参照してください。

## Overview

**JP:** プライマリ結果はそのまま採用しつつ、裏で別プロバイダを“影実行”してメトリクスだけを記録する PoC。タイムアウト / レート制限 / 形式不正などの**異常系固定セット**も最小実装で再現します。

**EN:** Minimal adapter that keeps the primary response, mirrors the request on a shadow provider for metrics only, and purposefully reproduces timeout / rate limit / malformed-response failures.

> ℹ️ **本ポートフォリオで外部LLM APIを利用するのはこの04プロジェクトのみです。** 01〜03は決定的なスタブ／ルールベース処理で完結し、ネットワークやAPIキーを必要としません。

## Key Features

- **Parallel orchestration modes** — `parallel_any` は最初に成功したプロバイダを返し、`parallel_all` は全結果を収集、`consensus` は複数プロバイダで多数決（閾値／スコア重み）を行う。各モードは `RunnerConfig.consensus` や CLI オプションで切り替え可能。
- **Shadow execution telemetry** — `run_with_shadow` でプライマリを待ちつつ、別スレッドで影プロバイダを実行。レスポンス差分やフィンガープリントを `artifacts/runs-metrics.jsonl` へ `shadow_diff` イベントとして記録。
- **Fallback runner & retries** — `Runner` が `TimeoutError` / `RateLimitError` / `RetriableError` を捕捉し、次候補へ切り替え。`RateLimitError` は 0.05 秒のバックオフを入れて再試行し、`TimeoutError` / `RetriableError` は即座に次プロバイダへ進む。成功時は `provider_success`、失敗時は `provider_error` / `provider_chain_failed` を発火。
- **Deterministic error simulation** — `MockProvider` はプロンプト中の `[TIMEOUT]` / `[RATELIMIT]` / `[INVALID_JSON]` を検知して対応する例外を投げ、異常系をテストから容易に再現。

## Motivation

- 本番の意思決定を変えずに品質・レイテンシ差分を継続測定 → ベンダ選定や回帰検知に活用。
- 異常系を**明示的に再現**できるため、フォールバックや再試行の動作確認が容易。

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
  │   ├─ parallel/
  │   ├─ test_err_cases.py
  │   └─ test_shadow.py
  ├─ demo_shadow.py
  ├─ pyproject.toml
  └─ requirements.txt
```

> ℹ️ 並列ランナーの詳細ケースは `tests/parallel/` 配下に集約しました。旧 `test_runner_parallel.py` シムは削除済みです。`pytest projects/04-llm-adapter-shadow/tests/parallel` で一括実行できます。

## Usage

### Quickstart — 04: LLM Adapter (Shadow/Fallback/Parallel)

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

3. **実行 & メトリクス確認（並列モード含む）**

   ```powershell
   $env:OPENAI_API_KEY = "sk-..."        # 例: どれか1つは成功するプロバイダ
   $env:GEMINI_API_KEY = "..."          # 無しでも OK（Gemini は自動スキップ）
   python demo_shadow.py --mode consensus --consensus-strategy majority
   Get-Content .\artifacts\runs-metrics.jsonl -Last 10
   ```

   1行=1イベントの JSONL が追記されます（`provider_success` / `parallel_vote` / `provider_error` / `provider_skipped` など）。

   - `--mode parallel_any` : 最初の成功レスポンスを採用。`parallel_first_success` イベントが追加。
   - `--mode parallel_all` : 全レスポンスを収集し、`parallel_result` イベントを逐次記録。
   - `--mode consensus` : 指定ストラテジで多数決。後述のメトリクスを `consensus_vote` イベントとして追記。

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
- `OLLAMA_BASE_URL` — Ollama API のベースURL（未指定時は `http://127.0.0.1:11434`。未設定の場合のみ旧名の `OLLAMA_HOST` が利用されます）。
- `GEMINI_API_KEY` — Gemini SDK が参照するAPIキー。未設定の場合、Gemini プロバイダは安全にスキップされます。
- `OPENAI_API_KEY` — OpenAI 公式APIを直接呼び出すプロバイダで利用するAPIキー。Quickstartの例と同様に必ず設定してください。
- `OPENAI_ORGANIZATION` / `OPENAI_BASE_URL` — OpenAI の組織IDやベースURLを上書きしたい場合に指定します（未設定なら公開エンドポイントと同じ挙動）。
- `OPENROUTER_API_KEY` — OpenRouter 経由で Anthropic / OpenAI などを利用する際の API キー。未設定なら OpenRouter プロバイダは自動スキップします。
- `OPENROUTER_BASE_URL` — OpenRouter の API ベース URL。既定値は `https://openrouter.ai/api/v1` で、セルフホストや将来のリージョン分離時のみ変更してください。


プロバイダ文字列は最初のコロンのみを区切り文字として扱うため、`ollama:gemma3n:e2b` のようにモデルIDにコロンを含めても問題ありません。`mock:foo` を指定するとモックプロバイダで簡易動作確認が可能です。

> ⚠️ `ProviderResponse.token_usage` が正式名称です。旧 `response.input_tokens` / `response.output_tokens` は互換プロパティとして残っていますが将来削除予定で、`DeprecationWarning` が出た場合は `response.token_usage.prompt` / `response.token_usage.completion`（合計値は `response.token_usage.total`）へ読み替えてください。メトリクスJSONの `*_token_usage_total` もこの値を参照します。

#### よく使う環境変数例

```bash
export PRIMARY_PROVIDER="gemini:gemini-2.5-flash"
export SHADOW_PROVIDER="ollama:gemma3n:e2b"
export GEMINI_API_KEY="<YOUR_GEMINI_KEY>"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"

# OpenRouter を優先プロバイダにする場合
export PRIMARY_PROVIDER="openrouter:openrouter/anthropic/claude-3.5-sonnet"
export OPENROUTER_API_KEY="<YOUR_OPENROUTER_KEY>"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"

```

ルート直下の `.env.example` をコピーして `.env` を作成すると、上記の雛形をそのまま利用できます。

OpenRouter のモデル指定は `openrouter:<vendor>/<model>` 形式で、OpenRouter 側のモデルリストに合わせて記述します。`OPENROUTER_API_KEY` は公式ダッシュボードで発行し、`.env` やシークレットストアに保管してください。組織のポリシーに従い、監査ログへ API キーを残さないようご注意ください。

OpenRouter 経由で複数ベンダーにアクセスすると、OpenRouter 側のレート制限と個別ベンダーのポリシーが同時に適用されます。`parallel_*` モード利用時は 429 が発生しやすいため、`RunnerConfig.rpm` を調整しつつ `RateLimitError` のリトライ挙動（0.05 秒バックオフ）に依存しすぎない構成にすることを推奨します。

Gemini の構造化出力を利用したい場合は、`generation_config` に
`{"response_mime_type": "application/json"}` や
`{"response_schema": {...}}` を指定すると JSON 固定のレスポンスを要求できます。
`demo_shadow.py` の `request_options` を編集するか、環境変数で
`PRIMARY_OPTIONS` を与えて `ProviderRequest.options` に受け渡してください。Ollama 向けには `REQUEST_TIMEOUT_S`（または小文字の `request_timeout_s`）を指定するとリクエスト単位のタイムアウトを秒数で上書きできます。

### RunnerConfig と CLI オプション対応表

```toml
[runner]
mode = "consensus"              # "fallback" | "parallel_any" | "parallel_all" | "consensus"
max_concurrency = 4              # 同時実行上限（parallel_* / consensus で有効）
rpm = 120                        # 1分あたりの合計呼び出し上限

[runner.consensus]
strategy = "majority_vote"       # "majority_vote" | "max_score" | "weighted_vote"
quorum = 2                       # 採択に必要な最小同意数
tie_breaker = "min_latency"      # "min_latency" | "min_cost" | "stable_order"
schema = "{\"type\":\"object\"}"   # JSON Schema（CLI の --schema はファイル読込）
judge = "pkg.module:call"        # judge 実装（module:callable 形式）
provider_weights = { "mock:fast" = 1.0, "mock:slow" = 0.5 }
max_latency_ms = 2500            # レイテンシ上限（ミリ秒）
max_cost_usd = 0.25              # 推定コスト上限（USD）
```

| RunnerConfig フィールド | CLI オプション | 説明 |
| --- | --- | --- |
| `mode` | `--mode {sequential,parallel-any,parallel-all,consensus}` | **JP:** 実行モードを選択。<br>**EN:** Selects the orchestration mode. |
| `max_concurrency` | `--max-concurrency <int>` | **JP:** 並列呼び出し数の上限。<br>**EN:** Limits concurrent provider calls. |
| `rpm` | `--rpm <int>` | **JP:** 1分あたりの合計呼び出し上限。<br>**EN:** Caps total requests per minute. |
| `metrics_path` | `--metrics <path>` | **JP:** メトリクス出力先を上書き。<br>**EN:** Overrides the metrics sink path. |
| `consensus.strategy` | `--aggregate {majority_vote,max_score,weighted_vote}` | **JP:** 多数決アルゴリズム。<br>**EN:** Consensus aggregation strategy. |
| `consensus.quorum` | `--quorum <int>` | **JP:** 採択に必要な票数。<br>**EN:** Minimum votes required to accept a candidate. |
| `consensus.tie_breaker` | `--tie-breaker {min_latency,min_cost,stable_order}` | **JP:** 票同数時の裁定。<br>**EN:** Tie-breaker policy. |
| `consensus.schema` | `--schema <path>` | **JP:** JSON Schema をファイルから読込み。<br>**EN:** Loads JSON Schema from the given file path. |
| `consensus.judge` | `--judge <module:callable>` | **JP:** 追加判定ロジックを呼び出す。<br>**EN:** Invokes custom judge callable for final arbitration. |
| `consensus.provider_weights` | `--weights provider=weight,...` | **JP:** プロバイダごとの重み付け。<br>**EN:** Applies per-provider weights. |
| `consensus.max_latency_ms` | `--max-latency-ms <int>` | **JP:** レイテンシが閾値を超えた候補を除外。<br>**EN:** Filters out responses exceeding the latency ceiling (ms). |
| `consensus.max_cost_usd` | `--max-cost-usd <float>` | **JP:** 推定コストが上限を超えた候補を除外。<br>**EN:** Drops responses beyond the USD cost guardrail. |

#### CLI オプション補足 / Additional notes

- **JP:** `--schema` は JSON ファイルを読み込み、内容をそのまま `ConsensusConfig.schema` に設定します。`--judge` は `pkg.module:callable` 形式で指定し、タイブレーク後も同票なら審級判定を行います。<br>**EN:** `--schema` reads a JSON document from disk into `ConsensusConfig.schema`, while `--judge` expects a `pkg.module:callable` string that is invoked if a tie persists after tie-breaking.
- **JP:** `--weights` は CSV 形式（例: `provider-a=1.0,provider-b=0.5`）で、指定がないプロバイダは重み 1.0 で扱われます。<br>**EN:** `--weights` accepts CSV values such as `provider-a=1.0,provider-b=0.5`; providers without entries default to weight 1.0.
- **JP:** `--max-latency-ms` と `--max-cost-usd` は制約に違反した候補を除外し、全候補が不合格の場合は `ParallelExecutionError` を送出します。<br>**EN:** `--max-latency-ms` and `--max-cost-usd` drop candidates violating the thresholds and raise `ParallelExecutionError` if none survive.

#### just コマンドによる補助 / Using `just` helpers

- **JP:** `just python-test` — Python テストスイートで CLI と RunnerConfig の整合性を検証します。<br>**EN:** `just python-test` runs the Python suite to verify CLI and RunnerConfig alignment.
- **JP:** `just lint` — CLI 追加オプションを含むモジュールが構文エラーなく読み込めるかを手早く確認します。<br>**EN:** `just lint` performs a quick syntax check to ensure CLI modules import cleanly with the new options.

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

### Consensus Metrics

- `consensus` モードでは、1回の要求につき `consensus_vote` が記録され、以下のフィールドを出力します:
  - `voters_total`, `votes_for`, `votes_against`, `abstained` — 投票の内訳。
  - `strategy`, `min_votes`, `score_threshold`, `tie_breaker` — 実行時の合議設定。
  - `winner_provider`, `winner_score`, `winner_latency_ms` — 採択候補と評価スコア。
  - `tie_break_applied`, `tie_break_reason` — タイブレークを適用した場合の詳細。
  - `candidate_summaries` — プロバイダごとのスコア／投票結果。
- `run_with_shadow` と併用した場合は、合議結果に加えて `shadow_diff.shadow_consensus_delta` が追記され、採択案と影プロバイダとの差分（投票数 / スコア / タイブレーク要因の再評価結果）を記録します。影側で失敗した場合は `shadow_consensus_error` が併記されます。

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

