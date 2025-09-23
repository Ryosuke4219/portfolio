# Flaky Analyzer — 要件・仕様（v1.0）

## 0. 目的（Purpose）

CI/E2E実行で生成される **JUnit 形式のテスト結果** を継続収集し、
**Flaky（試行により合否が揺れる）テスト**を **定量的に検出・スコア化・可視化・起票** できる最小実用モジュールを提供する。

> ゴール：5分で概況把握、10分で改善着手（隔離・修正・再発防止）まで導線をつなぐ。

---

## 1. スコープ / 非スコープ

### スコープ

* JUnit XML の取り込み（単発ファイル／ディレクトリ／アーティファクト展開済みパス）
* **ストリーミング解析** による大規模XML（100MB級）への耐性
* テスト識別子の**正規化（canonical id）**
* **連続実行履歴** の集計（JSONL ストア）
* **Flaky スコア**算出とランキング出力（CSV/JSON/HTML）
* **失敗分類（failure_kind）** の付与（timeout / nondeterministic / parsing / guard_violation / provider_error / infra 等）
* **GitHub 自動起票（Dry-run対応）** とテンプレ本文生成
* 週次/ナイトリーの**自動サマリ生成**（Markdown/HTML）

### 非スコープ（v1.0）

* xUnit, NUnit 等、JUnit以外のフォーマット（将来の拡張点）
* 外部SaaS（ReportPortal, Allure）へのアップロード（ミニマム例以外）
* DBサーバ（Postgres等）への常設保存（v1は**ファイルベースJSONL**）

---

## 2. 利用者・ユースケース

* **QA（非開発）**：週次レポでの状況把握／修正優先度の根拠づけ
* **SDET/SET**：Flakyの**自動検出→隔離→修正→回帰**のループ運用
* **EM/PM**：**件数推移とインパクト**の指標化（失敗密度・再現率・影響時間）

代表ユースケース：

1. CI 完了後に Analyzer を実行 → **TopN Flaky** と **推定影響時間**をSlack/PRコメントへ
2. 週次で **新規Flaky** と **解消済み** を差分でレポート
3. スコア閾値超のテストを自動で **起票テンプレ**化（ラベル: `flaky`, `test`, `area/*`）

---

## 3. 定義・用語

* **Canonical Test ID**：`<suite>.<class>.<name>[<params>]`

  * 可能なら `file`/`classname`/`package` 属性を利用し一意化。
  * パラメータ化テスト（例：`testFoo[param1=42]`）は角括弧付き表記へ正規化。
* **Attempt**：特定のCIラン内での当該テスト1回の実行
* **Fail/Pass**：`<failure|error|skipped>` 以外は Pass とみなす（skippedは別集計）
* **Window**：直近 `W` ラン（デフォルト 20）での履歴区間
* **Flaky**：Window 内で **Pass と Fail が双方存在** し、下式の **FlakyScore >= T** を満たすもの

---

## 4. 入出力（I/O）

### 入力

* **JUnit XML**：ファイルパス、ディレクトリ（`**/*.xml` グロブ）、stdin のいずれか
* **メタ**：`run_id`（CIのSHA/Run番号）、`timestamp`, `branch`, `commit`, `actor`, `duration_total_ms`

### 保存（履歴ストア）

* **JSONL**（1 Attempt = 1 行）：`/projects/03-ci-flaky/data/runs.jsonl`

  * ローテーション：10MB 超で `runs_YYYYMMDD.jsonl` に切替

### 出力

* **集計サマリ（JSON/CSV）**：`/projects/03-ci-flaky/out/summary.json|csv`
* **Flaky ランキング（CSV/JSON）**：`/out/flaky_rank.csv|json`
* **HTML レポ（単一ファイル）**：`/out/index.html`（テーブル＋簡易チャート）
* **週次Markdown**：`/docs/weekly-summary.md`
* **GitHub起票プレビュー**：`/out/issues/*.md`（Dry-run時）

> ℹ️ `/out/*.html|csv|json` は解析コマンド実行時に生成される成果物で、リポジトリには含めていません。CI アーティファクトやローカル実行で適宜取得します。

---

## 5. データモデル（JSONL スキーマ）

