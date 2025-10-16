# LLM Adapter (Core) — v0.2 タスク分解

> 2025-11-09 更新: v0.1.0 リリースチェックリストと OpenRouter 運用ガイドを追加し、M6 Exit Criteria を満たした。以降は v0.2 タスクとして保守・拡張を継続する。

## 未完了タスク一覧
- （なし）

## CLI / 入力整備

### タスク1: `--prompt-file` / `--prompts` のCRLF・BOM対応を強化する（対応済み）
- 対応状況: `collect_prompts` は `prompt_file` を UTF-8 で読み込み、末尾の `\r\n` を除去してからプロンプト一覧に追加する。`read_jsonl_prompts` も BOM 付き JSONL 行を `lstrip("\ufeff")` で正規化してから `json.loads` を実行し、辞書・文字列のどちらも既存キー順で解決している。【F:projects/04-llm-adapter/adapter/cli/prompt_io.py†L18-L71】
- 品質エビデンス: `projects/04-llm-adapter/tests/test_cli_prompt_io.py` が CRLF 付きテキストと BOM 付き JSONL の双方を読み込めることを回帰テストとして検証済み。【F:projects/04-llm-adapter/tests/test_cli_prompt_io.py†L1-L21】

### タスク17: CLI 単発プロンプトテスト分割チェックリスト（完了）
  - [x] `test_help.py` に CLI ヘルプのスモークテストを配置し、分割後もエントリポイントの使用方法を即時検証できるようにした。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_help.py†L1-L13】
  - [x] `test_metadata.py` にメタデータ伝播テストを移設し、単発プロンプト実行時に `ProviderRequest.metadata` が保持されることを保証する。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_metadata.py†L4-L46】
  - [x] `test_model_override.py` に `--model` 上書きテストを集約し、`cli` コマンドと `prompts` モジュールの双方でモデル指定が反映されることを検証する。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_model_override.py†L4-L51】
  - [x] `test_provider_options.py` にプロバイダオプションと型変換テストを集約し、単発/複数プロンプト双方で `ProviderRequest.options` が整合することを確認する。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_provider_options.py†L4-L81】
  - [x] CLI エラーと資格情報・OpenRouter 経路は `test_provider_errors.py`・`test_credentials.py`・`test_openrouter_flow.py` に分散し、旧 `test_cli_single_prompt.py` を削除したうえで `tests/cli_single_prompt/` 配下のみで回帰できる構成へ更新した。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py†L1-L126】【F:projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py†L81-L139】【F:projects/04-llm-adapter/tests/cli_single_prompt/test_openrouter_flow.py†L74-L107】

## Datasets / ゴールデン検証

### タスク2: `load_golden_tasks` を UTF-8 BOM と行番号付きエラーへ対応させる（対応済み）
- 対応状況: JSONL の読み込みは `encoding="utf-8-sig"` で BOM を吸収しつつ行単位で `strip()` を行い、`json.loads` 失敗時は `invalid JSON at {path}:{index}` 形式の `ValueError` で行番号を明示するようにした。【F:projects/04-llm-adapter/adapter/core/datasets.py†L33-L58】
- 品質エビデンス: `projects/04-llm-adapter/tests/test_datasets_loader.py` が BOM 混在ファイルの正常ロードと、壊れた行での行番号付きエラーを検証している。【F:projects/04-llm-adapter/tests/test_datasets_loader.py†L1-L32】

## Metrics / 決定性ガード

### タスク3: 決定性ゲート失敗時のエラーメッセージを記録する（対応済み）
- 対応状況: 決定性ゲートは diff rate/長さの統計を計算し、閾値超過時に警告ログへ出力するとともに `median_diff` と `len_stdev` を含む文字列を既存の `error_message` に追記している。【F:projects/04-llm-adapter/adapter/core/compare_runner_finalizer.py†L29-L76】
- 品質エビデンス: `projects/04-llm-adapter/tests/test_compare_runner_finalizer.py` で、既存メッセージが保持されたまま統計情報が追記されることを検証済み。【F:projects/04-llm-adapter/tests/test_compare_runner_finalizer.py†L1-L63】

