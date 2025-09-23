# Defect Report — テンプレート

## 1. 概要
- 事象要約: <1行>
- 重大度/優先度: <Critical/High/Medium/Low> / <P0..P3>
- 影響範囲: <対象機能/利用者/頻度>
- 起票日: <YYYY-MM-DD>

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

---

# Defect Report — BUG-2025-003

## 1. 概要
- 事象要約: LLM生成E2Eでダッシュボード遷移時にスピナーが消えずタイムアウトする。
- 重大度/優先度: High / P1
- 影響範囲: ポートフォリオE2Eシナリオのログイン後処理（再現率60%）。
- 起票日: 2025-03-19

## 2. 再現手順
1) `npm run test:e2e` を実行し、`tests/generated/login.spec.ts` の `should login with dashboard` ケースを対象にする。
2) テスト完了を待機する。
- 期待値: 認証後3秒以内にダッシュボードが表示され、`data-testid="dashboard-card"` を検出できる。
- 実際値: スピナーが永続化し、`locator.waitFor()` が60秒でタイムアウト。
- 証拠: `../test-results/results.json`（`npm run test:e2e` 実行時に生成されるスタブ実行ログ。リポジトリには含めない）

## 3. 原因分析（5Whys/図解は任意）
- 直接原因: E2Eテストがモーダルクローズを待たずにダッシュボード遷移を開始した。
- 真因: 生成テンプレートの共通 `waitForIdle` ヘルパーが `spinner` の非表示条件を監視していなかった。
- 関連 Failure Kind（任意）: timeout

## 4. 是正/予防・影響評価
- 是正（Corrective）: `waitForIdle` に `page.getByTestId('spinner').waitFor({ state: 'hidden' })` を追加し、全シナリオへ反映。影響はログイン/検索系シナリオ。
- 予防（Preventive）: 週次CIで `spinner` ログを収集し、遅延増加を検知する監視を追加。
- リスク/副作用: タイムアウト待ち時間が増加しCI時間が+30秒となる可能性。

## 5. 検証・完了条件（DoD）
- 再現テスト: `T-02-E2E-LOGIN-INVALID` と `T-02-E2E-LOGIN-VALID` を回し再発しないこと。
- 回帰: `T-03-FLAKY-RANK` で新規Flaky登録が増加していないこと。
- 閉塞条件を満たす証跡: `../projects/03-ci-flaky/out/index.html`（`npm run ci:analyze` で生成、詳細は `../docs/examples/ci-flaky/README.md`）
