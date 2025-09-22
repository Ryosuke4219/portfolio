# CI/CD 設計

## ワークフロー（論理）
- **Lint**：Node + Python の Lint を並列実行。
- **Test**：Unit/E2E（スタブ）と pytest を分離実行（キャッシュ有）。
- **Coverage**：HTML を生成し `docs/reports/coverage/` へ配置（Pages 公開）。
- **Deploy Pages**：`docs/` を `upload-pages-artifact` → `deploy-pages`。

### 実行シーケンス（例）
```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
      - run: npm ci && npm run lint
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt && ruff check
  test:
    needs: lint
    strategy:
      matrix:
        suite: ["unit", "e2e-shadow"]
    steps:
      - uses: actions/checkout@v4
      - run: just test-${{ matrix.suite }}
  coverage:
    needs: test
    steps:
      - uses: actions/checkout@v4
      - run: just coverage-html
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-html
          path: docs/reports/coverage
  publish-docs:
    needs: [coverage]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: docs
      - uses: actions/deploy-pages@v4
```

### ローカル連携
- `just lint` → Node/Python 両 lint を実行。
- `just test-unit` / `just test-e2e-shadow` → CI と同じコマンドで確認。
- `just coverage-html` → ローカルで HTML を生成し `python -m http.server --directory docs` で確認。

## ブランチ/PR 方針
- `main` 保護、PR 必須、**マージ後 head ブランチ自動削除**。
- PR の最低要件：Lint/Test/Coverage の緑化、生成物変更は差分確認。

### レビュー観点
- 仕様変更を伴う場合、`docs/specs/` の差分が揃っているか。
- LLM プロンプトの変更は `prompts/` 配下でレビューし、再現条件を PR 説明に記載。
- flaky レポートの更新がある場合、解析結果を ISSUE または PR コメントで共有。

## 品質ゲート（目安）
- 変更行の**新規カバレッジ 60%+**（PoC 段階）。
- flaky 率が一定閾値超過で E2E の自動再実行を提案（手動承認）。

### 拡張アイデア
- `quality-gate.yml` を追加し、カバレッジやフレーク率の閾値をチェックするスクリプトを組み込む。
- LLM Adapter のメトリクスを nightly で集計し、Pages 上に最新グラフを生成。
- CI 完了後に `gh` CLI を使って Slack / Teams への通知をオプション化。

## セキュリティ
- CodeQL（既定セットアップ）。
- Pages の `pages:write` / `id-token:write` のみ付与。

### シークレット管理
- `.github/workflows/` 配下では OpenAI / Anthropic 等の API キーを直接扱わず、`LLM_API_KEY` など抽象名で保管。
- セルフホスト Runner を導入しない限りは GitHub が提供する OIDC のみ使用。外部送信は避ける。
- Dependabot Alerts を有効化し、LLM 依存ライブラリの CVE を早期検知。
