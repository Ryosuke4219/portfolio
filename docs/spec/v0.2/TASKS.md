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