```json
{
  "run_id": "gh_123456789",
  "ts": "2025-09-22T12:34:56Z",
  "branch": "main",
  "commit": "a1b2c3d",
  "suite": "ui-e2e",
  "class": "LoginFlow.spec",
  "name": "should login with valid user",
  "params": "browser=chromium",
  "canonical_id": "ui-e2e.LoginFlow.spec.should login with valid user[browser=chromium]",
  "status": "pass",              // pass|fail|error|skipped
  "duration_ms": 1234,
  "failure_kind": null,          // timeout|nondeterministic|parsing|guard_violation|provider_error|infra|null
  "failure_signature": null,     // 先頭N行の正規化ハッシュ（同一原因判定用）
  "retries": 0,                  // CI側での自動リトライ回数（分かる範囲）
  "ci_meta": { "actor": "bot", "workflow": "portfolio-ci" }
}
```

---

## 6. Flakyスコア（定義と算出）

### 6.1 指標（Window=W ラン）

* `attempts`：総試行数（skipped 除く）
* `fails`：失敗回数（fail|error）
* `passes`：成功回数
* `p_fail = fails / attempts`
* **Intermittency**：`I = 2 * min(passes, fails) / attempts`（0〜1、双方出現で高い）
* **RecencyWeight**：指数減衰重み `w(t) = exp(-λ * age)`（デフォルト λ=0.1、最新ほど高重み）
* **Impact**：平均 `duration_ms` の対数正規化 `impact = log1p(avg_duration_ms) / log1p(600000)`（\~10分を上限）

### 6.2 スコア式（デフォルト重み）

```
FlakyScore = 0.50 * I
           + 0.30 * p_fail
           + 0.15 * RecencyWeighted(p_fail)
           + 0.05 * Impact
```

* **判定閾値**：`T = 0.60`（YAMLで変更可能）
* **新規Flaky**：直近 `K=5` ラン内に初検出された Flaky

### 6.3 失敗分類（failure_kind）

* timeout：テスト所要が suite 95pct×倍率 を超過（YAML `timeout_factor`）
* nondeterministic：同一 `failure_signature` が一定割合未満で散在
* parsing：HTML/JSON 等の構文エラー（スタック正規化で検出）
* guard_violation：テストガード（要素欠落・命名重複）での失敗
* provider_error/infra：ネットワーク・依存API・CIインフラ起因（キーワードルール）

---

## 7. 設定（YAML）

`/projects/03-ci-flaky/config/flaky.yml`

```yaml
window: 20
threshold: 0.60
new_flaky_window: 5
weights:
  intermittency: 0.50
  p_fail: 0.30
  recency: 0.15
  impact: 0.05
timeout_factor: 3.0           # 95pct * factor を超えたら timeout
impact_baseline_ms: 600000     # 10分
output:
  top_n: 50
  formats: [csv, json, html]
issue:
  enabled: true
  dry_run: true
  repo: "Ryosuke4219/portfolio"
  labels: ["flaky", "test"]
  assignees: []
  dedupe_by: "failure_signature"   # or "canonical_id"
paths:
  input: "./junit"                 # CIアーティファクト解凍先
  store: "./data/runs.jsonl"
  out: "./out"
```

---

## 8. CLI 仕様

### コマンド郡（Node/TS or Python どちらでも、既存構成に合わせて実装）

```
flaky parse --input ./junit --run-id gh_${GITHUB_RUN_ID} --branch $BRANCH --commit $SHA
flaky analyze --config ./config/flaky.yml
flaky report --format html --open
flaky issue --top-n 10 --dry-run
flaky weekly --since 14d
```

### 代表フロー

1. `parse`：JUnit を **ストリーミング**で読んで JSONL へ追記
2. `analyze`：Window 集計→スコア算出→TopN を CSV/JSON/HTML 出力
3. `report`：HTML レポ生成（テーブル、Sparkline、失敗種別円グラフ）
4. `issue`：閾値超のテストをテンプレ化（Dry-runで `.md` 作成）
5. `weekly`：今週の **新規/解消** を `/docs/weekly-summary.md` に追記

---

## 9. HTML レポ（最低限の要件）

* **Overview**：総テスト数 / Flaky 件数 / 新規Flaky / 最多失敗種別
* **TopN テーブル**：`rank, canonical_id, attempts, pass/fail, p_fail, I, score, avg_dur, failure_top_k`
* **トレンド**：直近Nランでの `p_fail` Sparkline
* **リンク**：各テスト行 → 直近 run のログ断片（failure_signature 抜粋）