## CI / 品質維持

### タスク4: v0.2 ブランチの CI エラー種に即応する運用タスク
- 背景: v0.2 でも `ruff`/`mypy`/`pytest` を厳格に維持する必要があるため、失敗種別ごとの調査・修正タスクを常設する。【F:pyproject.toml†L1-L58】
- 手順:
  1. CI が赤くなった場合は該当ログを分類し、静的解析は CI と同じく `ruff check .` と `mypy --config-file pyproject.toml projects/04-llm-adapter-shadow/src` を明示的に実行し、続いて `pytest projects/04-llm-adapter/tests`（Python コア）でローカル再現する。JavaScript 側の Lint が失敗した場合は `npm run lint:js`、Python バイトコード検証が必要なケースは `python -m compileall` を追加で走らせ、CI 手順との差異が出ないようログの差分を確認する。
  2. 失敗原因が新規ケースの場合は再発防止のテスト or Lint ルール追加を別チケット化し、本タスクで暫定修正を行う。
  3. 緑化確認後は CI リンクと修正概要を記録し、既存タスクが解消された場合はクローズする。

## Refactoring

### タスク5: `runner_execution.py` を責務単位で分割し可読性を向上させる（完了）
- 進捗: RunnerExecution 本体を 6 モジュールへ再構成し、プロバイダ呼び出し・再試行・並列実行・メトリクス確定・シャドウ連携を専用モジュールで管理する構成に移行した。【F:projects/04-llm-adapter/adapter/core/runner_execution.py†L1-L170】【F:projects/04-llm-adapter/adapter/core/runner_execution_call.py†L1-L69】【F:projects/04-llm-adapter/adapter/core/runner_execution_metrics.py†L1-L85】【F:projects/04-llm-adapter/adapter/core/runner_execution_attempts.py†L1-L71】【F:projects/04-llm-adapter/adapter/core/runner_execution_parallel.py†L1-L90】【F:projects/04-llm-adapter/adapter/core/runner_execution_shadow.py†L1-L94】
- 品質エビデンス: 直列/並列の双方で `RunnerExecution` 公開 API を通じた既存テストが緑を維持し、再試行処理と影実行メトリクスを個別に検証している（再試行: `pytest projects/04-llm-adapter/tests/runner_retry/test_runner_execution_retries.py`、影付き並列: `pytest projects/04-llm-adapter/tests/parallel/test_runner_execution_parallel_metrics.py`）。【F:projects/04-llm-adapter/tests/runner_retry/test_runner_execution_retries.py†L1-L150】【F:projects/04-llm-adapter/tests/parallel/test_runner_execution_parallel_metrics.py†L1-L166】

## Providers

### タスク6: Ollama プロバイダを v0.2 コアへ移植する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/ollama.py`
  - `projects/04-llm-adapter/adapter/core/providers/ollama_connection.py`
  - `projects/04-llm-adapter/adapter/core/providers/ollama_runtime.py`
  - `projects/04-llm-adapter/adapter/core/providers/__init__.py`
  - `projects/04-llm-adapter/tests/providers/ollama/test_success.py`
    【F:projects/04-llm-adapter/tests/providers/ollama/test_success.py†L1-L100】
  - `projects/04-llm-adapter/tests/providers/ollama/test_streaming.py`
    【F:projects/04-llm-adapter/tests/providers/ollama/test_streaming.py†L1-L57】
  - `projects/04-llm-adapter/tests/providers/ollama/test_retriable_errors.py`
    【F:projects/04-llm-adapter/tests/providers/ollama/test_retriable_errors.py†L1-L98】
