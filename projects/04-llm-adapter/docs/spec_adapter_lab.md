# LLM Adapter 実験装置 — 要件・仕様（v1.0）

（対象：B1〜B4「計測・比較・回帰」一式／配置推奨：`/projects/04-llm-adapter/docs/spec_adapter_lab.md`）

---

## 0. 目的（Purpose）

* LLM 実験（プロバイダ／プロンプト／実行モード）の結果を**定量化・可視化・回帰**できる最小実用の実験装置を提供する。
* 5分で概況、10分で比較判断、30分で回帰まで到達できる導線を整える。

---

## 1. スコープ / 非スコープ

### スコープ

* **B1**: メトリクス収集（JSONL）→ **HTMLレポ自動生成**（表・グラフ）
* **B2**: **決定性・再現性ガード**（seed/温度/再試行/予算）＋比較ランナー
* **B3**: **ゴールデン小データセット**の運用と **baseline vs 最新**回帰
* **B4**: **失敗分類ログ**の付与と週次サマリへの集計反映

### 非スコープ（v1.0）

* 自前の評価モデルや人手評価 UI の実装（将来拡張）
* 外部SaaS（Weights & Biases 等）への常時アップロード（必要なら拡張点として）

---

## 2. 利用者と主要ユースケース

* **SDET/開発QA**：複数プロバイダ・プロンプトの**速度/コスト/差分率**比較、再現性確認
* **非開発QA/EM**：**週次トレンド**（失敗種別、成功率、コスト）把握
* 代表フロー：

  1. `run_compare.py` で 2プロバイダ×2プロンプト×N回 実行
  2. `runs-metrics.jsonl` を `metrics_to_html.py` で **`/reports/index.html`** に可視化
  3. `just golden` で **baseline vs 最新** の回帰比較を HTML に差し込む

---

## 3. 成果物と配置

```
/adapter/
  ├─ run_compare.py                     # 比較ランナー（並列/直列）
  ├─ config/
  │    ├─ providers/openai.yaml         # 例：プロバイダ設定（seed/温度/価格/制限）
  │    ├─ providers/local_ollama.yaml   # 例：ローカル推論
  │    └─ budgets.yaml                  # 予算と打ち切りポリシー
/datasets/
  └─ golden/
       ├─ tasks.jsonl                   # 10〜20件の小データ
       └─ baseline/                     # 期待 or 参照出力（任意）
/tools/report/
  └─ metrics_to_html.py                 # JSONL→HTML
/reports/
  └─ index.html                         # 集計レポ（Actionsで更新）
/data/
  └─ runs-metrics.jsonl                 # 実行ログ（追記）
```

> **運用メモ**: `/data/` と `/reports/` 配下の生成物は `.gitignore` に登録し、GitHub にはコミットしない。ローカルでの再現手順とスクリーンショットは [`docs/examples/llm-adapter/README.md`](../../../docs/examples/llm-adapter/README.md) にまとめる。

---

## 4. データモデル

### 4.1 実行メトリクス（`/data/runs-metrics.jsonl`）

**1行=1試行（Attempt）**。UTF-8、改行区切り JSON。

```json
{
  "ts": "2025-09-22T12:34:56Z",
  "run_id": "gh_123456789",
  "provider": "openai",
  "model": "gpt-4.1-mini",
  "mode": "parallel",                  // parallel | serial
  "prompt_id": "task-001",
  "prompt_name": "login_happy_path",
  "seed": 42,
  "temperature": 0.2,
  "top_p": 1.0,
  "max_tokens": 512,
  "input_tokens": 314,
  "output_tokens": 201,
  "latency_ms": 1435,
  "cost_usd": 0.0019,                  // providers.yaml の単価で算出
  "status": "ok",                      // ok | error
  "failure_kind": null,                // timeout | non_deterministic | parsing | guard_violation | provider_error | null
  "error_message": null,
  "output_text": "<redacted-or-hash>", // 生文は保存せず、既定はハッシュ/要約
  "output_hash": "sha256:...",
  "eval": {
    "exact_match": false,
    "diff_rate": 0.12,                 // 正規化距離（下記 §6.2）
    "len_tokens": 201
  },
  "budget": {
    "run_budget_usd": 0.05,
    "hit_stop": false
  },
  "ci_meta": { "branch": "main", "commit": "a1b2c3d" }
}
```

> **プライバシー**：`output_text` は既定で **ハッシュ**（または先頭128字でマスク）にする。生文保存を許可する場合のみ `providers.yaml` で `persist_output: true`。

### 4.2 プロバイダ設定（`/adapter/config/providers/*.yaml`）

