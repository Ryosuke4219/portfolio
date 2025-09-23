# Contributing Guide / コントリビューションガイド

このリポジトリは、QA × SDET × LLM の自動化パイプラインを共有するポートフォリオです。開発体験を揃えるため、以下の手順でローカル環境を構築し、PR 提出前チェックを実施してください。

## ローカル環境セットアップ

### 推奨: `just setup`

1. 事前に以下をインストールします。
   - Node.js 24.x（`.node-version` 参照）
   - Python 3.10 以上（推奨 3.11、`pyproject.toml` 参照）
   - [just](https://just.systems) コマンドランナー
2. リポジトリ直下で `just setup` を実行すると、`scripts/bootstrap.sh` / `scripts/bootstrap.ps1` が以下を自動化します。
   - Node.js 依存 (`npm ci`) の取得と Playwright スタブのインストール
   - `.venv/` 仮想環境の作成と Python 依存 (`projects/04-llm-adapter-shadow/requirements.txt`) の導入
3. 初回セットアップ後は `.venv/bin/activate` で仮想環境を有効化しつつ作業できます。

> Dev Container (VS Code) を利用する場合は、開発コンテナ内で `just setup` を実行してください。

### 手動セットアップ (just 未導入の場合)

```bash
npm ci                 # または npm install
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r projects/04-llm-adapter-shadow/requirements.txt
npx --yes playwright install  # 失敗する場合は手動でスキップしても可
```

Windows では `scripts/bootstrap.ps1` を実行すると同等の処理が行われます。

## テスト・レポート実行フロー

| コマンド | 用途 |
| --- | --- |
| `just lint` | JavaScript の構文チェック (`node --check`) と Python バイトコード検証 (`python -m compileall`) |
| `just test` | Node.js (`spec:validate`, `e2e:gen`, `scripts/run-node-suite.sh`, `ci:analyze`, `ci:issue`, `node --test`) と Python (`pytest`) の一括回帰 |
| `just report` | Python プロジェクトのカバレッジ付きレポート (`pytest --cov`) |

開発内容に応じて以下も活用してください。

- Node 側のみ確認したい場合: `npm run spec:validate`, `npm run e2e:gen`, `bash scripts/run-node-suite.sh`
- Python 側のみ確認したい場合: `./.venv/bin/pytest -q projects/04-llm-adapter-shadow/tests`
- レポート生成物の確認: `just report` 実行後に `coverage.xml` やターミナル出力をレビュー

## PR 作成前チェックリスト

PR を開く前に、最低限以下を確認してください。

- [ ] `just lint` を完走して JavaScript / Python の静的チェックを通過した
- [ ] `just test` を完走し、Node / Python の回帰がすべて成功した
- [ ] Python コードを変更した場合は `just report` を実行し、カバレッジ変化を確認した
- [ ] 生成物やレポートを更新した場合は差分をコミットし、必要に応じて `docs/` や README のリンクを更新した
- [ ] 破壊的変更や大きな機能追加は概要・リスク評価を PR テンプレートに明記した

## ブランチ運用・コミット規約

- `main` ブランチは常にデプロイ可能な状態を保つため、直接 push せず PR ベースで更新します。
- 作業ブランチは `feat/<トピック>`・`fix/<トピック>`・`docs/<トピック>` など、用途が分かる命名を推奨します。
- コミットメッセージは [Conventional Commits](https://www.conventionalcommits.org/ja/v1.0.0/) をベースに、`feat`, `fix`, `docs`, `chore`, `test` などの型で簡潔にまとめてください。
- 1 コミット = 1 まとまった変更を意識し、セットアップスクリプトやレポート生成物は別コミットに切り出すとレビューが容易になります。
- Issue やドキュメントを更新した場合は、コミット本文や PR 説明欄で関連リソースへのリンクを明示してください。

---

ご不明点や改善提案があれば Issue / Discussion / PR でお気軽に連絡ください。
