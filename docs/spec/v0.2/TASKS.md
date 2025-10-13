# LLM Adapter (Core) — v0.2 タスク分解

> 2025-11-09 更新: v0.1.0 リリースチェックリストと OpenRouter 運用ガイドを追加し、M6 Exit Criteria を満たした。以降は v0.2 タスクとして保守・拡張を継続する。

## CLI / 入力整備

### タスク1: `--prompt-file` / `--prompts` のCRLF・BOM対応を強化する（対応済み）
- 対応状況: `collect_prompts` は `prompt_file` を UTF-8 で読み込み、末尾の `\r\n` を除去してからプロンプト一覧に追加する。`read_jsonl_prompts` も BOM 付き JSONL 行を `lstrip("\ufeff")` で正規化してから `json.loads` を実行し、辞書・文字列のどちらも既存キー順で解決している。【F:projects/04-llm-adapter/adapter/cli/prompt_io.py†L18-L71】
- 品質エビデンス: `projects/04-llm-adapter/tests/test_cli_prompt_io.py` が CRLF 付きテキストと BOM 付き JSONL の双方を読み込めることを回帰テストとして検証済み。【F:projects/04-llm-adapter/tests/test_cli_prompt_io.py†L1-L21】

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

### タスク5: `runner_execution.py` を責務単位で分割し可読性を向上させる（未完了）
- 進捗: 未着手。v0.2 でのリファクタリング計画のみ策定済み。
- 背景: `RunnerExecution` は 280 行超の大型クラスで、プロバイダ呼び出し・シャドウ制御・メトリクス生成・スキーマ検証が一箇所に詰め込まれている。【F:projects/04-llm-adapter/adapter/core/runner_execution.py†L1-L276】 保守性向上のため責務分割が必要。
- 手順:
  1. 既存ユニットテストを調査し、`SequentialAttemptExecutor`/`ParallelAttemptExecutor` の振る舞いをカバーする回帰テスト（不足していれば追加）を先に用意する。
  2. `_run_single` のプロバイダ呼び出し・メトリクス構築・シャドウ処理をそれぞれ専用モジュール/クラスへ切り出し、公開API（シグネチャ）を維持したままファイル分割する。
  3. `pytest projects/04-llm-adapter/tests/test_compare_runner_orchestration.py` など既存スイートを実行し、リファクタ後も挙動が変わらないことを確認する。

## Providers

### タスク6: Ollama プロバイダを v0.2 コアへ移植する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/ollama.py`
  - `projects/04-llm-adapter/adapter/core/providers/__init__.py`
  - `projects/04-llm-adapter/tests/providers/test_ollama_provider.py`
- 対応状況:
  - `OllamaProvider` が環境変数・設定ファイル・CLI からホストやタイムアウト、自動 Pull の優先順位を解決し、CI/オフライン制御に応じて `ProviderSkip` を返す挙動を含めてコアへ組み込まれた。【F:projects/04-llm-adapter/adapter/core/providers/ollama.py†L50-L166】
  - `ProviderRequest` のメッセージと `options.*` をチャットペイロードへ取り込み、ストリーミング応答を `ProviderResponse` に正規化する処理を実装した。【F:projects/04-llm-adapter/adapter/core/providers/ollama.py†L168-L268】
  - CLI からリテラル指定した API キーを `ProviderRequest.options["api_key"]` に格納し、Ollama へも伝播できるよう CLI パイプラインを整備した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L107】【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L359-L392】
- 品質エビデンス:
- ✅ CLI API キー透過テスト: `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py::test_cli_literal_api_key_option` が成功し、CLI で指定したリテラル API キーが `ProviderRequest.options` を介して Ollama へ伝播する経路を検証している。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L359-L392】
  - ✅ ストリーミング・429/5xx 検証テスト: `pytest projects/04-llm-adapter/tests/providers/test_ollama_provider.py` がストリーミング結合と 429/5xx 正規化を含むケースを通過し、`ProviderResponse` 正規化とリトライ戦略を担保している。【F:projects/04-llm-adapter/tests/providers/test_ollama_provider.py†L200-L389】

