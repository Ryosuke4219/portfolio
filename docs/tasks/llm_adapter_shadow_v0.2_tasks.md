# 04 LLM Adapter Shadow — v0.2 タスク分解

## Providers

### タスク1: OpenRouter Provider の契約テストを作成
- 背景: Roadmap M3 では OpenAI/Ollama/OpenRouter を同一SPIで扱うことが Exit Criteria。既存テストは OpenAI のみで、OpenRouter 向けの回帰が不足している。【F:04/ROADMAP.md†L12-L34】【F:projects/04-llm-adapter-shadow/tests/providers/test_openai_provider.py†L1-L200】
- 作業: `projects/04-llm-adapter-shadow/tests/providers/test_openrouter_provider.py` を新設し、(1) 429→`RateLimitError`、(2) 5xx→`RetriableError`、(3) ストリーミング指定透過、(4) usage 正規化のテストを OpenAI ケースに倣って用意する。FakeSession/FakeResponse を使ってプロトコル整合性を確認する。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/providers/test_openrouter_provider.py` を実行し、未実装段階で失敗することを確認する。【F:justfile†L29-L34】

### タスク2: OpenRouter Provider 実装を追加
- 背景: OpenRouter API を呼び出すプロバイダ実装が未提供のため、上記テストが失敗する。【F:projects/04-llm-adapter-shadow/src/llm_adapter/providers/openai.py†L1-L200】
- 作業: `projects/04-llm-adapter-shadow/src/llm_adapter/providers/openrouter.py` を新設し、OpenAI 実装をベースに `_requests_compat` 経由で HTTP POST を行う。レスポンスから `text`/`token_usage`/`finish_reason` を正規化し、エラーを RateLimit/Retriable/Timeout にマップする。APIキー・Base URL は環境変数 (`OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL`) から取得できるようにする。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/providers/test_openrouter_provider.py` を緑化し、`ruff check` / `mypy --config-file pyproject.toml` を通過させる。【F:justfile†L29-L34】【F:pyproject.toml†L1-L58】

### タスク3: Provider ファクトリへ OpenRouter を登録
- 背景: Factory のデフォルトマッピングは Gemini/Ollama/Mock のみで OpenRouter が未登録。【F:projects/04-llm-adapter-shadow/src/llm_adapter/providers/factory.py†L44-L96】
- 作業: `projects/04-llm-adapter-shadow/src/llm_adapter/providers/factory.py` に `"openrouter"` プレフィックスを追加し、APIキーを自動注入するコールバックを実装する。`parse_provider_spec` の挙動は維持しつつ、環境変数経由の生成 (`provider_from_environment`) でも OpenRouter が利用できることを確認する。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/providers/test_parse_and_factory.py` を実行して登録漏れがないことを確認する。

### タスク4: Factory テストを OpenRouter 対応に拡張
- 背景: 既存の `test_parse_and_factory.py` には OpenRouter の登録確認がない。【F:projects/04-llm-adapter-shadow/tests/providers/test_parse_and_factory.py†L1-L48】
- 作業: `projects/04-llm-adapter-shadow/tests/providers/test_parse_and_factory.py` に OpenRouter のデフォルト登録を検証するケースを追加し、`provider_from_environment` で `openrouter:gpt-4o-mini` を解決できることを確認する。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/providers/test_parse_and_factory.py` を緑化する。【F:justfile†L29-L34】

## Documentation

### タスク5: README に OpenRouter 設定例を追記
- 背景: Provider configuration 節には Gemini/Ollama のみ記載されており、OpenRouter への導線が欠落している。【F:projects/04-llm-adapter-shadow/README.md†L111-L135】
- 作業: `projects/04-llm-adapter-shadow/README.md` の Provider configuration セクションに OpenRouter の環境変数 (`OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL`) やモデル指定例、API キーの取得手順リンクを追加する。
- 検証: `just lint` の Markdown チェックと `pytest projects/04-llm-adapter-shadow/tests/test_version.py` を実行して差分影響がないことを確認する。【F:justfile†L37-L48】

### タスク6: Roadmap に OpenRouter 対応の参照を追加
- 背景: v0.2 Roadmap はプレースホルダのみで OpenRouter 対応へのリンクがない。【F:docs/spec/v0.2/ROADMAP.md†L1-L5】
- 作業: `docs/spec/v0.2/ROADMAP.md` に OpenRouter Provider 追加タスクへの参照リンクを追記し、進捗把握の導線を整備する。
- 検証: `just lint` を実行してドキュメント検証を通す。【F:justfile†L37-L48】

## CI / Quality

### タスク7: ruff チェックエラーの解消
- 背景: 新規ファイル追加後に `ruff check` を走らせ、スタイル違反が発生した場合に迅速に修正する必要がある。【F:justfile†L37-L48】
- 作業: `ruff check` を実行し、違反が出た箇所に `ruff --fix` もしくは手動修正を適用する。修正は対象ファイル単位で別途タスクに従って行う。
- 検証: `ruff check` が 0 exit code になること。

### タスク8: mypy 型チェックエラーの解消
- 背景: Provider SPI は strict 設定で型検証しており、新規実装での型崩れを防ぐ必要がある。【F:pyproject.toml†L1-L58】
- 作業: `mypy --config-file pyproject.toml` を実行し、検出された型エラーを該当モジュールで修正する。
- 検証: `mypy --config-file pyproject.toml` が成功すること。

### タスク9: pytest スイートのエラー解消
- 背景: Provider 実装に伴い Python テストが失敗する可能性があるため、逐次修正が必要。【F:justfile†L29-L34】
- 作業: `pytest projects/04-llm-adapter-shadow/tests` を実行し、失敗したケースを原因切り分けして修正する。修正内容は該当タスクにて管理する。
- 検証: `pytest projects/04-llm-adapter-shadow/tests` が成功すること。

### タスク10: Node テストとビルドのエラー解消
- 背景: `just node-test` で生成される spec や e2e が Provider 追加の影響を受ける可能性がある。【F:justfile†L20-L36】
- 作業: `just node-test` を実行し、失敗する場合はモックや型定義を更新して整合性を保つ。
- 検証: `just node-test` が成功すること。

## Refactoring

### タスク11: ConsensusCandidate 集約ロジックのモジュール分割
- 背景: `consensus_candidates.py` が候補集約・スコア計算・スキーマ検証・タイブレークまで単一ファイルに集中しており 270 行超で可読性が低い。【F:projects/04-llm-adapter-shadow/src/llm_adapter/consensus_candidates.py†L1-L274】
- 作業: `projects/04-llm-adapter-shadow/src/llm_adapter/consensus_candidates.py` から集約ロジックと検証処理を新モジュールへ分割し、API を維持したまま内部責務を整理する。分割後は単体テストを追加して機能維持を確認する。
- 検証: `pytest projects/04-llm-adapter-shadow/tests/test_runner_consensus.py` と `pytest projects/04-llm-adapter-shadow/tests/consensus/test_tie_breakers.py` を実行し、緑化を確認する。【F:justfile†L29-L34】