- 対応状況:
  - `OllamaProvider` は `OllamaConnectionHelper.from_config` で `OllamaClient` と接続パラメータを取得し、インスタンス内に接続情報と準備済みモデル集合を保持しながら、ネットワーク許可判定・モデル準備・ペイロード組み立て・チャット呼び出し・応答正規化を `OllamaRuntimeHelper` へ委譲する薄いオーケストレータとして機能する。【F:projects/04-llm-adapter/adapter/core/providers/ollama.py†L19-L58】【F:projects/04-llm-adapter/adapter/core/providers/ollama_runtime.py†L21-L205】
  - `OllamaConnectionHelper` がホスト/タイムアウト/オフライン制御を環境変数・設定から正規化し、クライアント生成やオート Pull 設定を一元管理する構成である。【F:projects/04-llm-adapter/adapter/core/providers/ollama_connection.py†L36-L135】
  - `OllamaRuntimeHelper` がネットワークアクセス確認、モデル Pull と存在チェック、チャット API へのペイロード組み立て・送信、レスポンス/トークン使用量の正規化、ストリーミング応答の集約まで担当する。【F:projects/04-llm-adapter/adapter/core/providers/ollama_runtime.py†L21-L254】
  - CLI からリテラル指定した API キーを `ProviderRequest.options["api_key"]` に格納し、Ollama へも伝播できるよう CLI パイプラインを整備した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L107】【F:projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py†L81-L115】
- 品質エビデンス:
- ✅ Ollama 品質エビデンス: `pytest projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py::test_cli_literal_api_key_option` が成功し、CLI が受け取ったリテラル API キーを `ProviderRequest.options["api_key"]` へ載せ替えてから Ollama に渡す経路を検証している。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py†L81-L115】
- ✅ 成功/ストリーミング/429・5xx 検証テスト: `projects/04-llm-adapter/tests/providers/ollama/test_success.py`・`test_streaming.py`・`test_retriable_errors.py` が `ProviderResponse` 正規化とリトライ戦略を担保している。【F:projects/04-llm-adapter/tests/providers/ollama/test_success.py†L55-L99】【F:projects/04-llm-adapter/tests/providers/ollama/test_streaming.py†L9-L57】【F:projects/04-llm-adapter/tests/providers/ollama/test_retriable_errors.py†L11-L98】

#### Ollama テスト分割チェックリスト
- [x] 成功系テストを `projects/04-llm-adapter/tests/providers/ollama/test_success.py` へ移行する。
- [x] ストリーミング系テストを `projects/04-llm-adapter/tests/providers/ollama/test_streaming.py` へ移行する。
- [x] 429/5xx・自動 Pull 異常系テストを `projects/04-llm-adapter/tests/providers/ollama/test_retriable_errors.py` へ移行する。
- [x] 旧 `projects/04-llm-adapter/tests/providers/test_ollama_provider.py` のブリッジを削除し、新ディレクトリのみで運用する（成功/スキップ回帰は `test_ollama_provider_executor_success_cases` へ移設済み）。
- 完了状況: Ollama 関連テストは `projects/04-llm-adapter/tests/providers/ollama/` 配下へ集約し、旧ブリッジを削除した上で `pytest projects/04-llm-adapter/tests/providers/ollama` のみで回帰を担保する構成へ移行した。【F:projects/04-llm-adapter/tests/providers/ollama/test_success.py†L1-L100】【F:projects/04-llm-adapter/tests/providers/ollama/test_streaming.py†L1-L57】【F:projects/04-llm-adapter/tests/providers/ollama/test_retriable_errors.py†L1-L98】
- 検証証跡: `pytest projects/04-llm-adapter/tests/providers/ollama` が成功し、成功・ストリーミング・再試行の各テストが単独で通過することを確認した。

