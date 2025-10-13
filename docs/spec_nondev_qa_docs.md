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

**目的**: LLM Adapter の失敗傾向・HTTP 障害を自動集計し継続運用の姿を提示

#### 入力データ

- `artifacts/runs-metrics.jsonl`（`just report` / テレメトリ収集フローで生成）
- 任意: OpenRouter HTTP 失敗率などメタ情報（`runs-metrics.jsonl` に含まれる）

#### 集計項目

- `FailureTotal`: 失敗総数（`failure_kind` が付与されたイベントの件数）
- `FailureSummary`: 失敗種別ごとの上位3件（rank, kind, count）
- `OpenRouterHttpFailures`: OpenRouter プロバイダーで発生した HTTP 障害（RateLimit/Retriable の件数・割合）

#### 出力テンプレート

```md
# LLM Adapter 週次サマリ

## <YYYY-MM-DD> 時点の失敗サマリ
- 失敗総数: <N>  # 失敗が無い場合: 「失敗は記録されていません。」

| Rank | Failure Kind | Count |
| ---: | :----------- | ----: |
| 1 | <failure_kind> | <count> |
| ... | ... | ... |

### OpenRouter HTTP Failures  # 対象データが無い場合はセクション非表示

| Rank | 種別 | Count | Rate% |
| ---: | :---- | ----: | ----: |
| 1 | <category or label> | <count> | <rate> |
```

<details><summary>Method</summary>
`just weekly-summary` が `PYTHONPATH=projects/04-llm-adapter` で `tools.report.metrics.data` を用い、
`artifacts/runs-metrics.jsonl` から失敗種別サマリと OpenRouter HTTP 失敗を抽出し、
`tools.report.metrics.weekly_summary.update_weekly_summary` へ渡して Markdown を追記する。
生成ファイルは既存エントリ（`## <日付>`）を保持したまま、最新日付のブロックを末尾に追加する。
</details>

#### 自動生成要件

- 週1回（例: 月曜 09:00 JST）に `just weekly-summary` を実行しコミット
- `docs/weekly-summary.md` 末尾に最新日付のブロックを追加し、過去ブロックは維持
- `artifacts/runs-metrics.jsonl` が無い場合も失敗せず、「失敗は記録されていません。」と記録

#### CLI仕様

```
just weekly-summary
  # 内部で tools.report.metrics.data / weekly_summary を呼び出し、
  # artifacts/runs-metrics.jsonl → docs/weekly-summary.md を更新

python -m tools.report.metrics.cli \
  --metrics artifacts/runs-metrics.jsonl \
  --out reports/index.html \
  --weekly-summary docs/weekly-summary.md
```

**DoD**

- `docs/weekly-summary.md` に `# LLM Adapter 週次サマリ` が存在し、末尾ブロックが `## <YYYY-MM-DD> 時点の失敗サマリ`
- 失敗があれば順位付き表、無ければ「失敗は記録されていません。」を出力
- OpenRouter HTTP 失敗が存在する場合は `### OpenRouter HTTP Failures` 表を含む
- 入力欠如時もエラーにならず、最新ブロックが追加される

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
- **E4**: Actionsで週次自動更新し、最新ブロックに失敗サマリ／HTTP障害を記録

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
/projects/04-llm-adapter/tools/report/metrics/
  ├─ cli.py
  └─ weekly_summary.py
/assets/
  └─ ...
```
