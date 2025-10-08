# 04 LLM Adapter Shadow — v0.2 タスク分解

## Providers

### タスク1: OpenRouter Provider 契約テストを追加する
- 背景: Roadmap の M3 では OpenAI/Ollama/OpenRouter の3系統を同一SPIで扱うことがExit Criteriaだが、進捗レビューでは OpenRouter 連携が未完了と整理されている。【F:04/ROADMAP.md†L12-L34】【F:04/progress-2025-10-04.md†L16-L32】
- 作業: `projects/04-llm-adapter-shadow/tests/providers/test_openrouter_provider.py` を新設し、OpenRouterレスポンス/エラーのモックを使って (1) 429→`RateLimitError`、(2) 5xx→`RetriableError`、(3) ストリーミング指定の透過を検証するテストを追加する。先にテストを赤にし、既存 OpenAI/Gemini のテストスタイルを踏襲する。【F:projects/04-llm-adapter-shadow/tests/providers/test_openai_provider.py†L1-L200】
- 検証: `pytest projects/04-llm-adapter-shadow/tests/providers/test_openrouter_provider.py` を実行し、未実装段階では失敗することを確認する（CI想定の pytest エラー）。【F:justfile†L29-L34】

### タスク2: OpenRouter Provider 実装とファクトリ登録
- 背景: 上記テストが失敗するため、OpenRouter 実装とファクトリ登録で解消する必要がある。【F:04/ROADMAP.md†L12-L34】【F:projects/04-llm-adapter-shadow/src/llm_adapter/providers/factory.py†L51-L69】
- 作業:
  1. `projects/04-llm-adapter-shadow/src/llm_adapter/providers/openrouter.py` を追加し、OpenAI 互換APIに近いレスポンス正規化（`text`抽出・トークン使用量・finish_reason）と `_requests_compat` 経由のHTTP呼び出しを実装する。既存 `OpenAIProvider` の実装パターンを参考にする。【F:projects/04-llm-adapter-shadow/src/llm_adapter/providers/openai.py†L16-L144】
  2. `factory.py` に `"openrouter"` プレフィックスを登録し、環境変数経由の生成でも利用できるようにする。【F:projects/04-llm-adapter-shadow/src/llm_adapter/providers/factory.py†L51-L96】
  3. 必要に応じて `_requests_compat.py` や共通エラーマップへ差分を追加してテストが通るまで実装を進める。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/providers/test_openrouter_provider.py` → `pytest projects/04-llm-adapter-shadow/tests/providers/test_parse_and_factory.py` の順で緑化し、`ruff check` と `mypy --config-file pyproject.toml` で新規ファイルの静的検証を通す。【F:justfile†L29-L34】【F:pyproject.toml†L1-L58】

## Documentation

### タスク3: OpenRouter 利用手順を README に追記
- 背景: README の Provider 設定例では Gemini/Ollama のみ記載されており、OpenRouter への導線が欠落している。【F:projects/04-llm-adapter-shadow/README.md†L111-L139】
- 作業: README の Provider configuration 節に OpenRouter の環境変数・モデル指定例・APIキー設定を追加し、`docs/spec/v0.2/ROADMAP.md` へも参照リンクを追記する。
- 検証: `just lint` の Markdown/Compile チェック、および `pytest projects/04-llm-adapter-shadow/tests/test_version.py` でドキュメント更新によるバージョン逸脱が無いことを確認する。【F:justfile†L37-L48】

## CI/Quality

### タスク4: OpenRouter 追加後の CI コマンドを監視しエラーを解消
- 背景: DoD では ruff/mypy/pytest/node:test を全て緑に保つ必要があるため、新規Provider追加で発生し得る静的解析・Nodeスイートのエラーに対応するタスクを用意する。【F:04/ROADMAP.md†L72-L74】【F:justfile†L20-L58】【F:pyproject.toml†L1-L70】
- 作業:
  1. Provider 実装差分を導入したブランチで `just lint`・`ruff check`・`mypy --config-file pyproject.toml` を順に実行し、警告や型エラーが出れば修正する。
  2. `just node-test` を走らせ、OpenRouter 向けの spec 生成や e2e テストで失敗する箇所があればログを精査し、必要に応じて Node 側のモック/スタブを更新する。
  3. CI ログに新規の失敗種別が現れた場合は、再発防止のガード（テスト or lint 設定）を別途検討する。
- 検証: `just lint` → `just node-test` → `just python-test` をシーケンシャルに実行し、全て成功することを確認する。【F:justfile†L20-L58】

## Refactoring

### タスク5: ConsensusCandidate 集約ロジックのモジュール分割
- 背景: `consensus_candidates.py` は候補集約・スコア計算・スキーマ検証・タイブレークまで単一ファイルに内包しており 270 行超と肥大化している。責務を分割して可読性とテスト性を高めたい。【F:projects/04-llm-adapter-shadow/src/llm_adapter/consensus_candidates.py†L1-L274】
- 作業: 集約ロジック（`CandidateSet`/`_Candidate`）とスキーマ検証 (`validate_consensus_schema`)・タイブレーク (`_apply_tie_breaker`) を別モジュールへ切り出し、既存インポート互換を維持しつつ内部APIを整理する。単体テストを追加して機能維持を確認する。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/test_runner_consensus.py` と `pytest projects/04-llm-adapter-shadow/tests/consensus/test_tie_breakers.py` を中心に全体テストを実行し、分割後も合議ロジックが変わらないことを保証する。【F:justfile†L29-L34】