```yaml
provider: openai
endpoint: https://api.openai.com/v1/chat/completions
model: gpt-4.1-mini
auth_env: OPENAI_API_KEY
seed: 42
temperature: 0.2
top_p: 1.0
max_tokens: 512
timeout_s: 60
retries:
  max: 2
  backoff_s: 2
persist_output: false
pricing:              # /1k tokens
  prompt_usd: 0.005
  completion_usd: 0.015
rate_limit:
  rpm: 300
  tpm: 400000
quality_gates:
  determinism_diff_rate_max: 0.15     # 反復時の許容差分率
  determinism_len_stdev_max: 8        # 出力トークン長の許容標準偏差
```

### 4.3 予算設定（`/adapter/config/budgets.yaml`）

```yaml
default:
  run_budget_usd: 0.05
  daily_budget_usd: 2.00
  stop_on_budget_exceed: true
overrides:
  openai: { run_budget_usd: 0.10 }
  local_ollama: { run_budget_usd: 0.00 }   # ローカルはコスト0扱い
```

### 4.4 ゴールデン小データ（`/datasets/golden/tasks.jsonl`）

```json
{
  "id": "task-001",
  "name": "login_happy_path",
  "input": { "username": "alice", "password": "secret" },
  "prompt_template": "Login user {{username}} with password {{password}} and return SUCCESS/FAIL.",
  "expected": { "type": "regex", "value": "SUCCESS" }   // or {type: "json_equal", value: {...}}
}
```

---

## 5. メトリクスと指標

### 5.1 基本

* **latency_ms**：API 呼び出し〜最終トークン受信まで
* **input_tokens / output_tokens**：プロバイダ報告またはトークナイザ推定
* **cost_usd**：`pricing` に基づき `input/1000*prompt_usd + output/1000*completion_usd`
* **status**：`ok` or `error`（例外・レート制限・タイムアウト等）

### 5.2 差分率（`eval.diff_rate`）

* 文字列の**トークン列**に分割（空白で naive / 必要なら BPE 互換）
* `diff_rate = levenshtein(tokens_a, tokens_b) / max(len_a, len_b)`（0=一致）
* **決定性検査**：同一条件 N 回（既定3）で中央値 `diff_rate` と `len_tokens` の **stdev** を算出

---

## 6. 実行モードと比較

### 6.1 実行モード

* **parallel**：複数プロバイダ/プロンプトを**並列**実行し、集計で比較
* **serial**：**直列**（例：短い要約→検証→再生成）のステップを 1 ランとして記録

  * `mode_steps`: 任意（serial のみ）。各ステップでメトリクスを記録し、親ランに集約。

### 6.2 比較ランナー（`/adapter/run_compare.py`）

* 入力：`providers/*.yaml`、`datasets/golden/tasks.jsonl`、繰り返し回数 `--repeat N`
* 機能：

  * 乱数・温度・top_p・max_tokens を固定して **決定性検査**
  * `budgets.yaml` の予算内で停止（`--allow-overrun` 無指定なら停止）
  * 結果を `/data/runs-metrics.jsonl` へ **追記**

---

## 7. レポート生成（B1）

### 7.1 ツール（`/tools/report/metrics_to_html.py`）

* 入力：`/data/runs-metrics.jsonl`、（任意）`/datasets/golden/baseline/*`
* 出力：`/reports/index.html`（単一ファイル、`.gitignore` 対象 — 生成手順は `docs/examples/llm-adapter/README.md`）
* 要件（最低限）：

  * **Overview**：総試行数、成功率（ok率）、平均/中央値 latency、合計/平均 cost
  * **比較表**：`provider, model, prompt_id, attempts, ok%, avg_latency, avg_cost, avg_diff_rate`
  * **グラフ**（簡易）：

    * latency ヒストグラム（プロバイダ別）
    * cost vs latency 散布図（色：provider、形：prompt）
  * **回帰ブロック**：`baseline vs 最新` の **合否/差分率**（B3 を参照）

### 7.2 GitHub Actions（nightly）

* ステップ：チェックアウト → Python セットアップ → 依存導入（pandas+任意の可視化） → `metrics_to_html.py` 実行 → **Artifact / Pages 公開**
* 受け入れ：**2プロバイダ×2プロンプト**以上で表・グラフが表示されること

---

## 8. ゴールデン & 回帰（B3）

### 8.1 概念

* **ゴールデン小データ**：10〜20件。軽量・判定可能。
* **baseline**：安定版の参照出力 or 判定ロジック。
* **最新**：現在のラン結果。
* 比較：`exact_match`（正規表現/JSON 等） or `diff_rate` 閾値で判定。

