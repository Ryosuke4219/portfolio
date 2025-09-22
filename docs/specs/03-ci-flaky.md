# 仕様 #3：CI ログ解析 → フレーク検知

## 目的と価値
CI の JUnit ログから **flaky（fail→pass、pass→fail の遷移）**を自動抽出し、再実行や起票につなげる。

## 入力・出力
- 入力：`junit.xml`（複数ランの履歴・タイムスタンプ・ hostname など）。  
- 出力：`flaky-summary.json` / `flaky/index.html`（トップ N、再現条件、失敗ログ抜粋）。

## 受け入れ条件（AC）
- 同一テスト ID の時系列遷移を判定し、**信頼度スコア**を算出（例：連続失敗率/直近成功率）。  
- 「失敗の第一原因（first failing run）」と「直近成功 run」をリンク表示。  
- **再実行方針**（回数・間隔）をルール化して出力に添付。

## 非機能要件
- 10,000 ケース × 30 ラン分を 2 分未満で集計（ローカル基準）。  
- HTML レポートは Pages へ公開可能な静的生成物。

## リスクと緩和
- 時計ズレ/タイムゾーン → すべて UTC で記録し、UI でローカル変換。
- テスト名変更 → 固定 ID と `classname` の両方で**突合**。

## 分析手順
1. 過去 N ラン分の `junit.xml` を読み込み、`testsuite@timestamp` を UTC として正規化。
2. テスト ID（`classname#name`）ごとに時系列を構築し、成功/失敗の遷移を抽出。
3. 直近ランの状態と累積統計から信頼度スコアを算出。
4. flaky と判定されたケースを優先度順（影響度 × 発生頻度）に並べ替え。
5. HTML / JSON の両形式でレポート化し、Pages に配置。

## スコアリング指標例
| 指標 | 定義 | 用途 |
| --- | --- | --- |
| `stability_index` | 直近 5 回の成功率 | flaky か否かの一次判定 |
| `first_failure_at` | 初回失敗ランの timestamp | 回帰タイミングの特定 |
| `recovery_latency` | 失敗→成功までの経過時間 | 再実行ポリシーの調整 |
| `rerun_recommendation` | 自動再実行の回数・間隔 | CI 設計の入力値 |

## レポート構成（HTML）
```text
flaky/index.html
├─ Summary（テーブル：Top N flaky, スコア, 推奨対応）
├─ Timeline（Sparkline で pass/fail 遷移を可視化）
├─ Detail ページ
│   ├─ 失敗ログ抜粋（system-out / system-err）
│   └─ 再現条件（環境, branch, commit, retried?）
└─ Export（JSON, CSV ダウンロードリンク）
```
