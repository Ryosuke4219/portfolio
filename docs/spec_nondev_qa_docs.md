# 非開発QAドキュメント資産 — 要件・仕様（v1.0）

## 0. 目的

- 面接・実務双方で通用する QA 成果物（文書＋最小自動化）を常時提示できる状態にする。
- 3分で意図を把握、10分で再現／評価できる情報密度に標準化する。

---

## 1. 対象範囲（E1〜E4）

- **E1**: テスト計画（A4・1枚）
- **E2**: RTM（要求⇄テスト・CSV）
- **E3**: 欠陥レポ雛形＋例（Markdown）
- **E4**: 週次自動サマリ（Markdown／GitHub Actionsで自動更新）

---

## 2. 共通非機能要件（NFR）

- 読了時間: **3分以内**（E1、E4）
- ファイルサイズ: 1ドキュメント **200KB以下**（画像リンクは外部 or `/assets`）
- 再現性: リポ内の **相対リンク**で他成果物へ遷移可能
- バージョン管理: コミット単位で更新履歴が追える（PRで差分可視）
- 言語: 日本語（必要に応じ英文1行サマリ可）

---

## 3. 成果物仕様

### E1. テスト計画（`/docs/test-plan.md`）

**目的**: スコープ／優先度／リスク／完了条件の明確化（A4・1枚）

#### 固定セクション

1. **目的（Goal）**: 検証で何を証明／否定したいか（2–3行）
2. **対象と範囲（Scope / Out of Scope）**: 対象機能・環境、除外（各5行以内）
3. **品質基準（Quality Gates）**: 受け入れ条件（例: PassRate ≥ 95%、Critical欠陥=0）
4. **観点（Test Ideas）**: 主要観点を箇条書き（5〜8項目）
5. **リスクと対策（Risk & Mitigation）**: Top3（各1行）
6. **実行体制（Roles / Env）**: 担当・環境・データソース（1段落）
7. **トレーサビリティ（Traceability）**: RTMへのリンク（相対パス）
8. **完了定義（DoD）**: 計画の完了条件（3〜5行）

#### テンプレート

```md
# Test Plan — <対象名> v1.0

## 1. 目的（Goal）
- <この検証で証明/否定したいことを2–3行>

## 2. 対象と範囲（Scope / Out of Scope）
- Scope: <対象機能/画面/シナリオ/データ/環境>
- Out of Scope: <今回除外する要素>

## 3. 品質基準（Quality Gates）
- PassRate >= <95%> / Critical欠陥=0 / a11y重大=0 / FlakyScore上位< N 限定 など

## 4. 観点（Test Ideas）
- <主要観点1>
- <主要観点2>
- ...

## 5. リスクと対策（Top3）
- R1: <リスク> → M1: <対策>
- R2: ...
- R3: ...

## 6. 実行体制（Roles / Env / Data）
- Roles: QA=<name>, SDET=<name>
- Env: <環境> / Data: <ソース・前提>

## 7. トレーサビリティ
- RTM: `./rtm.csv`（Req⇄Testの対応）

## 8. 完了定義（DoD）
- <この計画が完了と言える状態を3–5行で明示>
```

**DoD**

- セクションを空欄なく記述し、A4相当1枚に収まる
- RTMへのリンクを含み、Quality Gatesを数値基準で表現する

---

### E2. RTM（`/docs/rtm.csv`）

**目的**: 要求⇄テストのトレーサビリティ証拠を提供

#### CSVカラム

- `RequirementID`
- `RequirementTitle`
- `Priority`（H/M/L）
- `Risk`（H/M/L）
- `TestID`
- `Project`（01/02/03…など）
- `TestType`（E2E/Unit/Integration/a11y/Visual…）
- `Status`（Planned/Implemented/Deprecated）
- `Coverage`（Full/Partial/NA）
- `EvidenceLink`（相対リンク）
- `LastRunAt`（ISO日付）
- `Owner`

#### サンプル

```csv
RequirementID,RequirementTitle,Priority,Risk,TestID,Project,TestType,Status,Coverage,EvidenceLink,LastRunAt,Owner
REQ-LOGIN-001,正しい資格情報でログインできる,H,M,T-02-E2E-LOGIN-VALID,02,E2E,Implemented,Full,../projects/02-e2e/README.md#login,2025-09-20,ryo
REQ-LOGIN-002,パスワード誤り時はエラー表示,H,M,T-02-E2E-LOGIN-INVALID,02,E2E,Implemented,Full,../projects/02-e2e/README.md#invalid,2025-09-20,ryo
REQ-A11Y-001,フォーム要素に適切なラベルがある,M,M,T-02-E2E-A11Y-LABEL,02,a11y,Implemented,Partial,../projects/02-e2e/README.md#a11y,2025-09-20,ryo
REQ-REPORT-001,JUnitを解析して失敗傾向を把握できる,M,M,T-03-REPORT-SUMMARY,03,Integration,Implemented,Full,../projects/03-ci-flaky/README.md#summary,2025-09-21,ryo
```

**DoD**

- 10行以上の対応を記載
- `01〜03` のテストIDを最低10件マッピング
- `EvidenceLink` をすべて有効にする

---

