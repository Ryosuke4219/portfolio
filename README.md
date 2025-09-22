# Portfolio Hub

[![CI](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ryosuke4219/portfolio/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Ryosuke4219/portfolio/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Ryosuke4219/portfolio/actions/workflows/codeql.yml)
[![Docs](https://github.com/Ryosuke4219/portfolio/actions/workflows/publish-docs.yml/badge.svg?branch=main)](https://github.com/Ryosuke4219/portfolio/actions/workflows/publish-docs.yml)

---

## 30秒サマリ（採用向け）

**何を作ったか**：MarkdownベースのドキュメントとGitHub Actionsを組み合わせ、ポートフォリオの可視化を自動化するハブを構築。CIで実行環境を確認し、CodeQLでセキュリティ検査、GitHub Pagesで常設公開。  
**なぜ価値があるか**：更新フローをGitHub上に集約することで、変更→検証→公開をワンストップで回せる。常に同じパイプラインでレビューでき、Docsが自動配信される。  
**証明スキル**：GitHub Actions設計、CodeQLによる静的解析、GitHub Pages運用、Markdown情報設計。

*Built a Markdown-driven portfolio hub with CI for environment checks, CodeQL security scanning, and GitHub Pages publishing; centralizes update→verify→release loops and showcases GitHub Actions, CodeQL, and documentation design skills.*

---

## プロジェクト一覧（Projects）

1. **docs/ — GitHub Pages向けドキュメントサイト**
   - `docs/index.md` をハブとして、`overview.md`・`specs/`・`design/` に分割した仕様/設計ドキュメントを公開。GitHub Pages ワークフローがこのディレクトリを配信する。
   - 主な操作:
     ```bash
     # ローカルでMarkdownをブラウズ（簡易サーバ）
     python -m http.server 8000 --directory docs
     ```
2. **GitHub Actions: ci.yml — Node環境の健全性チェック**  
   - `actions/setup-node@v4` で Node 24 系を取得し、CI でバージョンを確認。将来追加するテストやLintのベースになる。  
   - 主な操作:
     ```bash
     # ローカルでもCIと同じバージョンを確認
     node -v
     npm -v
     ```
3. **GitHub Actions: codeql.yml — セキュリティスキャン**  
   - JavaScript/TypeScript 向け CodeQL を定期・PR トリガーで実行し、脆弱性の検出を自動化。  
   - 主な操作:
     ```bash
     # GitHub CLIで手動実行（任意）
     gh workflow run codeql.yml --ref main
     ```
4. **GitHub Actions: publish-docs.yml — GitHub Pages デプロイ**  
   - Pages が有効化されている場合に `docs/` をアーティファクトとしてアップロードし、自動デプロイ。無効時はメッセージで通知。  
   - 主な操作:
     ```bash
     # 手動デプロイのトリガー例（任意）
     gh workflow run publish-docs.yml --ref main
     ```

---

## クイックスタート（Quick Start）

- Node 24.x を導入（fnm / nvm などで CI と揃える）。
- `python -m http.server --directory docs` などでドキュメントをプレビュー。
- GitHub Pages を有効化すると、`publish-docs.yml` が自動公開を行う。
- GitHub CLI (`gh`) があれば、CodeQL や Docs デプロイの手動実行も可能。

**Environment**

* Node: v24.x（GitHub Actions と同一） / GitHub CLI: 任意 / CI: GitHub Actions（Linux）([GitHub][1])

---

## このリポジトリの価値（Why it matters）

* **一元管理**：ポートフォリオの更新・公開ループを GitHub 上に集約し、履歴と公開物を同期。
* **自動検証**：CI・CodeQL が毎回同じ環境で検証し、破壊的変更やセキュリティリスクを早期検出。
* **公開の容易さ**：GitHub Pages への自動アップロードで、ドキュメントを常に最新状態で共有。

---

## スキルセット（Skills demonstrated）

* **Automation**：GitHub Actions、ワークフロー分割、条件付きデプロイ。
* **Security**：CodeQL による静的解析導線。
* **Documentation**：Markdown 情報設計、GitHub Pages 公開。
* **Tooling**：Node.js 環境整備、GitHub CLI 運用。

---

## Now / Next

* **Now**

  * GitHub Pages を有効化して `docs/index.md` を公開。
  * README ヒーロースニペット（`README_hero_snippet.md`）をLPやプロフィールに活用。

* **Next**

  * CI にテスト / Lint ステップを追加し、Node プロジェクトを拡充。
  * Docs に週次レポートや成果メトリクスを追加し、自動配信を強化。
  * CodeQL 対応言語や品質メトリクスを広げ、セキュリティと可観測性を強化。

---

## リポジトリ構成（一部）

```
.
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── pull_request_template.md
│   └── workflows/
│       ├── ci.yml
│       ├── codeql.yml
│       └── publish-docs.yml
├── docs/
│   ├── design/
│   │   ├── architecture.md
│   │   ├── ci-cd.md
│   │   ├── data-contracts.md
│   │   └── risks-and-ops.md
│   ├── index.md
│   ├── overview.md
│   └── specs/
│       ├── 01-spec2cases.md
│       ├── 02-ac-to-e2e.md
│       ├── 03-ci-flaky.md
│       └── 04-llm-adapter-shadow.md
├── README.md
└── README_hero_snippet.md
```

> 補足：各ワークフロー／ドキュメントの詳細は README の該当セクションと GitHub Actions 実行ログを参照。([GitHub][1])

[1]: https://github.com/Ryosuke4219/portfolio "GitHub - Ryosuke4219/portfolio"