---

## 10. GitHub Actions 連携（概要）

* `jobs.flaky`：

  1. アーティファクト展開 → `flaky parse`
  2. `flaky analyze && flaky report`
  3. 成果物を `actions/upload-artifact`（`flaky-report`）
  4. `issue.enabled && !dry_run` のとき `flaky issue`
  5. 週次（cron）で `flaky weekly` 実行、`/docs/weekly-summary.md` をコミット（Botユーザー）

---

## 11. パフォーマンス要件

* **100MB** のJUnit XML を **<3分 / <300MB RSS** で解析（開発PC/CI中位ランナー目安）
* JSONL 追記は **ロック制御**で破損防止（単一ジョブ想定／将来はファイルローテ）
* HTML レポ生成は **<30秒**（TopN=100 まで）

---

## 12. 例外・エラーハンドリング

* 破損XML：該当 run_id を **無視**し、警告ログ＋`parsing` 失敗としてカウント
* 属性欠落（classnameなど）：`suite`/`file` から推定、最後は `unknown` 埋め
* 同名衝突：`canonical_id` の生成時に **パス情報**を優先
* 入力なし：`analyze` は**前回の集計結果**をそのまま再出力（終了コード 0）

---

## 13. テスト計画（v1 ミニマム）

### 単体

* 典型XML（小）：OK／空／壊れかけ／巨大属性値
* 速度テスト：100MB 疑似JUnit（生成器同梱）
* 正規化：パラメトリック命名／クラス名欠損／ファイル名のみ

### 結合

* `parse→analyze→report` の通し動作
* Window=1/5/20 のスコア変化（期待値テーブル）
* 失敗種別の分類ルール（timeout/guard_violation/infra など）

### E2E（CI）

* GitHub Actions での nightly 実行 → Artifact に `index.html` 出力
* `dry_run issue` が `/out/issues/*.md` を生成

---

## 14. 受け入れ基準（DoD）

* コマンド 5種が README の例通りに動作
* 100MB JUnit を所定時間・メモリ内で解析（CI ログに実測値を残す）
* `summary.json / flaky_rank.csv / index.html / weekly-summary.md` が生成
* `threshold` を変更するとランキングが反映
* `dry_run issue` でテンプレが作成され、**重複起票の抑止（signature重複）**が効く

---

## 15. セキュリティ / ライセンス

* 入力ファイルは信頼境界外：**XML外部実体（XXE）禁止**の設定でパース（ストリーミング時も同様）
* 機密情報（トークン等）は環境変数で供給、ログに出力しない
* ライセンスは **MIT** を推奨

---

## 16. 将来拡張（Backlog）

* xUnit/NUnit など他フォーマット対応
* SQLite ストア（期間集計を高速化）
* Allure/ReportPortal へのアップロードオプション
* 「自動隔離（quarantine）」のサンプル PR 生成
* 変化点検出（CUSUM）での異常検知

---

## 付録A：出力サンプル（CSVの先頭行）

```
rank,canonical_id,attempts,passes,fails,p_fail,intermittency,recency,impact,score,avg_duration_ms,failure_top_k
1,ui-e2e.LoginFlow.spec.should login with valid user[browser=chromium],20,14,6,0.30,0.60,0.18,0.12,0.57,1450,"timeout(3)|guard_violation(2)|infra(1)"
```

## 付録B：起票テンプレ（Markdown）

```md
# Flaky: ui-e2e.LoginFlow.spec.should login with valid user[browser=chromium]

- Score: 0.74 (T=0.60)
- Attempts: 20 (Pass 12 / Fail 8), p_fail=0.40, I=0.80
- Avg Duration: 1.45s
- Failure kinds: timeout(5), guard_violation(2), infra(1)
- Recent runs: gh_12345, gh_12346, gh_12347

## Suspected Cause
- Timeout > suite 95pct * 3.0
- Element missing intermittently on first render

## Next Actions
- [ ] Add data-testid, stabilize selector
- [ ] Increase wait on network idle or mock API
- [ ] Add retry(1) only for known infra flakiness

/label: flaky, test
```

---

この仕様目的は、**非開発QA**には数値・文書・改善導線で“使える”を提示でき、**SDET**にはストリーミング解析・スコア式・CI連携で“運べる実装”の提示となります。
