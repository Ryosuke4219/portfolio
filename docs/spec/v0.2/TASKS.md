# LLM Adapter (Core) — v0.2 タスク分解

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
  1. CI が赤くなった場合は該当ログを分類し、`just lint`（静的解析）→`pytest projects/04-llm-adapter/tests`（Pythonコア）→必要に応じて `npm run` 系（Node側）の順でローカル再現する。
  2. 失敗原因が新規ケースの場合は再発防止のテスト or Lint ルール追加を別チケット化し、本タスクで暫定修正を行う。
  3. 緑化確認後は CI リンクと修正概要を記録し、既存タスクが解消された場合はクローズする。

## Refactoring

### タスク5: `runner_execution.py` を責務単位で分割し可読性を向上させる
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
  - CLI からリテラル指定した API キーを `ProviderRequest.options["api_key"]` に格納し、Ollama へも伝播できるよう CLI パイプラインを整備した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L105】【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L224-L258】
- 品質エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/providers/test_ollama_provider.py` が成功し、ストリーミング結合・自動 Pull 無効時の例外・429/5xx 正規化・CI/オフライン分岐を契約テストで担保している。【F:projects/04-llm-adapter/tests/providers/test_ollama_provider.py†L200-L389】
  - ✅ `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py::test_cli_literal_api_key_option` が成功し、CLI で指定したリテラル API キーが `ProviderRequest.options` へ反映される経路を検証している。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L224-L258】

### タスク7: OpenRouter プロバイダを v0.2 コアに統合する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/openrouter.py`
  - `projects/04-llm-adapter/adapter/core/providers/__init__.py`
  - `projects/04-llm-adapter/tests/providers/test_openrouter_provider.py`
- 対応状況:
  - `OpenRouterProvider` が API キー/ベース URL の環境変数マッピングとセッションヘッダ初期化を担い、Shadow 依存なしでコア提供する構成へ移行した。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L126-L200】
  - `ProviderRequest` のオプション優先順位を HTTP ペイロードへ反映し、ストリーミングチャンクからのテキスト/トークン統合を `ProviderResponse` へ集約している。【F:projects/04-llm-adapter/adapter/core/providers/openrouter.py†L202-L330】
  - CLI からのリテラル API キー指定や設定ファイルの `api_key`/`env` を `ProviderRequest.options["api_key"]` へ結線し、OpenRouter でも CLI からの入力が確実に伝播する完了経路として整理した。【F:projects/04-llm-adapter/adapter/cli/prompt_runner.py†L58-L105】【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L393-L481】
- 品質エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/providers/test_openrouter_provider.py` が成功し、`ProviderRequest.options` 経由で付与される認証ヘッダが秘匿されたまま HTTP セッションへ反映され、429/503 正規化と `ProviderCallExecutor` 連携を網羅している。【F:projects/04-llm-adapter/tests/providers/test_openrouter_provider.py†L140-L396】
  - ✅ `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py::test_cli_openrouter_accepts_provider_option_api_key` を含む CLI テスト群で、OpenRouter 向けのリテラル API キーが `ProviderRequest.options` で秘匿されたまま CLI からプロバイダへ伝播することを確認済み。【F:projects/04-llm-adapter/tests/test_cli_single_prompt.py†L451-L481】

#### 継続課題（Providers）
- 実サーバーでのストリーミング透過性検証と運用フロー整備（タスク13を参照）。
- OpenRouter 429/5xx 発生状況の集計とドキュメント拡充（タスク14を参照）。

### タスク12: OpenAI プロバイダのリクエストオプションを v0.2 コアへ拡張する
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/openai.py`
  - `projects/04-llm-adapter/adapter/config/providers/openai.yaml`
  - `projects/04-llm-adapter/adapter/cli/app.py`
- 完了条件:
  - `ProviderRequest.options` の `openai.*` パラメータを OpenAI API へ透過する共通マッピングを整備し、トークン計測やストリーミング挙動を既存実装と揃える。
  - CLI から `--provider openai` 選択時に上記オプションを指定・検証できるよう入力バリデーションとヘルプを更新し、`pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py` を含む CLI テスト群を緑化する。
  - `markdownlint 04/ROADMAP.md` を含む既存のドキュメント整形チェックを通過させ、`docs/spec/v0.2/TASKS.md` の該当節へ進捗リンクを追加する。

