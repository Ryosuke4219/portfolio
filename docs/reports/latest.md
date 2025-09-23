---
layout: default
title: QA Reliability Snapshot — 2025-09-23
description: CI pass rate and flaky ranking (auto-generated)
---

# QA Reliability Snapshot — 2025-09-23

- Window: Last 7 days
- Data Last Updated: 2025-09-21T03:44:09Z

## KPI
| 指標 | 値 |
|------|----|
| Pass Rate | 40.00% (2/5) |
| Failures | 2 |
| Errors | 1 |
| Top Failure Kinds | timeout 1 / guard_violation 1 / infra 1 |
| ソースJSON | [latest.json](./latest.json) |

## Top Flaky Tests
| Rank | Canonical ID | Attempts | p_fail | Score |
|-----:|--------------|---------:|------:|------:|
| 1 | ui-e2e.LoginFlow.spec.should show error for invalid user | 8 | 0.38 | 0.71 |
| 2 | ui-e2e.LoginFlow.spec.should login with valid user | 8 | 0.25 | 0.58 |
| 3 | api-report.ReportJob.test.generates flaky summary | 5 | 0.20 | 0.46 |

<details><summary>Generation</summary>
Source: runs=projects/03-ci-flaky/data/runs.jsonl / flaky=projects/03-ci-flaky/data/flaky_rank.csv
Window: 7 days / Executions: 5
Automation: tools/generate_ci_report.py (GitHub Actions)
</details>