### タスク7: OpenRouter プロバイダを v0.2 コアに統合する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/openrouter.py`
  - `projects/04-llm-adapter/adapter/core/providers/__init__.py`
  - `projects/04-llm-adapter/tests/providers/test_openrouter_provider.py`
- 対応状況:
  - `OpenRouterProvider` が API キー/ベース URL の環境変数マッピングとセッションヘッダ初期化を担い、Shadow 依存なしでコア提供する構成へ移行した。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L126-L200】
  - `ProviderRequest` のオプション優先順位を HTTP ペイロードへ反映し、ストリーミングチャンクからのテキスト/トークン統合を `ProviderResponse` へ集約している。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L202-L330】
  - CLI からのリテラル API キー指定や設定ファイルの `api_key`/`env` を `ProviderRequest.options["api_key"]` へ結線し、OpenRouter でも CLI からの入力が確実に伝播する完了経路として整理した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L107】【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L604-L693】
  - OpenRouter 運用ドキュメントを `projects/04-llm-adapter/README.md` と `docs/releases/v0.1.0.md` に同期し、`python -m tools.report.metrics.openrouter_stats --metrics artifacts/runs-metrics.jsonl --out artifacts/openrouter --since ...`（`just openrouter-stats -- --since ...` 経由でも同等）と `llm-adapter-openrouter-probe` の手順を最新化した。【F:projects/04-llm-adapter/README.md†L198-L206】【F:docs/releases/v0.1.0.md†L1-L23】
- 品質エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/providers/test_openrouter_provider.py` が成功し、`ProviderRequest.options` 経由で付与される認証ヘッダが秘匿されたまま HTTP セッションへ反映され、429/503 正規化と `ProviderCallExecutor` 連携を網羅している。【F:projects/04-llm-adapter/tests/providers/test_openrouter_provider.py†L140-L396】
- ✅ `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py::test_cli_openrouter_accepts_provider_option_api_key` を含む CLI テスト群で、OpenRouter 向けのリテラル API キーが `ProviderRequest.options` で秘匿されたまま CLI からプロバイダへ伝播することを確認済み。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L662-L693】
#### 継続課題（Providers）
- 実サーバーでのストリーミング透過性検証と運用フロー整備（タスク13を参照）。
- OpenRouter 429/5xx 発生状況の集計とドキュメント拡充（タスク14を参照）。

### タスク12: OpenAI プロバイダのリクエストオプションを v0.2 コアへ拡張する（対応済み）
- 主要モジュール: `adapter/core/providers/openai.py` が `_prepare_request_kwargs` で `ProviderRequest.options`・温度・停止語・タイムアウトを統合し、`responses`/`chat.completions`/`completions` それぞれの呼び出しでストリーミングと `max_tokens` の上書きを一貫化した。【F:projects/04-llm-adapter/adapter/core/providers/openai.py†L200-L296】
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
- ✅ `python -m tools.report.metrics.openrouter_stats --metrics artifacts/runs-metrics.jsonl --out artifacts/openrouter --since 2025-10-01`（`just openrouter-stats -- --since 2025-10-01` 相当）の実行手順と CI スケジュールを本タスクへ記録し、`--out` で指定した `artifacts/openrouter/` に最新集計を生成する運用ログを共有している。【F:justfile†L96-L101】

## CLI Request Pipeline

### タスク8: CLI から `ProviderRequest` への移行を完了する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/app.py`
  - `projects/04-llm-adapter/adapter/cli/prompt_runner.py`
  - `projects/04-llm-adapter/adapter/core/_provider_execution.py`