### タスク7: OpenRouter プロバイダを v0.2 コアに統合する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/openrouter.py`
  - `projects/04-llm-adapter/adapter/core/providers/__init__.py`
  - `projects/04-llm-adapter/tests/providers/openrouter/test_auth_api_key_resolution.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_api_key_resolution.py†L1-L132】
  - `projects/04-llm-adapter/tests/providers/openrouter/test_auth_request_options.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_request_options.py†L1-L91】
  - `projects/04-llm-adapter/tests/providers/openrouter/test_auth_skip_behavior.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_skip_behavior.py†L1-L81】
  - `projects/04-llm-adapter/tests/providers/openrouter/test_base_url.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_base_url.py†L1-L261】
  - `projects/04-llm-adapter/tests/providers/openrouter/test_options.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_options.py†L1-L110】
  - `projects/04-llm-adapter/tests/providers/openrouter/test_streaming.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_streaming.py†L1-L62】
  - `projects/04-llm-adapter/tests/providers/openrouter/test_errors.py`
    【F:projects/04-llm-adapter/tests/providers/openrouter/test_errors.py†L1-L157】
- 対応状況:
  - `OpenRouterProvider` が API キーの優先順位（環境変数マッピング→リテラル→フォールバック）とベース URL 解決を統合し、セッションの Authorization ヘッダを初期化して Shadow 依存なしでコア提供する構成へ移行した。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L200-L316】
  - `_build_payload` が `ProviderRequest` のオプション優先順位を HTTP ペイロードへ織り込み、`stream`/`request_timeout_s` などの上書きを一箇所で解決する経路を整備した。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L327-L352】
  - `invoke` がストリーミング要求を `_consume_stream` と協調させ、HTTP 応答チャンクをテキスト・使用量・終了理由へ集約したうえで `ProviderResponse` を生成する。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L354-L444】【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L446-L506】
  - CLI からのリテラル API キー指定や設定ファイルの `api_key`/`env` を `ProviderRequest.options["api_key"]` へ結線し、OpenRouter でも CLI からの入力が確実に伝播する完了経路として整理した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L107】【F:projects/04-llm-adapter/tests/cli_single_prompt/test_openrouter_flow.py†L74-L107】
  - OpenRouter 運用ドキュメントを `projects/04-llm-adapter/README.md` と `docs/releases/v0.1.0.md` に同期し、`python -m tools.report.metrics.openrouter_stats --metrics artifacts/runs-metrics.jsonl --out artifacts/openrouter --since ...`（`just openrouter-stats -- --since ...` 経由でも同等）と `llm-adapter-openrouter-probe` の手順を最新化した。【F:projects/04-llm-adapter/README.md†L198-L206】【F:docs/releases/v0.1.0.md†L1-L23】
- 品質エビデンス:
  - ✅ 認証経路: `test_auth_api_key_resolution.py`・`test_auth_request_options.py`・`test_auth_skip_behavior.py` が環境変数マッピング優先度、リクエストオプション経由の API キー上書き、欠落時の `ProviderSkip` を個別に検証する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_api_key_resolution.py†L18-L132】【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_request_options.py†L19-L91】【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_skip_behavior.py†L19-L81】
  - ✅ オプション/ストリーム/エラー: `test_options.py` が構成値とリクエスト値の優先順位を比較し、`test_streaming.py` がチャンク統合と使用量集計を確認し、`test_errors.py` が 401/403/429/503 を正規化してリトライ判定を保証する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_options.py†L20-L110】【F:projects/04-llm-adapter/tests/providers/openrouter/test_streaming.py†L19-L62】【F:projects/04-llm-adapter/tests/providers/openrouter/test_errors.py†L20-L157】
- ✅ OpenRouter 品質エビデンス: `pytest projects/04-llm-adapter/tests/cli_single_prompt/test_openrouter_flow.py::test_cli_openrouter_accepts_provider_option_api_key` を含む CLI テスト群で、OpenRouter 向けのリテラル API キーが `ProviderRequest.options` で秘匿されたまま CLI からプロバイダへ伝播することを確認済み。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_openrouter_flow.py†L74-L107】
#### 継続課題（Providers）
- 実サーバーでのストリーミング透過性検証と運用フロー整備（タスク13を参照）。
- OpenRouter 429/5xx 発生状況の集計とドキュメント拡充（タスク14を参照）。

