---
layout: default
title: Spec to Cases
description: 仕様書からテストケースを抽出する LLM × スキーマ駆動パイプラインのハイライト
---

# Spec to Cases

仕様書 Markdown を入力として、LLM のドラフトとルールベース整形を組み合わせたテストケース生成パイプラインです。ケースは JSON Schema で検証し、既存のテスト管理や自動化フレームワークへ取り込みやすい構造を維持します。

## Highlights

- LLM が生成したドラフトを post-processing し、`schema.json` に準拠する JSON を保証。
- ステップ・期待値・優先度などテスト設計で必要なフィールドを type-preserving に整形。
- CLI スクリプトで Markdown → JSON の変換をバッチ実行可能。

## Key Artifacts

- [spec.sample.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases/spec.sample.md) — 入力となる仕様書サンプル。
- [cases.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases/cases.sample.json) — 生成されたテストケースの完成形。
- [schema.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases/schema.json) — 出力 JSON のバリデーション用スキーマ。
- [scripts/convert.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases/scripts/convert.py) — 変換 CLI のエントリポイント。

## How to Reproduce

1. `projects/01-spec2cases/` 配下で必要な Python 依存関係（`jsonschema` など）をインストール。
2. `scripts/convert.py --spec spec.sample.md --output cases.sample.json` を実行し、サンプル出力を再生成。
3. 生成物はスキーマで検証され、不一致がある場合は CLI がエラーを返します。

## Next Steps

- LLM プロンプトをカスタマイズして領域別テンプレート（API / UI / 非機能）を切り替え。
- 既存のテスト管理ツールとの API 連携（例: Xray、TestRail）にケース JSON を投入。
- `weekly-summary` での適用ログは [週次サマリ一覧]({{ '/weekly-summary.html' | relative_url }}) を参照。
