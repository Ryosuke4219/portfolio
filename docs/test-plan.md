# Test Plan — Portfolio QA Visibility v1.0

## 1. 目的（Goal）
- ポートフォリオ内のQA成果物が最新データに基づき一貫して更新されていることを確認する。
- 週次サマリ、RTM、欠陥レポがリンク切れや欠落なく参照できることを証明する。
- 自動集計スクリプトの運用準備完了を確認し、面談・評価時に再現できる状態を確保する。

## 2. 対象と範囲（Scope / Out of Scope）
- Scope: `/docs` 配下のQA資産（テスト計画、RTM、欠陥レポ、週次サマリ）、`/tools/weekly_summary.py`、サンプルデータ、GitHub Actionsワークフロー。
- Out of Scope: 実際の本番サービス機能検証、04-shadow プロジェクトの詳細仕様、UIデモの視覚確認。

## 3. 品質基準（Quality Gates）
- PassRate >= 96%（週次サマリに記載されたテスト結果ベース）。
- Critical欠陥 = 0 / Major欠陥 <= 1。
- RTMリンク有効率 100%、自動サマリ生成ジョブ成功率 100%（直近2回）。

## 4. 観点（Test Ideas）
- 文書整合性: 各成果物間のリンク・バージョン整合性。
- トレーサビリティ: RTMとテスト計画の要求対応状況。
- 欠陥レポ品質: テンプレ適用、証跡リンクの有効性。
- 自動化: weekly_summary スクリプトの入出力、エラー時のフォールバック。
- データ品質: runs.jsonl / flaky_rank.csv の期間・フォーマット妥当性。
- ガバナンス: GitHub Actionsのスケジュール、権限、コミットポリシー。

## 5. リスクと対策（Top3）
- R1: データ欠損で週次サマリが空になる → M1: スクリプトで過去出力保持とエラーログ監視。
- R2: RTMリンクが将来のリポ構造変更で無効化 → M2: 週次CIでリンクチェッカを追加検討。
- R3: 欠陥レポ例が最新傾向を反映しない → M3: 月次レビューで例示更新をタスク化。

## 6. 実行体制（Roles / Env / Data）
- Roles: QA=Y. Sato, SDET=K. Arai、Reviewer=M. Chen。
- Env: GitHub Codespaces / Node.js 20 / Python 3.11。
- Data: `projects/03-ci-flaky/data/runs.jsonl`、`projects/03-ci-flaky/out/flaky_rank.csv`、欠陥レポ証跡。

## 7. トレーサビリティ
- RTM: `./rtm.csv`（Req⇄Testの対応）

## 8. 完了定義（DoD）
- すべての成果物が本計画記載のQuality Gatesを満たし、レビュー承認済みである。
- 自動サマリが最新日付で更新され、週次比較差分が記載されている。
- 欠陥レポ例の是正・予防がRTMのカバレッジと矛盾しないことを確認済み。
- GitHub Actionsワークフローがdry-runで成功し、次回スケジュールに備えられている。