#### OpenRouter テスト分割チェックリスト
- [x] 認証系テストを `projects/04-llm-adapter/tests/providers/openrouter/test_auth_api_key_resolution.py`・`test_auth_request_options.py`・`test_auth_skip_behavior.py` へ分割し、環境変数マッピング／CLI オプション優先／API キー欠落時の `ProviderSkip` をそれぞれ検証する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_api_key_resolution.py†L18-L132】【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_request_options.py†L19-L91】【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_skip_behavior.py†L19-L81】
- [x] ベース URL／セッション関連テストを `projects/04-llm-adapter/tests/providers/openrouter/test_base_url.py` へ移設し、`router_base_url` のフォールバックとセッションヘッダ初期化を回帰する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_base_url.py†L1-L261】
- [x] オプション優先順位テストを `projects/04-llm-adapter/tests/providers/openrouter/test_options.py` へ移設し、`ProviderRequest.options` の `api_key` 上書きと `stream` 指定が HTTP ペイロードへ反映されることを確認する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_options.py†L1-L110】
- [x] ストリーミングと使用量集計テストを `projects/04-llm-adapter/tests/providers/openrouter/test_streaming.py` へ移設し、チャンク統合とトークン使用量の合算を保持する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_streaming.py†L1-L62】
- [x] エラー正規化テストを `projects/04-llm-adapter/tests/providers/openrouter/test_errors.py` へ移設し、429/503/401/403 正規化と再試行判定を分割後も継続監視する。【F:projects/04-llm-adapter/tests/providers/openrouter/test_errors.py†L1-L157】
- 完了状況: OpenRouter 関連テストは `projects/04-llm-adapter/tests/providers/openrouter/` 配下で完結し、旧ブリッジを削除済み。API キー透過・ベース URL・オプション優先順位・ストリーミング・エラー正規化の各検証を新ディレクトリ内のテストだけで維持している。【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_api_key_resolution.py†L18-L132】【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_request_options.py†L19-L91】【F:projects/04-llm-adapter/tests/providers/openrouter/test_auth_skip_behavior.py†L19-L81】【F:projects/04-llm-adapter/tests/providers/openrouter/test_base_url.py†L1-L261】【F:projects/04-llm-adapter/tests/providers/openrouter/test_options.py†L20-L110】【F:projects/04-llm-adapter/tests/providers/openrouter/test_streaming.py†L19-L62】【F:projects/04-llm-adapter/tests/providers/openrouter/test_errors.py†L20-L157】
- 検証証跡: `pytest projects/04-llm-adapter/tests/providers/openrouter` が成功し、旧ブリッジなしで OpenRouter 専用テストが緑化することを確認した。

### タスク12: OpenAI プロバイダのリクエストオプションを v0.2 コアへ拡張する（対応済み）
- 主要モジュール:
  - `OpenAIProvider` が `build_mode_strategies` で得たモード別ロジックへ接続情報やシステムプロンプトを引き渡し、委譲先のストラテジー呼び出しを制御する薄いオーケストレータへ再構成した。【F:projects/04-llm-adapter/adapter/core/providers/openai.py†L53-L140】
  - `openai_helpers.py` が API キー解決・共通キーワード引き回し・モードストラテジー生成・例外正規化を担い、各ストラテジー内部で `ProviderRequest` のオプション/制御値を最終ペイロードへ組み込む。【F:projects/04-llm-adapter/adapter/core/providers/openai_helpers.py†L27-L204】
  - `openai_extractors.py` がレスポンスからの本文抽出・トークン使用量集計・生データ化を一元化し、`OpenAIProvider` の戻り値構築に利用している。【F:projects/04-llm-adapter/adapter/core/providers/openai_extractors.py†L21-L184】
- 検証テスト: `test_openai_provider_applies_request_overrides` が CLI から渡されるオプションを通じて `stream`/`seed`/`response_format` が SDK 呼び出しへ渡ること、ストリーム結果が `ProviderResponse` に正規化されることを確認する。【F:projects/04-llm-adapter/tests/providers/test_openai_provider_request_overrides.py†L1-L158】

