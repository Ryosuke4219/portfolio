# LLM Adapter (Core) — v0.2 タスク分解

## CLI / 入力整備

### タスク1: `--prompt-file` / `--prompts` のCRLF・BOM対応を強化する
- 背景: CLI では `--prompt-file`/`--prompts` からプロンプトを読み込み可能だが【F:projects/04-llm-adapter/README.md†L70-L76】、現状の実装は CRLF 改行や UTF-8 BOM を許容しておらず、Windowsで保存したファイルやBOM付きJSONLを読み込むと余分な `\r` が残ったり `JSONDecodeError` が即時送出される。【F:projects/04-llm-adapter/adapter/cli/prompt_io.py†L15-L71】
- 手順:
  1. `projects/04-llm-adapter/tests/test_cli_prompt_io.py` を新設し、(a) CRLF付き `--prompt-file` で `collect_prompts` が `\r` を含まない文字列を返すこと、(b) BOM付き JSONL を `read_jsonl_prompts` が正常に読み込むこと、の2ケースで赤くなるテストを追加する。
  2. `collect_prompts` で改行除去処理を `rstrip("\r\n")` へ更新し、`read_jsonl_prompts` の先頭行から UTF-8 BOM を除去する（`lstrip("\ufeff")` 等）。
  3. `pytest projects/04-llm-adapter/tests/test_cli_prompt_io.py` を実行し、テスト追加→修正の順で緑化する。

## Datasets / ゴールデン検証

### タスク2: `load_golden_tasks` を UTF-8 BOM と行番号付きエラーへ対応させる
- 背景: ゴールデンタスク JSONL は仕様上反復利用する想定であり【F:projects/04-llm-adapter/docs/spec_adapter_lab.md†L73-L108】、現状のローダーは BOM 付きファイルや壊れた JSON 行で素の `JSONDecodeError` を投げてしまう。【F:projects/04-llm-adapter/adapter/core/datasets.py†L45-L64】
- 手順:
  1. `projects/04-llm-adapter/tests/test_datasets_loader.py` を追加し、BOM付き1行と途中で壊れた行を含むファイルで (a) 正常ロード、(b) 例外メッセージに行番号が含まれること、を確認する失敗テストを書く。
  2. `load_golden_tasks` を `encoding="utf-8-sig"` もしくは BOM 除去する読み込みへ変更し、`json.loads` 例外を捕捉して `ValueError(f"invalid JSON at {path}:{line}")` 形式の明示的エラーへ差し替える。
  3. `pytest projects/04-llm-adapter/tests/test_datasets_loader.py` を実行し、BOM対応とエラー文言の緑化を確認する。

## Metrics / 決定性ガード

### タスク3: 決定性ゲート失敗時のエラーメッセージを記録する
- 背景: v1.0仕様では失敗分類ログを残すことが求められているが【F:projects/04-llm-adapter/docs/spec_adapter_lab.md†L18-L21】、現在の `DeterminismGate` は `status`/`failure_kind` を更新するのみで具体的な理由を `error_message` に残さない。【F:projects/04-llm-adapter/adapter/core/compare_runner_finalizer.py†L25-L78】
- 手順:
  1. `projects/04-llm-adapter/tests/test_compare_runner_finalizer.py` を新設（既に同等テストが `test_compare_runner_metrics.py` 等に存在する場合はファイル名をそちらへ合わせて修正）し、決定性閾値超過時に `error_message` が `median_diff` や `len_stdev` を含むことを期待するテストを先に追加する（閾値を超えた際の `error_message` には差分統計が含まれるべき旨を明記しておく）。
  2. `DeterminismGate.apply` 内でゲート失敗時に `error_message` へ理由を追記（既存メッセージがあれば連結）する実装を追加し、標準出力には変化を与えない。
  3. `pytest projects/04-llm-adapter/tests/test_compare_runner_finalizer.py` を流し、文言追加後に緑化する。

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