- 対応状況:
  - `prompt_runner.execute_prompts` が CLI から渡された `ProviderConfig` を `_build_request` で `ProviderRequest` に正規化し、プロンプト・オプション・メタデータを統合した上で `invoke` の同期呼び出しへ供給する実装に刷新した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L142】
  - `ProviderCallExecutor.execute` が `_invoke_provider` を介して `adapter/core/_provider_execution.py` 内で `ProviderRequest` を構築し、CLI 側 `_build_request` と同一のフィールド構成（`prompt`/`options`/`metadata`）を共有して API 移行を完了させた。【F:projects/04-llm-adapter/adapter/core/_provider_execution.py†L40-L139】
  - `prompts.run_prompts` が `ProviderFactory.create` で得たプロバイダへ `execute_prompts` を介して `ProviderRequest` をまとめて投入し、CLI からのオプション上書きやモデル指定を `ProviderConfig` に反映してから渡す構成へ整理された。【F:projects/04-llm-adapter/adapter/cli/prompts.py†L335-L384】
- 品質エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py` — CLI が `_build_request` で構築した `ProviderRequest` に API キーやプロンプト配列を束ね、`prompt_runner.execute_prompts` が `ProviderResponse` を取得する流れを検証。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L22-L219】
  - ✅ `pytest projects/04-llm-adapter/tests/test_base_provider_spi.py` — `ProviderCallExecutor.execute` が `_invoke_provider` を通じて `ProviderRequest` を構築し、`options`/`metadata` の整合性を担保する回帰テストを維持。【F:projects/04-llm-adapter/tests/test_base_provider_spi.py†L108-L139】

### タスク9: CLI 入力パイプラインに Ollama/OpenRouter の設定項目を追加する（対応済み）
- 主要モジュール:
  - `adapter/cli/prompts.py` が CLI 引数で受けた `--provider-option` を設定 YAML の `options` とマージし、`ProviderConfig.raw` を差し替えて `api_key` などのリテラル値を統合する。【F:projects/04-llm-adapter/adapter/cli/prompts.py†L242-L331】
  - `adapter/cli/prompt_runner.py` の `_build_request` が統合済み `ProviderConfig` から `options`/`metadata` を抽出し、`ProviderRequest` へ確実に反映する。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L107】
- 検証テスト:
  - `test_cli_provider_option_coerces_types` / `test_run_prompts_provider_option_coerces_types` が `--provider-option` の文字列を型変換して `ProviderRequest.options` に伝播することを検証する。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L396-L460】
  - `test_cli_openrouter_accepts_provider_option_api_key` が CLI から渡した OpenRouter の `api_key` が `ProviderRequest.options` 経由でプロバイダへ届くことを確認する。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L662-L692】

## Docs & Templates

### タスク10: コア README と設定テンプレートを v0.2 用に同期する（対応済み）
- 対応状況:
  - README: Ollama/Ollama 並列実行時のストリーミング設定や OpenRouter の `.env`・CLI 併用手順、運用チェックリストを追記し、タスク要件の手順差分を反映済み。【F:projects/04-llm-adapter/README.md†L160-L214】
  - 設定テンプレート: Ollama 向けテンプレートでローカルエンドポイントとレート制御を明示し、OpenRouter 向けテンプレートで API キー・ベース URL のエイリアスや料金目安を定義した。【F:projects/04-llm-adapter/adapter/config/providers/ollama.yaml†L1-L22】【F:projects/04-llm-adapter/adapter/config/providers/openrouter.yaml†L1-L38】
  - テスト/手順: README 更新にあわせ、タスク確認用の `npx --yes markdownlint-cli2 "docs/spec/v0.2/TASKS.md"` 実行手順を整備し、Ollama/OpenRouter 専用 CLI 例が `projects/04-llm-adapter/tests/test_cli_single_prompt.py` で回帰される構成を維持している。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L359-L460】【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L604-L693】

### タスク11: Shadow 実装からの `src.llm_adapter` 依存を排除する（未完了）
- 進捗: 未着手。依存除去と CI 手順の緑化確認が未実行。
- 対象モジュール:
  - `pyproject.toml`
  - `projects/04-llm-adapter/adapter/**`
- 完了条件:
  1. Shadow 専用の `src.llm_adapter` 参照をコア側へ移行または削除し、`pyproject.toml` の `known-first-party` や `coverage` 設定から除去する。
  2. Python/Node 静的解析は CI と同じ順序で `npm run lint:js` → `ruff check .` → `mypy --config-file pyproject.toml projects/04-llm-adapter/adapter` → `mypy --config-file pyproject.toml projects/04-llm-adapter-shadow/src` → `python -m compileall projects/04-llm-adapter-shadow` を通過させる。Node 変更があれば `npm run ci:analyze` で差分の影響を確認し、`pytest projects/04-llm-adapter-shadow/tests` まで含めて CI と同等の検証を完了する。
  3. コア実装へ統合された場合は該当モジュールの import 先を更新し、Shadow 側の同名ファイルに deprecation を残すかどうかを判断する。

## CLI 実行制御

### タスク15: `prompt_runner` の RateLimiter/実行順序をテストでガードする（未完了）
- 進捗: 未着手。RateLimiter の境界テストが未追加。
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/prompt_runner.py`
  - `projects/04-llm-adapter/tests/test_prompt_runner.py`（新規）
- 完了条件:
  1. `RateLimiter.wait` と `execute_prompts` が `rpm` や並列数に従って呼び出しを抑制することを再現するテストを先に追加し、現在の 60 秒ウィンドウ制御（`asyncio.Lock` + `deque`）の境界ケース（`rpm=0`・`rpm=1`・短時間で複数投入）を網羅する。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L23-L196】
  2. スタブプロバイダを用意し、`execute_prompts` が `PromptResult.index` 順でソートされること、および失敗時に `classify_error` の戻り値が `PromptResult.error_kind` に反映されることを検証する。
  3. 必要に応じて `prompt_runner` 本体をテスタビリティ向上のために小調整する場合は型注釈を維持しつつ最小差分で行い、`pytest projects/04-llm-adapter/tests/test_prompt_runner.py` → `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py` の順で緑化する。

## CLI 実装の再構成

### タスク16: `prompts.run_prompts` を責務単位で分割しテスタビリティを改善する（未完了）
- 進捗: 未着手。回帰テストとファイル分割が未実施。
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/prompts.py`
  - `projects/04-llm-adapter/adapter/cli/` 配下の新規モジュール（例: `args.py` / `config_loader.py` など）
  - `projects/04-llm-adapter/tests/test_cli_prompts_refactor.py`（新規）
- 完了条件:
  1. 391 行の `prompts.py` が単一ファイルで CLI 解析・環境変数解決・ProviderFactory 呼び出し・結果出力まで抱えている現状をカバーする回帰テストを先に追加し、`run_prompts` の代表的な成功/失敗パス（環境変数未設定・`.env` ロード・`--provider-option` マージなど）を明文化する。【F:projects/04-llm-adapter/adapter/cli/prompts.py†L1-L392】
  2. テスト緑を維持したまま、引数パース・設定マージ・エラーハンドリングをそれぞれ新規モジュールへ切り出し、`prompts.py` 側はエントリポイントとログ設定の薄いラッパーに整理する。段階的に切り替えるため、既存関数から新モジュールを呼ぶ TODO チェックリストを追記し、全項目に ✅ を付けてから旧実装ブロックを削除する。
  3. 既存 CLI 公開 API（`run_prompts` / `ProviderFactory` / 出力形式）はそのまま維持しつつ、Python/Node の静的解析は CI と同じ順序で `npm run lint:js` → `ruff check .` → `mypy --config-file pyproject.toml projects/04-llm-adapter/adapter` → `mypy --config-file pyproject.toml projects/04-llm-adapter-shadow/src` → `python -m compileall projects/04-llm-adapter-shadow` を通過させる。Node 関連差分がある場合は `npm run ci:analyze` を併走し、`pytest projects/04-llm-adapter-shadow/tests` と `npx --yes markdownlint-cli2 "docs/spec/v0.2/TASKS.md"`（必要なら `npx --yes markdownlint-cli2 "04/ROADMAP.md"`）で再現性と整形を確認してから進捗欄へ反映する。