### タスク13: OpenRouter ストリーミング実サーバー検証を運用へ組み込む（対応済み）
- 対応状況: OpenRouter のストリーミングログをプローブする CLI を `projects/04-llm-adapter/tools/openrouter/stream_probe.py` に集約し、`llm-adapter-openrouter-probe` と `just openrouter-stream-probe` が同一エントリポイントを共有する構成へ統一した。【F:projects/04-llm-adapter/tools/openrouter/stream_probe.py†L1-L105】【F:projects/04-llm-adapter/pyproject.toml†L25-L28】【F:justfile†L91-L95】
- 品質エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py` が成功し、OpenRouter 前提のストリーミングイベントが `ProviderResponse` へ透過することを確認している。【F:projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py†L1-L120】

### タスク14: OpenRouter ドキュメントと 429/5xx ガードを拡充する（対応済み）
- 対応状況: `projects/04-llm-adapter/tools/report/metrics/openrouter_stats.py` をエントリポイントに据え、`python -m tools.report.metrics.openrouter_stats --metrics <runs-metrics.jsonl> --out <出力ディレクトリ> [--since <ISO日時>]`（`just openrouter-stats` 経由では `--metrics artifacts/runs-metrics.jsonl --out artifacts/openrouter` を既定で付与）で 429/5xx を集計する運用を整備。`--out` で指定したディレクトリに `openrouter_http_failures.json` と `openrouter_http_failures.jsonl` を生成し、API キー/ベース URL の伝播手順と集計の運用フローを README・CLI ガイドおよび本タスクに反映した。【F:projects/04-llm-adapter/tools/report/metrics/openrouter_stats.py†L1-L55】
- 成果/エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py` で 429/5xx の正規化と週次スライスが検証されている。【F:projects/04-llm-adapter/tests/tools/test_openrouter_stats_cli.py†L1-L52】
  - ✅ `pytest projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py` でストリーミングプローブとメトリクス収集の互換性を担保している。【F:projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py†L1-L120】
- ✅ `python -m tools.report.metrics.openrouter_stats --metrics artifacts/runs-metrics.jsonl --out artifacts/openrouter --since 2025-10-01`（`just openrouter-stats -- --since 2025-10-01` 相当）の実行手順と CI スケジュールを本タスクへ記録し、`--out` で指定した `artifacts/openrouter/` に最新集計を生成する運用ログを共有している。【F:justfile†L96-L99】

## CLI Request Pipeline

### タスク8: CLI から `ProviderRequest` への移行を完了する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/app.py`
  - `projects/04-llm-adapter/adapter/cli/prompt_runner.py`
  - `projects/04-llm-adapter/adapter/core/_provider_execution.py`
- 対応状況:
  - `_process_prompt` が RateLimiter とセマフォの許可を待ちながら `_build_request` で `ProviderRequest` を構築し、`provider.invoke` を同期 API として `run_in_executor` で実行するため、CLI で束ねたプロンプト・オプション・メタデータがそのままプロバイダへ届く。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L90-L174】
  - `prompt_runner.execute_prompts` は並列タスクを生成して `asyncio.gather` で収集し、`PromptResult.index` で整列して呼び出し元へ返すため、CLI の入力順を維持したまま結果を扱える。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L177-L197】
  - `ProviderCallExecutor.execute` が `_invoke_provider` を介して `adapter/core/_provider_execution.py` 内で `ProviderRequest` を構築し、CLI 側 `_build_request` と同一のフィールド構成（`prompt`/`options`/`metadata`）を共有して API 移行を完了させた。【F:projects/04-llm-adapter/adapter/core/_provider_execution.py†L40-L139】
  - `prompts.run_prompts` が `ProviderFactory.create` で得たプロバイダへ `execute_prompts` を介して `ProviderRequest` をまとめて投入し、CLI からのオプション上書きやモデル指定を `ProviderConfig` に反映してから渡す構成へ整理された。【F:projects/04-llm-adapter/adapter/cli/prompts.py†L28-L67】
