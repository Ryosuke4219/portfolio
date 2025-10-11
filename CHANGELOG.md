# Changelog

本プロジェクトの更新履歴は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に基づいて管理します。バージョン番号は [Semantic Versioning](https://semver.org/lang/ja/) に準拠します。

## [Unreleased]

### Added
- 次期リリースに向けた変更をここに追記します。

### Changed
- 変更予定があればここに追記します。

### Fixed
- 修正予定があればここに追記します。

## [v0.1.0] - 2025-10-02

### Added
- `projects/04-llm-adapter` に CLI コマンド群と `just` レシピを統合し、推論プロバイダの並列実行を本番運用フローへ組み込み。
- 影実行のメトリクス収集と週次サマリ生成を自動化し、監視・改善サイクルをドキュメント化。
- CLI/just/週次サマリの成果物を M6 リリース向けに再編し、`v0.1.0` として公開。

### Migration
- 旧 `projects/04-llm-adapter-shadow` のスクリプト群を `projects/04-llm-adapter` へ統合し、移行手順と影響範囲をドキュメント化。

## [v1.0.0] - 2025-09-23

### Highlights
- **Demo 01 – Spec to Cases**
  - Markdown 仕様書から JSON テストケースを生成し、スキーマ検証と type-preserving 変換で品質を担保する CLI を整備。
  - スモールスタート向けにサンプル spec / cases と検証・実行スクリプトを同梱し、即座にパイプラインを再現可能に。
- **Demo 02 – LLM to Playwright**
  - LLM が受け入れ基準を補完した Blueprint から Playwright テストを自動生成し、data-testid ベースの堅牢なセレクタ戦略を実装。
  - CSV/JSON ドライバによるデータ駆動テストと a11y スキャンを統合し、スタブランナーで決定的な E2E 実行を再現。
- **Demo 03 – CI Flaky Analyzer**
  - JUnit XML をストリーミング解析して履歴 JSONL を構築し、HTML・CSV・JSON のマルチフォーマットレポートを一括生成。
  - GitHub Issue テンプレートと週次サマリを自動出力し、CI での flaky 検知と追跡をワンコマンド化。
- **Demo 04 – LLM Adapter — Shadow Execution**
  - プライマリ応答と並走する影プロバイダの差分をメトリクス収集し、JSONL に蓄積するシャドー実行アダプタを実装。
  - タイムアウト／レート制限／形式不正などの障害注入とフォールバック鎖をモックで再現し、pytest で検証。

## [v0.1] - 2025-09-23

### Added
- 仕様書テキストから JSON テストケースを生成・検証・実行する `projects/01-spec2cases-md2json` パイプラインを整備。
- LLM を活用して受け入れ基準を拡張し Playwright テストを自動生成する `projects/02-blueprint-to-playwright` PoC を追加。
- JUnit XML を解析して flaky テストを検出・可視化する `projects/03-ci-flaky` ツール群を実装。
- LLM 影実行とフォールバック挙動を記録するアダプタのミニマル実装を公開。

### Docs
- GitHub Pages を利用した Portfolio Gallery とレポート公開フローを README に整理。
