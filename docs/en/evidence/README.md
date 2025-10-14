# QA Evidence Catalog (EN)

This catalog lists the primary sources referenced by the `EvidenceLink` entries in the RTM so that reviewers can access materials quickly during validation.

## 01. Spec to Cases
- Template for case design: `../examples/spec2cases/spec.sample.md`
- Automation script: `../../projects/01-spec2cases-md2json/scripts/spec2cases.mjs`
- Sample cases: `../examples/spec2cases/cases.sample.json`

## 02. LLM to Playwright
- Test overview: `../../projects/02-blueprint-to-playwright/tests/README.md`
- Sample blueprint: `../examples/llm2pw/blueprint.sample.json`
- Demo HTML: `../examples/llm2pw/demo`
- Generated scenarios: `../../projects/02-blueprint-to-playwright/tests/generated`
- Visual diffs: `../../projects/02-blueprint-to-playwright/tests/generated/__snapshots__`

## 03. CI Flaky Analyzer
- Product README: `../../projects/03-ci-flaky/README.md`
- Specification: `../../projects/03-ci-flaky/docs/spec_flaky_analyzer.md`
- Analysis store: `../../projects/03-ci-flaky/data/runs.jsonl` — append with `npx flaky parse --input <junit-xml>`
- Summary HTML: `npx flaky analyze` generates `../../projects/03-ci-flaky/out/index.html` (downloadable from CI)

## 04. LLM Adapter
- Product README: `../../projects/04-llm-adapter/README.md`
- Evidence details: `./llm-adapter.md`
- Provider configurations: `../../projects/04-llm-adapter/adapter/config/providers`
- Golden tasks: `../../projects/04-llm-adapter/datasets/golden`

## Docs Cross Reference
- Test plan: [Test plan]({{ '/test-plan.html' | relative_url }})
- Defect report sample: [Defect report sample]({{ '/defect-report-sample.html' | relative_url }})
- Weekly summary: [Weekly summary]({{ '/weekly-summary.html' | relative_url }})

> [日本語版カタログ]({{ '/evidence/README.html' | relative_url }})
