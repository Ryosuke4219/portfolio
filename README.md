# Portfolio Hub
_QA / SDET / LLM 成果物をまとめた可視化ポータル_


[![Tests](https://img.shields.io/github/actions/workflow/status/Ryosuke4219/portfolio/ci.yml?branch=main&label=tests)](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml)
[![Lint](https://img.shields.io/github/actions/workflow/status/Ryosuke4219/portfolio/lint.yml?branch=main&label=lint)](https://github.com/Ryosuke4219/portfolio/actions/workflows/lint.yml)
[![CodeQL](https://github.com/Ryosuke4219/portfolio/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Ryosuke4219/portfolio/actions/workflows/codeql.yml)
[![Pages](https://img.shields.io/website?url=https%3A%2F%2Fryosuke4219.github.io%2Fportfolio%2F&label=pages)](https://ryosuke4219.github.io/portfolio/)
[![Coverage](https://img.shields.io/github/actions/workflow/status/Ryosuke4219/portfolio/coverage.yml?branch=main&label=coverage)](https://github.com/Ryosuke4219/portfolio/actions/workflows/coverage.yml)
[![Release](https://img.shields.io/github/v/release/Ryosuke4219/portfolio?display_name=tag&sort=semver)](https://github.com/Ryosuke4219/portfolio/releases)
[![QA Snapshot](https://img.shields.io/badge/QA%20Snapshot-Auto%20weekly-6f42c1?logo=github)](https://ryosuke4219.github.io/portfolio/reports/latest.html)


<!-- qa-metrics:start -->
| 指標 | 値 |
|------|----|
| Pass Rate | 100.00% (126/126) |
| Top Flaky | データなし |
| 最終更新 | 2025-09-23T07:46:06.005000Z |
| レポート | [最新レポートを見る](https://ryosuke4219.github.io/portfolio/reports/latest.html) |

直近3回の差分:
- local_20250923T074605Z_20_20250923074606 (2025-09-23T07:46:06.005000Z): Pass Rate 100.00% (±0.00pp) / Flaky 0件 (±0)
- local_20250923T074604Z_19_20250923074604 (2025-09-23T07:46:04.396000Z): Pass Rate 100.00% (±0.00pp) / Flaky 0件 (±0)
- local_20250923T074602Z_18_20250923074602 (2025-09-23T07:46:02.920000Z): Pass Rate 100.00% (±0.00pp) / Flaky 0件 (±0)

<!-- qa-metrics:end -->
<sub>※週次ワークフロー (`weekly-qa-summary.yml`) が `tools/update_readme_metrics.py` で自動更新します。</sub>


> 🔎 最新CIレポート: [JUnit要約](https://ryosuke4219.github.io/portfolio/reports/junit/index.html) / [Flakyランキング](https://ryosuke4219.github.io/portfolio/reports/flaky/index.html) / [Coverage HTML](https://ryosuke4219.github.io/portfolio/reports/coverage/index.html)

> QA × SDET × LLM の実践ポートフォリオ。小さく完結した自動化パイプラインを公開。 / Practical QA × SDET × LLM portfolio featuring compact automation pipelines.

- **Website:** <https://ryosuke4219.github.io/portfolio/> — Portfolio Gallery on GitHub Pages
- **行動規範:** [Contributor Covenant v2.1](CODE_OF_CONDUCT.md)
- **Docs Deploy:** `.github/workflows/pages.yml` が `docs/` をビルド&公開（追加の Pages ワークフローは不要）
- **Topics:** `qa`, `sdet`, `playwright`, `llm`, `pytest`, `github-actions`, `devcontainers`, `codeql`
- **Quick Start:** `just setup && just test && just report`

### Quick glance (EN)

Hands-on portfolio showcasing QA × SDET × LLM automation pipelines, continuously published via GitHub Pages.

- `just setup` — Initialize Node.js/Python dependencies and Playwright stubs.
- `just test` — Execute combined regression across Node and Python projects.
- `just lint` — Run JavaScript linting and Python bytecode validation.
- `just report` — Generate pytest coverage reports for the Python adapter.
- GitHub Pages: <https://ryosuke4219.github.io/portfolio/>

> [!TIP] Quick Start
> `just setup` — Node.js / Python 依存と Playwright スタブを初期化します。
> `just test` — Node＋Python の回帰テストを一括で実行します。
> `just lint` — JavaScript の構文チェックと Python バイトコード検証を行います。
> `just report` — Python プロジェクトのテスト＋カバレッジレポートを生成します。
>
> ✅ 詳細手順は [ローカルセットアップ (Local onboarding)](#ローカルセットアップ-local-onboarding) を参照してください。

---

## 概要 (Overview)

QA × SDET × LLM を軸にした実践的ポートフォリオで、テスト自動化やLLM活用のPoCを継続的に追加していきます。
GitHub Pages の [Portfolio Gallery](docs/index.md) ではサマリと成果物を常時公開しています。

Practical portfolio focusing on **QA × SDET × LLM**.
New automation pipelines and LLM-driven PoCs are published regularly, with a persistent [Portfolio Gallery](docs/index.md) available via GitHub Pages.

---

## プロジェクト一覧 (Projects)

1. **仕様書テキスト → 構造化テストケース → CLIで自動実行** 【決定的生成】

   * 確定した仕様から**機械的にテストケースを生成**し、CIで回す最小パイプライン。
   * 人手が介在しないため再現性が高く、決定的（deterministic）な結果を得られる。
   * *Convert plain-text specs into structured test cases, execute automatically via CLI and CI pipeline.*

2. **要件定義・受け入れ基準をLLMで拡張 → PlaywrightのE2Eテスト自動生成PoC** 【HITL支援】

   * LLMを使って**受け入れ基準（AC）の補足・拡張を支援**し、E2Eテスト雛形を自動生成。  
   * 要件定義の代替ではなく、人間のレビュー（HITL）を前提とした“効率化PoC”。  
   * *Leverage LLM to expand acceptance criteria and generate Playwright-based E2E tests (HITL-oriented PoC).*

3. **CIログ解析 → 不安定テストの検知・再実行・タグ付け/自動起票**

   * CIの信頼性を高めるため、flaky test を自動処理する仕組み。
   * *Analyze CI logs to detect flaky tests, auto-rerun, tag, or create tickets automatically.*

4. **LLM Adapter — Shadow Execution & Error Handling (Minimal)**

   * プライマリ結果はそのまま採用しつつ、影（shadow）実行で別プロバイダを並走させ、差分メトリクスをJSONLに記録・可視化。
   * *Minimal adapter showcasing shadow execution (metrics-only background run) and deterministic error-case fallbacks.*

### 1. 仕様書テキスト → 構造化テストケース → CLIで自動実行
[詳しい解説はこちら → （Zenn 記事予定地）]()

* `docs/examples/spec2cases/spec.sample.md` のような Markdown からテストケース JSON を生成。

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

→ 詳細: [Spec2Cases CLI README](projects/01-spec2cases/README.md)

### 2. LLM設計 → Playwright E2E テスト自動生成
[詳しい解説はこちら → （Zenn 記事予定地）]()

* `docs/examples/llm2pw/blueprint.sample.json` をもとにテストコードを自動生成。

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
  * `projects/02-llm-to-playwright/tests/README.md` にテスト生成時の**セレクタ・ガード方針**や**ビジュアル／a11y スモーク**の運用メモを記載。`login-cases.json` / `a11y-pages.csv` を編集するだけでデータドリブンにシナリオを増やせる構成とした。

→ 詳細: [LLM → Playwright Pipeline README](projects/02-llm-to-playwright/README.md)

### 3. CI ログ解析と flaky テスト検出
[詳しい解説はこちら → （Zenn 記事予定地）]()

* JUnit XML を解析して履歴 DB (`database.json`) を更新。

  ```bash
  npx flaky parse --input path/to/junit-xml/ --run-id demo_001 --branch main --commit deadbeef
  ```

  * Node.js のみで動作する軽量 XML パーサーを実装し、外部依存なしでレポートを吸収。
  * 直近 5 件の実行から fail→pass を検知すると flaky として表示。
  * 直近で fail→pass したテストを Markdown で出力し、Issue 化に利用。

  ```bash
  npx flaky analyze --config projects/03-ci-flaky/config/flaky.yml
  npm run ci:issue
  ```

  * 失敗率や平均時間、直近 10 実行のタイムラインを含むレポートを生成。
  * 解析結果は `projects/03-ci-flaky/out/`（HTML/CSV/JSON）に出力され、CI 実行時はアーティファクトとして取得できる。

→ 詳細: [Flaky Analyzer CLI README](projects/03-ci-flaky/README.md)

### 4. LLM Adapter — Shadow Execution & Error Handling (Minimal)
[詳しい解説はこちら → （Zenn 記事予定地）]()

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

→ 詳細: [LLM Adapter (Core) README](projects/04-llm-adapter/README.md) / [Shadow Adapter README](projects/04-llm-adapter-shadow/README.md)

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

## リリース (Releases)

- 最新: [v1.0.0 – ポートフォリオ統合リリース](docs/releases/v1.0.0.md) — [GitHub Releases 一覧](https://github.com/Ryosuke4219/portfolio/releases)

### マイルストーン一覧

1. **[v1.0.0 – ポートフォリオ統合リリース](docs/releases/v1.0.0.md)** — 4 本の自動化パイプラインと CI / Pages / Releases の公開フローを整備し、ポートフォリオ全体を横断的に参照できるようにしました。
2. **[v0.3 – flaky検出＋週次サマリ](docs/releases/v0.3.md)** — 週次 QA サマリ（README 自動更新）と CI レポート公開を整備し、Pages／Releases から参照できるようにしました。
3. **[v0.2 – LLMアダプタ（shadow/fallback）最小版](docs/releases/v0.2.md)** — Python 製 LLM アダプタを追加し、shadow 実行とフォールバック検証を pytest / GitHub Actions で自動化しました。
4. **[v0.1 – 初期プロジェクト群](docs/releases/v0.1.md)** — テキスト仕様 → テストケース生成、LLM→Playwright 自動化、CI ログ解析の 3 パイプラインを公開しました。

### リリース運用手順

1. 直近のマイルストーンを `docs/releases/` に追記し、変更点・テスト・関連ドキュメントを整理。
2. 対象コミットに注釈付きタグを作成: `git tag -a vX.Y <commit> -m "vX.Y – サマリ"`
3. `gh release create vX.Y --verify-tag --notes-file docs/releases/vX.Y.md` で GitHub Releases を公開し、README の最新リンクを更新。
4. タグと README 更新を `git push --follow-tags` で共有。


---

## ローカルセットアップ (Local onboarding)

Quick Start で触れた `just` コマンドを詳しく説明します。セットアップの前後関係や内部で呼び出すスクリプトの構成を把握したい場合に参照してください。

1. `just setup` で Node.js / Python 依存と Playwright ブラウザスタブをまとめて初期化します。
   * `.cache/` を共有キャッシュとして利用し、npm と pip のダウンロードを再利用します。
   * `.venv/` に Python 3.11 の仮想環境を自動作成します。
2. `just test` で CI 相当の検証を一括実行できます。
   * Node 側: 仕様ケースの検証 → E2E テスト生成 → デモサーバー起動 → Playwright スタブ実行 → JUnit 解析/レポート生成。
   * Python 側: `projects/04-llm-adapter-shadow` の pytest を実行。
3. `just lint` / `just report` でワンコマンド lint / カバレッジ計測が可能です。

VS Code Dev Container を利用する場合は `devcontainer.json` の postCreateCommand で自動的に `just setup` が走ります。

## 環境 (Environment)

* Node: v24.6.0 (fnm)
* Python: 3.11+ (uv)
* CI: GitHub Actions
* Node.js 標準ライブラリのみで動く CLI を採用。`just setup`（内部で `npm ci` / `pip install` などを実行）は Playwright 実行時のみ必要。

## セットアップ & テスト (Setup & Test)

開発環境は VS Code Dev Containers に対応しています。`devcontainer.json` と `.devcontainer/Dockerfile` を利用することで、Node.js と Playwright 拡張が揃った環境が自動構築されます。

ローカル／Dev Container のいずれでも、以下の 2 コマンドで依存関係の導入からテスト実行まで完結します。

```bash
just setup
just test
```

---

## 今後 (Next Steps)

* 各プロジェクトのサンプルコードを追加
* メトリクスや成果（工数削減、安定化率など）をREADME内に明記
* 英語ツアー動画と GitHub Pages での追加デモを整備

*Add more sample code for each project, include metrics/results (e.g., effort reduction, stability rate), and produce English walkthrough videos plus extra demos on GitHub Pages.*
