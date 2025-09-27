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

### GitHub Pages 公開 / 復旧手順

- 公開 URL: <https://ryosuke4219.github.io/portfolio/>
- 復旧手順:
  1. GitHub Actions → Pages ワークフローを `Run workflow` で再実行し、`Build with Jekyll` と `Deploy to GitHub Pages` の両ステップが `Completed` になったことを実行ログで確認。
  2. ビルド失敗時はローカルで `bundle exec jekyll build --source docs --destination _site` を実行しエラー箇所を修正。
  3. 修正を `main` ブランチへプッシュすると自動でデプロイが再開されます。

---

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

1. **01: spec2cases-md2json — Markdown → JSON（決定的）**  
   LLMを使わず、Markdown仕様を**決定的に**テストケースJSONへ変換します。

2. **02: blueprint-to-playwright — Blueprint → Playwright（決定的）**  
   受け入れ基準の blueprint から、**決定的に** `.spec.ts` を生成しスタブ実行します。

3. **03: ci-flaky-analyzer — JUnit → HTML/CSV（決定的）**  
   CIのJUnitログを取り込み、flaky挙動を集計・可視化します。

4. **04: llm-adapter-shadow — LLMモデル選択/比較（唯一のLLM使用箇所）**
   *primary* と *shadow* の2系統LLMを並走させ、差分・フォールバック・異常系を検証します。

   **最短コマンドと入出力例:**

   ```bash
   llm-adapter --provider adapter/config/providers/openai.yaml \
     --prompts examples/prompts/ja_one_liner.jsonl --out out.jsonl
   ```

   * `examples/prompts/ja_one_liner.jsonl`

     ```jsonl
     {"prompt": "日本語で1行、自己紹介して"}
     ```

   * `out.jsonl`（一例）

     ```jsonl
     {"provider": "openai", "model": "gpt-4o-mini", "latency_ms": 812, "status": "ok", "prompt_sha256": "d16a2c…", "output": "こんにちは、QAエンジニアのRyです。"}
     ```

### LLM使用ポリシー（重要）

- **01 / 02 / 03 は LLM を使用しません（決定的処理）**  
  同じ入力から常に同じ出力が得られます。CI向きです。
- **LLM を使うのは 04 のみ**  
  モデル選択・比較・フォールバック・shadow実行など、確率的要素は **04 に集約**しています。

### 1. 仕様書テキスト → 構造化テストケース → CLIで自動実行

* `docs/examples/spec2cases/spec.sample.md` のような Markdown からテストケース JSON を生成。

  ```bash
  npm run spec:generate
  # => projects/01-spec2cases-md2json/cases.generated.json を出力
  ```
* 内蔵の軽量バリデータで JSON 構造を検証。

  ```bash
  npm run spec:validate -- projects/01-spec2cases-md2json/cases.generated.json
  ```
* CLI からテストケースを読み込み、タグや ID でフィルタして擬似実行。

  ```bash
  npm run spec:run -- projects/01-spec2cases-md2json/cases.generated.json --tag smoke
  ```

  * `--tag` や `--id` で絞り込めるため、スモークテスト／個別ケースを即座に確認可能。
  * 期待値や手順が欠落している場合は失敗としてサマリに計上し、仕様漏れを検知。

→ 詳細: [Spec2Cases CLI README](projects/01-spec2cases-md2json/README.md)

### 2. LLM設計 → Playwright E2E テスト自動生成

* `docs/examples/llm2pw/blueprint.sample.json` をもとにテストコードを自動生成。

  ```bash
  npm run e2e:gen
  ```

  * シナリオごとに ID/タイトル・セレクタ・テストデータ・アサーションをチェックし、欠損時は即エラー。
  * `url:`/`text:` 形式のアサーションはそれぞれ `toHaveURL`／`getByText().toBeVisible()` に変換。
* 生成されたテストは `projects/02-blueprint-to-playwright/tests/generated/` に配置され、同梱の Playwright 互換スタブでシナリオを検証。

  ```bash
  npm test
  ```

  * スタブランナーは静的デモの遷移と文言を解析し、`junit-results.xml` / `test-results/` を生成。
  * CI ではこれらの成果物を `npm run ci:analyze` / `npm run ci:issue` へ渡して履歴管理を行う。
  * `projects/02-blueprint-to-playwright/tests/README.md` にテスト生成時の**セレクタ・ガード方針**や**ビジュアル／a11y スモーク**の運用メモを記載。`login-cases.json` / `a11y-pages.csv` を編集するだけでデータドリブンにシナリオを増やせる構成とした。

→ 詳細: [LLM → Playwright Pipeline README](projects/02-blueprint-to-playwright/README.md)

### 3. CI ログ解析と flaky テスト検出

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

```bash
# LLM Adapter 本体の最短バッチ実行
cat <<'JSONL' > sample.jsonl
{"prompt": "日本語で1行、自己紹介して"}
JSONL

llm-adapter --provider projects/04-llm-adapter/adapter/config/providers/openai.yaml \
  --prompts sample.jsonl --out out.jsonl --format jsonl
```

```jsonl
{"prompt_sha256": "d4b8…", "status": "ok", "latency_ms": 480, "model": "gpt-4o-mini", "output_tokens": 34}
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
4. `pre-commit install` で Git フックを有効化し、初回は `pre-commit run --all-files` で一括検証できます。

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


---

## AI利用に関する開示 / AI Usage Disclosure

### 日本語
本リポジトリのコードおよびドキュメントは、**AI支援**（GitHub Copilot、ChatGPT 等）を用いて作成しています。  
設計・統合・最終判断は作者が行い、**コミット前に人手でレビュー・編集・検証**しています。出力は CI（テスト／Lint／CodeQL 等）で継続的に確認しています。

- **機密・個人情報**は AI ツールに投入していません。
- **ライセンス適合・重複**については可能な範囲で確認しています。
- 外部成果物やプロンプト由来の要素がある場合は、必要に応じて **CREDITS.md／LICENSE** に出所を記載します。
- 必要に応じ、コミット末尾に由来を示すトレーラー（例：`AI-Generated: partial|substantial` / `AI-Tools: copilot, chatgpt`）を付すことがあります.

### English
Code and documents in this repository are created **with AI assistance** (e.g., GitHub Copilot, ChatGPT).  
Design, integration, and final decisions remain the author’s responsibility. **All changes are human-reviewed and validated** prior to commit and continuously checked in CI (tests/lint/CodeQL).

- **No proprietary or personal data** is provided to AI tools.
- **License compliance and duplication** are checked to a reasonable extent.
- Where appropriate, sources are noted in **CREDITS.md / LICENSE**.
- Commit trailers may be used to indicate provenance (e.g., `AI-Generated: partial|substantial`, `AI-Tools: copilot, chatgpt`).
