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
  - `ProviderRequest` ベースの呼び出しとトークン計測をコア実装へ移植し、`projects/04-llm-adapter/README.md` に Ollama の利用方法を記載済み。
- 品質エビデンス:
  - `pytest projects/04-llm-adapter/tests/providers/test_ollama_provider.py` が成功し、既存 YAML と整合するオプションが網羅されている。

### タスク7: OpenRouter プロバイダを v0.2 コアに統合する（対応済み）
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/core/providers/openrouter.py`
  - `projects/04-llm-adapter/adapter/core/providers/__init__.py`
  - `projects/04-llm-adapter/tests/providers/test_openrouter_provider.py`
- 対応状況:
  - `ProviderRequest` からヘッダ構成とレート制御を構築する実装をコア側へ反映し、`projects/04-llm-adapter/README.md` に OpenRouter の利用手順と環境変数を追記済み。
- 品質エビデンス:
  - `pytest projects/04-llm-adapter/tests/providers/test_openrouter_provider.py` が成功し、既存 YAML の必須キーを読み込めている。

## CLI Request Pipeline

### タスク8: CLI から `ProviderRequest` への移行を完了する
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/app.py`
  - `projects/04-llm-adapter/adapter/cli/prompt_runner.py`
  - `projects/04-llm-adapter/adapter/core/provider_spi.py`
- 完了条件:
  - Shadow 実装の [CLI runner](../../../projects/04-llm-adapter-shadow/src/llm_adapter/cli/runner.py) と同等に、CLI 引数から `ProviderRequest` を構築して `ProviderSPI.invoke` へ渡す。
  - `pytest projects/04-llm-adapter/tests/test_cli_single_prompt_diagnostics.py` と `pytest projects/04-llm-adapter/tests/test_base_provider_spi.py` が成功し、`generate` API を経由するコードは残さない。
  - `docs/spec/v0.2/ROADMAP.md` に CLI 移行状況の脚注を追記する。

### タスク9: CLI 入力パイプラインに Ollama/OpenRouter の設定項目を追加する
- 対象モジュール:
  - `projects/04-llm-adapter/adapter/cli/app.py`
  - `projects/04-llm-adapter/adapter/cli/utils.py`
  - `projects/04-llm-adapter/adapter/config/providers`
- 完了条件:
  - `adapter/cli/app.py` の `--provider`/`--model` オプションで Ollama/OpenRouter 固有の `options.*` を指定できるよう、`ProviderRequest` の追加フィールドをマッピングする。
  - 現状 `projects/04-llm-adapter/adapter/config/providers/ollama.yaml` と `projects/04-llm-adapter/adapter/config/providers/openrouter.yaml` は既存だが、`projects/04-llm-adapter/README.md` の [Provider configuration](../../../projects/04-llm-adapter/README.md#provider-configuration) に揃うよう項目を精査し不足分を補う。
  - `pytest projects/04-llm-adapter/tests/test_cli_single_prompt_diagnostics.py::test_prompt_runner_provider_response_tokens` を含む CLI 系テストが成功し、`markdownlint docs/spec/v0.2/TASKS.md` も通過する。

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