- 品質エビデンス:
- ✅ CLI パイプライン回帰: `pytest projects/04-llm-adapter/tests/cli_single_prompt/test_provider_options.py::{test_cli_fake_provider,test_cli_provider_option_coerces_types,test_run_prompts_provider_option_coerces_types}` — CLI が `_build_request` でプロバイダ設定の `max_tokens` と `options` を維持しつつ `--provider-option` の文字列を型変換して `ProviderRequest.options` に取り込み、単発/複数プロンプト双方で同一経路をマージできることを検証。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_provider_options.py†L4-L81】
- ✅ CLI エラー分岐: `pytest projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py::{test_cli_errors_when_provider_lacks_invoke,test_cli_errors_when_provider_factory_returns_non_invoke_provider,test_cli_unknown_provider,test_cli_rate_limit_exit_code}` — 旧 `test_prompt_flow.py` で担保していたプロバイダ未実装・未知プロバイダ・429 エラー時の終了コード/標準エラー出力を分割テストで監視し、CLI パイプライン移行後も `ProviderRequest` 経路から正しい `exit_code` を返すことを保証。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_provider_errors.py†L1-L126】
  - ✅ `pytest projects/04-llm-adapter/tests/test_base_provider_spi.py` — `ProviderCallExecutor.execute` が `_invoke_provider` を通じて `ProviderRequest` を構築し、`model`/`prompt`/`max_tokens` などの基本フィールドが正しく揃うことを検証。【F:projects/04-llm-adapter/tests/test_base_provider_spi.py†L108-L139】
  - ✅ `pytest projects/04-llm-adapter/tests/test_provider_execution_request_options.py` — CLI と同一経路で `ProviderRequest.options`/`metadata` がコピーされることを `ProviderCallExecutor.execute` と `BaseProvider.generate` の両方で確認。【F:projects/04-llm-adapter/tests/test_provider_execution_request_options.py†L52-L76】

### タスク9: CLI 入力パイプラインに Ollama/OpenRouter の設定項目を追加する（対応済み）
- 主要モジュール:
  - `adapter/cli/config_loader.py` の `load_provider_configuration` が CLI 引数で受けた `--provider-option` を設定 YAML の `options` とマージし、`ProviderConfig.raw` を差し替えて `api_key` などのリテラル値を統合する。【F:projects/04-llm-adapter/adapter/cli/config_loader.py†L28-L67】
  - `adapter/cli/prompt_runner.py` の `_build_request` が統合済み `ProviderConfig` から `options`/`metadata` を抽出し、`ProviderRequest` へ確実に反映する。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L107】
- 検証テスト:
- `test_cli_provider_option_coerces_types` / `test_run_prompts_provider_option_coerces_types` が `--provider-option` の文字列を型変換して `ProviderRequest.options` に伝播することを検証する。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_provider_options.py†L29-L81】
- `test_cli_openrouter_accepts_provider_option_api_key` が CLI から渡した OpenRouter の `api_key` が `ProviderRequest.options` 経由でプロバイダへ届くことを確認する。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_openrouter_flow.py†L74-L107】

## Docs & Templates

### タスク10: コア README と設定テンプレートを v0.2 用に同期する（対応済み）
- 対応状況:
  - README: Ollama/Ollama 並列実行時のストリーミング設定や OpenRouter の `.env`・CLI 併用手順、運用チェックリストを追記し、タスク要件の手順差分を反映済み。【F:projects/04-llm-adapter/README.md†L160-L214】
  - 設定テンプレート: Ollama 向けテンプレートでローカルエンドポイントとレート制御を明示し、OpenRouter 向けテンプレートで API キー・ベース URL のエイリアスや料金目安を定義した。【F:projects/04-llm-adapter/adapter/config/providers/ollama.yaml†L1-L22】【F:projects/04-llm-adapter/adapter/config/providers/openrouter.yaml†L1-L38】