### 8.2 コマンド（例）

```
just golden
# 内部で: run_compare.py --repeat 1 --providers <set> --prompts golden
#        → metrics_to_html.py が baseline vs 最新 の結果をレポへ差し込み
```

### 8.3 受け入れ

* `index.html` に **回帰テーブル**が表示（Pass/Fail、diff_rate、原因メモ）
* `baseline` の更新は PR 経由（差分を人間が承認）

---

## 9. 決定性・再現性ガード（B2）

### 9.1 仕様

* **固定 seed**・`temperature`・`top_p` を providers.yaml で宣言
* **再試行**：`retries.max` 回（指数バックオフ）
* **品質ゲート**（providers.yaml→`quality_gates`）：

  * `determinism_diff_rate_max`（例：0.15）
  * `determinism_len_stdev_max`（例：8 tokens）

### 9.2 合否判定（決定性）

* 同一条件 N 回（既定3）で

  * `median(diff_rate) <= determinism_diff_rate_max` **かつ**
  * `stdev(len_tokens) <= determinism_len_stdev_max`
* NG の場合は `status=error, failure_kind=non_deterministic` を記録し、レポで警告。

---

## 10. 失敗分類（B4）

### 10.1 付与ルール

* `timeout`：`latency_ms` が `timeout_s` 超過 or 通信タイムアウト
* `provider_error`：HTTP 5xx/429、仕様準拠エラー（レート限界等）
* `parsing`：JSON/構文パース失敗、期待スキーマ不一致
* `guard_violation`：禁止記号、長さ制限、null 出力等の**事前ガード違反**
* `non_deterministic`：§9.2 の決定性ゲートに不合格

### 10.2 週次サマリ反映

* 上位3種別（件数）を**自動集計**し、`/docs/weekly-summary.md`（別仕様）へ反映

---

## 11. セキュリティ / プライバシ

* 認証は **環境変数**（`auth_env`）から取得。ログへ出力しない。
* 出力文は既定で **ハッシュ化**（`persist_output: false`）。必要時のみ保存を明示許可。
* 実験データに個人情報を含めない。必要に応じ**マスキング**。

---

## 12. パフォーマンス要件

* 2プロバイダ×2プロンプト×3反復の集計・HTML生成が**< 30秒**（開発機）
* `/data/runs-metrics.jsonl` は**追記型**で O(1) 書込、集計は pandas 等で数十万行まで実用

---

## 13. CLI 仕様（最小）

```
python adapter/run_compare.py \
  --providers adapter/config/providers/openai.yaml,adapter/config/providers/local_ollama.yaml \
  --prompts datasets/golden/tasks.jsonl \
  --repeat 3 --mode parallel

python tools/report/metrics_to_html.py \
  --metrics data/runs-metrics.jsonl \
  --golden datasets/golden \
  --out reports/index.html    # 生成物はコミットせず `.gitignore` 管理
```

---

## 14. テスト計画（v1 ミニマム）

* **単体**：

  * diff_rate 計算（境界値）／コスト算出（単価×トークン）
  * 失敗分類（timeout/parsing/guard_violation ルール）
* **結合**：

  * run_compare → JSONL 追記 → HTML 生成の通し
  * 決定性ゲート（OK/NG ケース）
* **E2E（CI）**：

  * nightly で 2×2×2 の小実験 → `index.html` を Artifact / Pages へ

---

## 15. 受け入れ基準（DoD）

* **B1**：`/reports/index.html` に **2プロバイダ×2プロンプト**の **latency / tokens / cost / diff率 / 失敗分類** が**表とグラフ**で表示される。
* **B2**：同条件反復で**決定性ゲート**評価が行われ、**95%同一結果**相当のしきい（§9.2）に従ってレポに**PASS/警告**が出る。
* **B3**：`just golden`（または同等コマンド）で **baseline vs 最新** の**回帰表**が HTML に差し込まれる。
* **B4**：`failure_kind` が記録され、**週次サマリ**に Top3 種別が反映される。

---

## 16. 将来拡張（Backlog）

* 文字列以外の**構造評価**（JSON スキーマ／関数的オラクル）
* **Pages のライブダッシュボード化**（フィルタ・検索）
* **コスト最適化ポリシー**（目標品質に対する最小コスト探索）
* **SQLite ストア**での期間クエリ高速化

---

> 本仕様は「最低限の実用」を優先し、**宣言的設定（YAML）**＋**追記型ログ（JSONL）**＋**単一HTML**で完結する。
> 実装は小さく始め、DoD（§15）を満たしたら段階的に拡張する。
