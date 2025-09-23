# Changelog

本プロジェクトの更新履歴は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に基づいて管理します。バージョン番号は [Semantic Versioning](https://semver.org/lang/ja/) に準拠します。

## [Unreleased]

### Added
- 次期リリースに向けた変更をここに追記します。

### Changed
- 変更予定があればここに追記します。

### Fixed
- 修正予定があればここに追記します。

## [v0.1] - 2025-09-23

### Added
- 仕様書テキストから JSON テストケースを生成・検証・実行する `projects/01-spec2cases` パイプラインを整備。
- LLM を活用して受け入れ基準を拡張し Playwright テストを自動生成する `projects/02-llm-to-playwright` PoC を追加。
- JUnit XML を解析して flaky テストを検出・可視化する `projects/03-ci-flaky` ツール群を実装。
- LLM 影実行とフォールバック挙動を記録する `projects/04-llm-adapter-shadow` のミニマル実装を公開。

### Docs
- GitHub Pages を利用した Portfolio Gallery とレポート公開フローを README に整理。