- テスト/手順: README 更新にあわせ、タスク確認用の `npx --yes markdownlint-cli2 "docs/spec/v0.2/TASKS.md"` 実行手順を整備し、Ollama/OpenRouter 専用 CLI 例が `projects/04-llm-adapter/tests/cli_single_prompt/` 配下で回帰される構成を維持している。【F:projects/04-llm-adapter/tests/cli_single_prompt/test_credentials.py†L81-L115】【F:projects/04-llm-adapter/tests/cli_single_prompt/test_openrouter_flow.py†L74-L107】

### タスク11: Shadow 実装からの `src.llm_adapter` 依存を排除する（完了）
- 進捗: Shadow 配下の Python パッケージを `llm_adapter` 名前空間へ正規化し、旧 `src.llm_adapter` 参照は `__init__` のメタパスエイリアスで段階移行する構成に置き換えた。`pyproject.toml` の first-party 設定も Shadow 名前空間へ更新済み。
- 主要モジュール:
  - `projects/04-llm-adapter-shadow/src/llm_adapter/__init__.py` が `llm_adapter` 直下で公開 API を束ねつつ `src.llm_adapter` への後方互換ロードをメタパスで提供し、Shadow 実装が単一名前空間へ集約されるようにした。【F:projects/04-llm-adapter-shadow/src/llm_adapter/__init__.py†L1-L80】
  - `pyproject.toml` の `known-first-party` と `mypy_path` を Shadow 側の `llm_adapter` パッケージに合わせて整備し、型・lint ツールが新しい名前空間を優先するよう揃えている。【F:pyproject.toml†L1-L40】
- 検証テスト:
  - `projects/04-llm-adapter-shadow/tests/test_no_src_imports.py` が Shadow ツリーとテスト群を走査して `src.llm_adapter` 文字列の混入を禁止し、新旧名前空間の整合を継続的に監視する。【F:projects/04-llm-adapter-shadow/tests/test_no_src_imports.py†L1-L46】

## CLI 実行制御

### タスク15: `prompt_runner` の RateLimiter/実行順序をテストでガードする（完了）
- 進捗: `RateLimiter.wait` の 60 秒ウィンドウ処理と `execute_prompts` の並列制御/エラー種別伝搬を回帰テスト化し、CLI 実装のロック・セマフォ制御と整合することを確認した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L1-L197】【F:projects/04-llm-adapter/tests/test_prompt_runner_rate_limit.py†L1-L117】
- 品質エビデンス: `pytest projects/04-llm-adapter/tests/test_prompt_runner_rate_limit.py` が `rpm=0/1` の境界と gather 戻り順逆転を模擬するケースで `PromptResult.index` ソートと `error_kind` 伝搬を検証し、RateLimiter 実装の破壊を防いでいる。 【F:projects/04-llm-adapter/tests/test_prompt_runner_rate_limit.py†L31-L117】

## CLI 実装の再構成

### タスク16: `prompts.run_prompts` を責務単位で分割しテスタビリティを改善する（完了）
- 進捗: `run_prompts` を薄いオーケストレータに整理し、引数解析・設定統合・実行/エラー制御を `args.py`・`config_loader.py`・`runner.py` へ移譲した。CLI API は維持しつつ ProviderFactory 連携と RateLimiter 公開を再利用できる構造になった。【F:projects/04-llm-adapter/adapter/cli/prompts.py†L1-L74】【F:projects/04-llm-adapter/adapter/cli/args.py†L1-L113】【F:projects/04-llm-adapter/adapter/cli/config_loader.py†L1-L160】【F:projects/04-llm-adapter/adapter/cli/runner.py†L1-L178】
- 品質エビデンス: `pytest projects/04-llm-adapter/tests/test_cli_prompts_refactor.py` が環境変数未設定・`.env` ロード・`--provider-option` マージ・RateLimit 例外などの主要パスを網羅し、再構成後も出力/終了コードが変わらないことを確認する。 【F:projects/04-llm-adapter/tests/test_cli_prompts_refactor.py†L1-L158】
