---
layout: default
title: Spec to Cases (EN)
description: Highlights of an LLM + schema-driven pipeline that extracts test cases from specifications
---

> [日本語版]({{ '/evidence/spec2cases.html' | relative_url }})

# Spec to Cases

This pipeline ingests specification Markdown, combines LLM drafting with rule-based formatting, and outputs validated test cases in JSON. JSON Schema keeps the structure compatible with existing test management and automation frameworks.

## Highlights

- Post-process the LLM draft to guarantee JSON that complies with `schema.json`.
- Preserve key testing attributes such as steps, expected results, and priority through type-preserving transforms.
- Batch-convert Markdown into JSON with CLI scripts.

## Key Artifacts

- [spec.sample.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases-md2json/spec.sample.md) — Sample specification input.
- [cases.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases-md2json/cases.sample.json) — Generated test cases.
- [schema.json](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases-md2json/schema.json) — Validation schema for the output JSON.
- [scripts/convert.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/01-spec2cases-md2json/scripts/convert.py) — CLI entry point for the conversion.

## How to Reproduce

1. In `projects/01-spec2cases-md2json/`, install required Python dependencies such as `jsonschema`.
2. Run `scripts/convert.py --spec spec.sample.md --output cases.sample.json` to regenerate the sample output.
3. The CLI validates the generated content; mismatches against the schema will raise an error.

## Next Steps

- Customize LLM prompts to switch templates by domain (API / UI / non-functional).
- Push the case JSON to existing test management tools (e.g., Xray, TestRail) via their APIs.
- Track adoption logs in the [weekly summary]({{ '/weekly-summary.html' | relative_url }}) for future improvements.
