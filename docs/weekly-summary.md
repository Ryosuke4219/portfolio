---
layout: default
title: Weekly QA Summary — 2025-09-22
description: 直近7日間のQA状況サマリ
---

# Weekly QA Summary — 2025-09-22

## Overview (last 7 days)
- TotalTests: 5
- PassRate: 40.00%
- NewDefects: 0
- TopFailureKinds: timeout 1 / guard_violation 1 / infra 1

## Top Flaky (score)
| Rank | Canonical ID | Attempts | p_fail | Score |
|-----:|--------------|---------:|------:|------:|
| 1 | ui-e2e.LoginFlow.spec.should show error for invalid user | 8 | 0.38 | 0.71 |
| 2 | ui-e2e.LoginFlow.spec.should login with valid user | 8 | 0.25 | 0.58 |
| 3 | api-report.ReportJob.test.generates flaky summary | 5 | 0.20 | 0.46 |

## Week-over-Week
- PassRate Δ: -26.67pp
- Entered: ui-e2e.LoginFlow.spec.should login with valid user
- Exited: ui-e2e.Dashboard.spec.should render analytics widgets

## Notes
- PassRate WoW: -26.67pp (prev 66.67%).
- Top Flaky 新規: ui-e2e.LoginFlow.spec.should login with valid user
- Top Flaky 離脱: ui-e2e.Dashboard.spec.should render analytics widgets

<details><summary>Method</summary>
データソース: projects/03-ci-flaky/data/runs.jsonl / projects/03-ci-flaky/out/flaky_rank.csv / 欠陥: docs/defect-report-sample.md
※ `runs.jsonl` と `out/*.csv` は `npm run ci:analyze`（`just test` 内）で再生成され、リポジトリには含めない。生成手順は `docs/examples/ci-flaky/README.md` を参照。
期間: 直近7日 / 比較対象: その前の7日
再計算: 毎週月曜 09:00 JST (GitHub Actions)
</details>