### タスク13: OpenRouter ストリーミング実サーバー検証を運用へ組み込む（対応済み）
- 対応状況: OpenRouter のストリーミングログをプローブする CLI を `tools/openrouter/stream_probe.py` に集約し、`llm-adapter-openrouter-probe` と `just openrouter-stream-probe` の両方から共通エントリポイントを呼び出してリアルタイム確認できるようにした。【F:projects/04-llm-adapter/tools/openrouter/stream_probe.py†L1-L105】【F:projects/04-llm-adapter/pyproject.toml†L25-L28】【F:justfile†L91-L95】
- 品質エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py` が成功し、OpenRouter 向け CLI からのストリーミングイベントが `ProviderResponse` へ透過することを確認している。【F:projects/04-llm-adapter/tests/tools/test_openrouter_stream_probe.py†L54-L120】
  - ✅ `llm-adapter-openrouter-probe --dry-run` と `just openrouter-stream-probe -- --dry-run` の実行手順を CI 手順に組み込み、OpenRouter のログ生成と失敗時の再試行挙動を本タスクへ反映済み。【F:projects/04-llm-adapter/tools/openrouter/stream_probe.py†L88-L104】【F:justfile†L91-L95】

### タスク14: OpenRouter ドキュメントと 429/5xx ガードを拡充する（対応済み）
- 対応状況: `tools/report/metrics` に `openrouter-stats` サブコマンドを追加し、`artifacts/openrouter/` へ 429/5xx 集計 JSONL を保存。API キー/ベース URL の伝播手順と集計の運用フローを README・CLI ガイドおよび本タスクに反映した。【F:docs/spec/v0.2/TASKS.md†L78-L81】
- 成果/エビデンス:
  - ✅ `pytest projects/04-llm-adapter/tests/test_metrics_openrouter_stats.py` で 429/5xx の正規化と週次スライスが検証されている。【F:docs/spec/v0.2/TASKS.md†L81-L82】
  - ✅ `just openrouter-stats --since 2025-10-01` の実行手順と CI スケジュールを本タスクへ記録し、運用ログを共有している。【F:docs/spec/v0.2/TASKS.md†L82-L84】

## CLI Request Pipeline

### タスク8: CLI から `ProviderRequest` への移行を完了する
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/app.py`
  - `projects/04-llm-adapter/adapter/cli/prompt_runner.py`
  - `projects/04-llm-adapter/adapter/core/provider_spi.py`
- 完了条件:
  - [CLI runner](../../../projects/04-llm-adapter/adapter/cli/prompt_runner.py) が CLI 引数から `ProviderRequest` を構築し、`ProviderSPI.invoke` へ渡す流れを `projects/04-llm-adapter/adapter/cli/app.py` から呼び出す形へ統一する。
  - `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py` と `pytest projects/04-llm-adapter/tests/test_base_provider_spi.py` が成功し、`generate` API を経由するコードは残さない。
  - `docs/spec/v0.2/ROADMAP.md` に CLI 移行状況の脚注を追記する。

### タスク9: CLI 入力パイプラインに Ollama/OpenRouter の設定項目を追加する
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/app.py`
  - `projects/04-llm-adapter/adapter/cli/utils.py`
  - `projects/04-llm-adapter/adapter/config/providers`
- 完了条件:
  - `adapter/cli/app.py` の `--provider`/`--model` オプションで Ollama/OpenRouter 固有の `options.*` を指定できるよう、`ProviderRequest` の追加フィールドをマッピングする。
  - CLI で `ProviderRequest.options.*` へ OpenAI など汎用プロバイダ設定を伝播させる残課題を解消し、`projects/04-llm-adapter/adapter/cli/prompt_runner.py` から `ProviderSPI.invoke` まで一貫させる。
  - 現状 `projects/04-llm-adapter/adapter/config/providers/ollama.yaml` と `projects/04-llm-adapter/adapter/config/providers/openrouter.yaml` は既存だが、`projects/04-llm-adapter/README.md` の [サンプル設定とプロンプト](../../../projects/04-llm-adapter/README.md#サンプル設定とプロンプト) に揃うよう項目を精査し不足分を補う。
  - `pytest projects/04-llm-adapter/tests/test_cli_single_prompt.py::test_cli_fake_provider` を含む CLI 系テストが成功し、`markdownlint docs/spec/v0.2/TASKS.md` も通過する。

## Docs & Templates

### タスク10: コア README と設定テンプレートを v0.2 用に同期する
- 対象モジュール:
  - `projects/04-llm-adapter/README.md`
  - `projects/04-llm-adapter/adapter/config/providers/*.yaml`
  - `docs/spec/v0.2/TASKS.md`
- 完了条件:
  - `projects/04-llm-adapter/README.md` の最新情報を保ち、Ollama/OpenRouter のセットアップ手順と API キー環境変数を追記する。
  - `projects/04-llm-adapter/adapter/config/providers/*.yaml` に新規テンプレートを追加し、`just lint` と `pytest projects/04-llm-adapter/tests` を通過させる。
  - 本タスクリストを更新し、`markdownlint` で整形エラーがないことを確認する。

### タスク11: Shadow 実装からの `src.llm_adapter` 依存を排除する
- 対象モジュール:
  - `pyproject.toml`
  - `projects/04-llm-adapter/adapter/**`
- 完了条件:
  1. Shadow 専用の `src.llm_adapter` 参照をコア側へ移行または削除し、`pyproject.toml` の `known-first-party` や `coverage` 設定から除去する。
  2. `just lint` と `pytest projects/04-llm-adapter/tests` が成功する。
  3. コア実装へ統合された場合は該当モジュールの import 先を更新し、Shadow 側の同名ファイルに deprecation を残すかどうかを判断する。
