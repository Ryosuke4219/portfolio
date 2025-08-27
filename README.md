# Portfolio Hub ? Ryosuke4219

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
   仕様からテストを起こし、CIで回すパイプラインの最小例。  
   _Convert plain-text specs into structured test cases, execute automatically via CLI and CI pipeline._

2. **要件定義・受け入れ基準をLLMで拡張 → PlaywrightのE2Eテスト自動生成PoC**  
   LLMを用いてテスト設計を支援、E2Eテスト作成を効率化。  
   _Leverage LLM to expand acceptance criteria and generate Playwright-based E2E tests._

3. **CIログ解析 → 不安定テストの検知・再実行・タグ付け/自動起票**  
   CIの信頼性を高めるため、flaky test を自動処理する仕組み。  
   _Analyze CI logs to detect flaky tests, auto-rerun, tag, or create tickets automatically._

---

## 環境 (Environment)
- Node: v24.6.0 (fnm)  
- Python: 3.11+ (uv)  
- CI: GitHub Actions  

---

## 今後 (Next Steps)
- 各プロジェクトのサンプルコードを追加  
- メトリクスや成果（工数削減、安定化率など）をREADME内に明記  
- 英語READMEやデモ動画を追加予定  

_Add more sample code for each project, include metrics/results (e.g., effort reduction, stability rate), and prepare an English-only README + demo video in the future._  

---
