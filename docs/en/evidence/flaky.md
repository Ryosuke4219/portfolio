---
layout: default
title: CI Flaky Analyzer (EN)
description: Highlights of the CLI that detects flaky tests and automates reporting from CI logs
---

> [日本語版]({{ '/evidence/flaky.html' | relative_url }})

# CI Flaky Analyzer

The CLI continuously ingests JUnit-formatted test results, scores flaky behavior, and visualizes it. It ships with npm scripts for CI integration and automates weekly reporting.

## Highlights

- Separates CLI subcommands such as `flaky parse`, `flaky analyze`, and `flaky issue` to cover collection through reporting.
- Streams large JUnit XML files and persists analysis as JSONL and HTML.
- The `weekly` command updates `docs/weekly-summary.md` to keep knowledge sharing automatic.

## Key Artifacts

- [README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/README.md) — Setup instructions and command list.
- [config/flaky.yml](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/config/flaky.yml) — Scoring and window configuration.
- [demo/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/03-ci-flaky/demo) — Sample JUnit logs and HTML report inputs.
- [out/index.html](https://github.com/Ryosuke4219/portfolio/blob/main/projects/03-ci-flaky/out/index.html) — Visualization of the analysis results.

## How to Reproduce

1. Run `npm install` inside `projects/03-ci-flaky/`.
2. For demo logs, run `npm run demo:parse` → `npm run demo:analyze` and inspect the generated `out/` directory.
3. In production, feed CI JUnit XML files and wire `npm run ci:analyze` or `npm run ci:issue` into the workflow.

## Next Steps

- Connect to Slack webhooks or the GitHub Issues API to take `flaky issue` from dry-run to production ticketing.
- Export the CSV output (`out/summary.csv`) to BI tools for long-term trend analysis.
- See the [weekly summary list]({{ '/weekly-summary.html' | relative_url }}) for automation updates.
