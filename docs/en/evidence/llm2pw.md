---
layout: default
title: LLM to Playwright (EN)
description: Highlights of the PoC that expands acceptance criteria and outputs Playwright tests automatically
---

> [日本語版]({{ '/evidence/llm2pw.html' | relative_url }})

# LLM to Playwright

This proof of concept lets an LLM enrich acceptance criteria and convert them into Playwright test code. It demonstrates a robust selector strategy, a11y scanning, and data-driven execution in a compact package.

## Highlights

- Prioritizes <code>data-testid</code> selectors with ARIA / role-based fallbacks as documented guidelines.
- Auto-generates sample tests under `tests/generated/` including snapshots and accessibility rules.
- Loops through data files (JSON / CSV) to produce multiple cases, keeping maintenance to simple data edits.

## Key Artifacts

- [tests/generated/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/02-llm-to-playwright/tests/generated) — Auto-generated Playwright suites.
- [tests/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/tests/README.md) — Notes on selectors, snapshots, and a11y policy.
- [blueprint.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/blueprint.sample.json) — Sample source data enriched by the LLM.
- [scripts/generate-tests.mjs](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-llm-to-playwright/scripts/generate-tests.mjs) — Driver script orchestrating LLM calls and code generation.

## How to Reproduce

1. In `projects/02-llm-to-playwright/`, run `npm install` to fetch dependencies.
2. Execute `npm run generate` (sample configuration) to regenerate the Playwright suites.
3. Run `npx playwright test` to execute generated tests with accessibility and snapshot checks.

## Next Steps

- Extend `blueprint.sample.json` with more acceptance criteria to control LLM breadth.
- Automate diff reviews in GitHub Actions and surface changes in the weekly summary.
- Harden secrets management and integrate `playwright test --update-snapshots` into CI before production use.