### E3. 欠陥レポ雛形＋例（`/docs/defect-report-sample.md`）

**目的**: 原因分析〜是正/予防を定型で示す

#### テンプレート

```md
# Defect Report — <ID例: BUG-2025-001>

## 1. 概要
- 事象要約: <1行>
- 重大度/優先度: <Critical/High/Medium/Low> / <P0..P3>
- 影響範囲: <対象機能/利用者/頻度>

## 2. 再現手順
1) <手順>
2) <期待/実際>
- 期待値: <…>
- 実際値: <…>
- 証拠: <ログ/スクショ/リンク>

## 3. 原因分析（5Whys/図解は任意）
- 直接原因: <…>
- 真因: <…>
- 関連 Failure Kind（任意）: timeout / guard_violation / infra など

## 4. 是正/予防・影響評価
- 是正（Corrective）: <fix内容・影響範囲・リリース計画>
- 予防（Preventive）: <再発防止・ガード>
- リスク/副作用: <…>

## 5. 検証・完了条件（DoD）
- 再現テスト: <手順 or テストID>
- 回帰: <関連テスト>
- 閉塞条件を満たす証跡: <リンク>
```

**DoD**

- テンプレートに加え、具体例を最低1件記載
- 証拠リンク（ログ/スクショ/CI結果）を有効にする

---

### E4. 週次自動サマリ（`/docs/weekly-summary.md`）

**目的**: 通過率／新規欠陥／Top失敗原因を自動集計し継続運用の姿を提示

#### 入力データ

- `projects/03-ci-flaky/data/runs.jsonl`（`npm run ci:analyze` / `just test` で生成、リポジトリには含めない）
- `projects/03-ci-flaky/out/flaky_rank.csv`（同上、詳細は `../docs/examples/ci-flaky/README.md`）
- 必要に応じて `junit/**/*.xml`

#### 指標（過去7日, デフォルト）

- `TotalTests`: 試行数（skipped除外）
- `PassRate`: pass / (pass+fail+error)
- `NewDefects`: 7日以内に作成された欠陥件数
- `TopFailureKinds`: `failure_kind` 上位3
- `TopFlaky`: score上位5（ID, score, attempts, p_fail）

#### 出力テンプレート

```md
# Weekly QA Summary — <YYYY-MM-DD>

## Overview (last 7 days)
- TotalTests: <N>
- PassRate: <xx.xx%>
- NewDefects: <N>
- TopFailureKinds: <timeout N> / <guard_violation M> / <infra K>

## Top Flaky (score)
| Rank | Canonical ID | Attempts | p_fail | Score |
|-----:|--------------|---------:|------:|------:|
| 1 | <id> | 20 | 0.40 | 0.74 |
| ... | ... | ... | ... | ... |

## Notes
- <任意メモ：改善・観測事項・次アクション>

<details><summary>Method</summary>
データソース: runs.jsonl, flaky_rank.csv / 期間: 直近7日 / 再計算: 毎週月曜 09:00 JST
※ `runs.jsonl` と `flaky_rank.csv` は `npm run ci:analyze` で生成する一時ファイル。コミット対象外のため `docs/examples/ci-flaky/README.md` を参照し再生成する。
</details>
```

#### 自動生成要件

- 週1回（例: 月曜 09:00 JST）に再生成しコミット
- 過去2週分の差分（PassRate増減、TopFlaky入れ替わり）を簡易表示
- 入力ファイルが存在しない場合でも失敗せず、前回内容を保持したまま更新日時のみ差し替え

#### CLI仕様

```
weekly_summary.py
  --runs <path to runs.jsonl>
  --flaky <path to flaky_rank.csv>   # 生成手順: docs/examples/ci-flaky/README.md
  --out  <path to weekly-summary.md>
  --days <int, default=7>
```

**DoD**

- `docs/weekly-summary.md` を自動生成し直近2週の差分を確認可能
- 入力欠如時もエラーにならず、直前の内容を保持した上で更新日時を差し替える

---

## 4. 依存関係・リンク規約

- すべてのリンクは相対パス
- 画像やGIFは `/assets` 配下に格納（1枚1MB以下推奨）

---

## 5. セキュリティ・情報管理

- ワークフロー内で機密トークンを出力しない
- 収集・公開するログから個人情報・秘匿URLをマスクする

---

## 6. 受け入れ基準（総合）

- **E1**: A4・1枚、数値基準付きQuality Gates、RTMリンク有効
- **E2**: 10行以上、`01〜03` のテストIDを10件以上、EvidenceLink有効
- **E3**: テンプレ＋具体例1件、証拠リンク有効
- **E4**: Actionsで週次自動更新、直近2週差分が確認できる

---

## 7. 将来拡張（任意）

- RTMから欠落テスト警告を出すスクリプト
- weekly-summaryへトレンドグラフ
- 欠陥レポの自動起票（GitHub Issues API 等）

---

### 付録A: 推奨配置

```
/docs/
  ├─ spec_nondev_qa_docs.md
  ├─ test-plan.md
  ├─ rtm.csv
  ├─ defect-report-sample.md
  ├─ weekly-summary.md
/tools/
  └─ weekly_summary.py
/assets/
  └─ ...
```
