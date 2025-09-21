# Portfolio Hub × Ryosuke4219

[![CI](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml)

---

## 概要 (Overview)
QA × SDET × LLM を軸にした実践的ポートフォリオ。  
小さく完結した自動化パイプラインやLLM活用のPoCを公開しています。  

Practical portfolio focusing on **QA × SDET × LLM**.  
This repository showcases small, complete automation pipelines and PoCs for integrating LLMs into QA/SDET workflows.  

---

## プロジェクト一覧 (Projects)
1. **仕様書テキスト → 構造化テストケース → CLIで自動実行**  
   - 仕様からテストを起こし、CIで回すパイプラインの最小例。  
   - _Convert plain-text specs into structured test cases, execute automatically via CLI and CI pipeline._

2. **要件定義・受け入れ基準をLLMで拡張 → PlaywrightのE2Eテスト自動生成PoC**  
   - LLMを用いてテスト設計を支援、E2Eテスト作成を効率化。  
   - _Leverage LLM to expand acceptance criteria and generate Playwright-based E2E tests._

3. **CIログ解析 → 不安定テストの検知・再実行・タグ付け/自動起票**
   - CIの信頼性を高めるため、flaky test を自動処理する仕組み。
   - _Analyze CI logs to detect flaky tests, auto-rerun, tag, or create tickets automatically._

### 1. 仕様書テキスト → 構造化テストケース → CLIで自動実行

- `projects/01-spec2cases/spec.sample.md` のような Markdown からテストケース JSON を生成。
  ```bash
  npm run spec:generate
  # => projects/01-spec2cases/cases.generated.json を出力
  ```
- 内蔵の軽量バリデータで JSON 構造を検証。
  ```bash
  npm run spec:validate -- projects/01-spec2cases/cases.generated.json
  ```
- CLI からテストケースを読み込み、タグや ID でフィルタして擬似実行。
  ```bash
  npm run spec:run -- projects/01-spec2cases/cases.generated.json --tag smoke
  ```
  - `--tag` や `--id` で絞り込めるため、スモークテスト／個別ケースを即座に確認可能。
  - 期待値や手順が欠落している場合は失敗としてサマリに計上し、仕様漏れを検知。
- パーサーとバリデータは Node.js の `node:test` でユニットテストを用意。
  ```bash
  npm run spec:test
  ```

### 2. LLM設計 → Playwright E2E テスト自動生成

- `projects/02-llm-to-playwright/blueprint.sample.json` をもとにテストコードを自動生成。
  ```bash
  npm run e2e:gen
  ```
  - シナリオごとに ID/タイトル・セレクタ・テストデータ・アサーションをチェックし、欠損時は即エラー。
  - `url:`/`text:` 形式のアサーションはそれぞれ `toHaveURL`／`getByText().toBeVisible()` に変換。
- 生成されたテストは `projects/02-llm-to-playwright/tests/generated/` に配置され、同梱の静的サーバーでデモ UI を起動して実行。
  ```bash
  # 事前に Playwright のブラウザをインストール
  npx playwright install --with-deps
  npm test
  ```
  - `npm test` は Playwright の E2E を実行し、ルート直下に `junit-results.xml` と `test-results/`（スクリーンショット・トレース等）を出力。
  - CI でも同じ手順を踏み、テストが失敗した場合でもこれらの成果物をアーティファクトとして保存。

### 3. CI ログ解析と flaky テスト検出

- JUnit XML を解析して履歴 DB (`database.json`) を更新。
  ```bash
  npm run ci:analyze -- projects/03-ci-flaky/demo/junit-run-fail.xml
  npm run ci:analyze -- projects/03-ci-flaky/demo/junit-run-pass.xml
  ```
  - Node.js のみで動作する軽量 XML パーサーを実装し、外部依存なしでレポートを吸収。
  - 直近 5 件の実行から fail→pass を検知すると flaky として表示。
- Playwright 実行後に `npm run ci:analyze`（引数なし）を実行すると、最新の `junit-results.xml` を基に `database.json` を生成・更新。
- 直近で fail→pass したテストを Markdown で出力し、Issue 化に利用。
  ```bash
  npm run ci:issue
  ```
  - 失敗率や平均時間、直近 10 実行のタイムラインを含むレポートを生成。
  - `database.json` が存在しない場合は自動でスキップするため、CI の後続処理にも安全。

---

## 環境 (Environment)
- Node: v24.6.0 (fnm)
- Python: 3.11+ (uv)
- CI: GitHub Actions
- Node.js 標準ライブラリのみで動く CLI を採用。`npm install` は Playwright 実行時のみ必要。

---

## 今後 (Next Steps)
- 各プロジェクトのサンプルコードを追加  
- メトリクスや成果（工数削減、安定化率など）をREADME内に明記  
- 英語READMEやデモ動画を追加予定  

_Add more sample code for each project, include metrics/results (e.g., effort reduction, stability rate), and prepare an English-only README + demo video in the future._  

---
