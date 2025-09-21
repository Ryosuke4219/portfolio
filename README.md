# Portfolio Hub ?

[![CI](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml)
[![CI](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml/badge.svg)](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml)

---

## 概要 (Overview)

QA × SDET × LLM を軸にした実践的ポートフォリオ。
小さく完結した自動化パイプラインやLLM活用のPoCを公開しています。

Practical portfolio focusing on **QA × SDET × LLM**.
This repository showcases small, complete automation pipelines and PoCs for integrating LLMs into QA/SDET workflows.

---

## プロジェクト一覧 (Projects)

1. **仕様書テキスト → 構造化テストケース → CLIで自動実行**

   * 仕様からテストを起こし、CIで回すパイプラインの最小例。
   * *Convert plain-text specs into structured test cases, execute automatically via CLI and CI pipeline.*

2. **要件定義・受け入れ基準をLLMで拡張 → PlaywrightのE2Eテスト自動生成PoC**

   * LLMを用いてテスト設計を支援、E2Eテスト作成を効率化。
   * *Leverage LLM to expand acceptance criteria and generate Playwright-based E2E tests.*

3. **CIログ解析 → 不安定テストの検知・再実行・タグ付け/自動起票**

   * CIの信頼性を高めるため、flaky test を自動処理する仕組み。
   * *Analyze CI logs to detect flaky tests, auto-rerun, tag, or create tickets automatically.*

4. **LLM Adapter — Shadow Execution & Error Handling (Minimal)**

   * プライマリ結果はそのまま採用しつつ、影（shadow）実行で別プロバイダを並走させ、差分メトリクスをJSONLに記録・可視化。
   * *Minimal adapter showcasing shadow execution (metrics-only background run) and deterministic error-case fallbacks.*

### 1. 仕様書テキスト → 構造化テストケース → CLIで自動実行

* `projects/01-spec2cases/spec.sample.md` のような Markdown からテストケース JSON を生成。

  ```bash
  npm run spec:generate
  # => projects/01-spec2cases/cases.generated.json を出力
  ```
* 内蔵の軽量バリデータで JSON 構造を検証。

  ```bash
  npm run spec:validate -- projects/01-spec2cases/cases.generated.json
  ```
* CLI からテストケースを読み込み、タグや ID でフィルタして擬似実行。

  ```bash
  npm run spec:run -- projects/01-spec2cases/cases.generated.json --tag smoke
  ```

  * `--tag` や `--id` で絞り込めるため、スモークテスト／個別ケースを即座に確認可能。
  * 期待値や手順が欠落している場合は失敗としてサマリに計上し、仕様漏れを検知。

### 2. LLM設計 → Playwright E2E テスト自動生成

* `projects/02-llm-to-playwright/blueprint.sample.json` をもとにテストコードを自動生成。

  ```bash
  npm run e2e:gen
  ```

  * シナリオごとに ID/タイトル・セレクタ・テストデータ・アサーションをチェックし、欠損時は即エラー。
  * `url:`/`text:` 形式のアサーションはそれぞれ `toHaveURL`／`getByText().toBeVisible()` に変換。
* 生成されたテストは `projects/02-llm-to-playwright/tests/generated/` に配置され、同梱の Playwright 互換スタブでシナリオを検証。

  ```bash
  npm test
  ```

  * スタブランナーは静的デモの遷移と文言を解析し、`junit-results.xml` / `test-results/` を生成。
  * CI ではこれらの成果物を `npm run ci:analyze` / `npm run ci:issue` へ渡して履歴管理を行う。

### 3. CI ログ解析と flaky テスト検出

* JUnit XML を解析して履歴 DB (`database.json`) を更新。

  ```bash
  npm run ci:analyze -- projects/03-ci-flaky/demo/junit-run-fail.xml
  npm run ci:analyze -- projects/03-ci-flaky/demo/junit-run-pass.xml
  ```

  * Node.js のみで動作する軽量 XML パーサーを実装し、外部依存なしでレポートを吸収。
  * 直近 5 件の実行から fail→pass を検知すると flaky として表示。
  * 直近で fail→pass したテストを Markdown で出力し、Issue 化に利用。

  ```bash
  npm run ci:issue
  ```

  * 失敗率や平均時間、直近 10 実行のタイムラインを含むレポートを生成。

### 4. LLM Adapter — Shadow Execution & Error Handling (Minimal)

**概要**
プライマリの応答はそのまま返しつつ、同一プロンプトを**別プロバイダで影（shadow）実行**して差分メトリクスを**JSONL**に収集。`TIMEOUT / RATELIMIT / INVALID_JSON` は**障害注入**（モック／ラッパ）で再現し、**フォールバックの連鎖**を最小構成で検証できる。
（要約）プライマリ結果を使いながら裏で並走し、差分を記録して可視化。

**収集メトリクス（Minimal）**

* 差分系：`latency_ms_delta`, `tokens_in_delta`, `tokens_out_delta`, `content_sha256_equal`
* 個別計測：`{primary, shadow}.status|latency_ms|tokens_in|tokens_out|content_sha256`
* フォールバック：`fallback.attempted`, `fallback.chain`, `fallback.final_outcome`
* 追跡：`trace_id`

**使い方**

```bash
cd projects/04-llm-adapter-shadow
python3 -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt

# デモ：影実行と差分メトリクスを記録
python demo_shadow.py
# => artifacts/runs-metrics.jsonl に1行/リクエストで追記
```

**異常系テストとCI**

```bash
pytest -q   # ERR（障害注入）/ SHD（影実行）シナリオ一式
```

* `[TIMEOUT]` / `[RATELIMIT]` / `[INVALID_JSON]` を含むプロンプトで異常系を明示的に再現し、フォールバック挙動を検証。

**記録フォーマット（例）**

```json
{
  "trace_id": "2025-09-21T02:10:33.412Z-7f2c",
  "primary": { "provider": "openrouter:gpt-x", "status": "ok", "latency_ms": 812, "tokens_in": 128, "tokens_out": 236, "content_sha256": "5e1d...a9" },
  "shadow":  { "provider": "ollama:qwen",       "status": "ok", "latency_ms": 1046,"tokens_in": 128, "tokens_out": 230, "content_sha256": "5e1d...a9" },
  "deltas":  { "latency_ms_delta": 234, "tokens_in_delta": 0, "tokens_out_delta": -6, "content_sha256_equal": true },
  "fallback": { "attempted": false, "chain": [], "final_outcome": "ok" }
}
```

**補足**

* “Minimal”の範囲は**観測（差分収集）×影実行×障害注入×単段フォールバック**に限定。
* リトライ／指数バックオフ／多段フォールバック／詳細コスト集計は**将来拡張**として棚上げ。
* 詳細は `projects/04-llm-adapter-shadow/README.md` を参照。

---

## 環境 (Environment)

* Node: v24.6.0 (fnm)
* Python: 3.11+ (uv)
* CI: GitHub Actions
* Node.js 標準ライブラリのみで動く CLI を採用。`npm install` は Playwright 実行時のみ必要。

---

## 今後 (Next Steps)

* 各プロジェクトのサンプルコードを追加
* メトリクスや成果（工数削減、安定化率など）をREADME内に明記
* 英語READMEやデモ動画を追加予定

*Add more sample code for each project, include metrics/results (e.g., effort reduction, stability rate), and prepare an English-only README + demo video in the future.*
