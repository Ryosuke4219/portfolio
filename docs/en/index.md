---
layout: default
title: Portfolio Hub (EN)
description: A portal showcasing QA / SDET / LLM highlights with weekly summaries in English
---

> [日本語版はこちら]({{ '/' | relative_url }})

> 🔎 Latest CI reports: [JUnit summary]({{ '/reports/junit/index.html' | relative_url }}) / [Flaky ranking]({{ '/reports/flaky/index.html' | relative_url }}) / [Coverage HTML]({{ '/reports/coverage/index.html' | relative_url }})

# Demos

<div class="demo-grid">
  <article class="demo-card">
    <header>
      <p class="demo-card__id">01</p>
      <h2><a href="{{ '/en/evidence/spec2cases.html' | relative_url }}">Spec to Cases</a></h2>
    </header>
    <p>A pipeline that turns specification Markdown into test case JSON with LLM drafting and rule-based post-processing.</p>
    <ul>
      <li>Schema validation and type-preserving transformation logic.</li>
      <li>CLI helpers and JSON samples for quick onboarding.</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/en/evidence/spec2cases.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>

  <article class="demo-card">
    <header>
      <p class="demo-card__id">02</p>
      <h2><a href="{{ '/en/evidence/llm2pw.html' | relative_url }}">LLM to Playwright</a></h2>
    </header>
    <p>A proof of concept where an LLM expands acceptance criteria and generates Playwright tests automatically.</p>
    <ul>
      <li>Robust selector strategy based on <code>data-testid</code> with a11y scanning baked in.</li>
      <li>Data-driven tests via JSON / CSV drivers for a minimal setup.</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/en/evidence/llm2pw.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>

  <article class="demo-card">
    <header>
      <p class="demo-card__id">03</p>
      <h2><a href="{{ '/en/evidence/flaky.html' | relative_url }}">CI Flaky Analyzer</a></h2>
    </header>
    <p>A CLI that detects flaky tests from CI logs and automatically produces HTML reports and ticket templates.</p>
    <ul>
      <li>Streaming analysis for large JUnit XML files with scoring stored as JSONL / HTML.</li>
      <li>One-command generation of HTML reports, JSONL history, and GitHub Issue templates.</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/en/evidence/flaky.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>

  <article class="demo-card">
    <header>
      <p class="demo-card__id">04</p>
      <h2><a href="{{ '/en/evidence/llm-adapter.html' | relative_url }}">LLM Adapter — Provider Orchestration</a></h2>
    </header>
    <p>An adapter that orchestrates provider calls and comparison runs while keeping production fallbacks intact.</p>
    <ul>
      <li>Supports OpenAI, Gemini, Ollama, and OpenRouter behind a unified tracing layer.</li>
      <li>Run prompts with <code>llm-adapter --provider adapter/config/providers/openai.yaml --prompt-file adapter/prompts/demo-04.yaml</code>.</li>
      <li>Launch batch comparisons via <code>python adapter/run_compare.py --prompts examples/prompts/ja_one_liner.jsonl</code> to replay JSONL prompt lists.</li>
    </ul>
    <p><a class="demo-card__link" href="{{ '/en/evidence/llm-adapter.html' | relative_url }}">Evidence &rarr;</a></p>
  </article>
</div>

## Weekly Summary

{% include weekly-summary-card.md locale="en" %}

### 01. Spec to Cases
- Minimal pipeline that generates test cases from specification Markdown.
- Deliverable: [cases.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/spec2cases/cases.sample.json)
- Extra materials: [spec.sample.md](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/spec2cases/spec.sample.md)

### 02. LLM to Playwright
- PoC that enriches acceptance criteria with an LLM and auto-generates Playwright tests.
- Deliverables: [tests/generated/](https://github.com/Ryosuke4219/portfolio/tree/main/projects/02-blueprint-to-playwright/tests/generated)
- Samples: [blueprint.sample.json](https://github.com/Ryosuke4219/portfolio/blob/main/docs/examples/llm2pw/blueprint.sample.json) / [demo/](https://github.com/Ryosuke4219/portfolio/tree/main/docs/examples/llm2pw/demo)
- References: [tests/README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/02-blueprint-to-playwright/tests/README.md)

### 03. CI Flaky Analyzer
- Detects flaky tests from CI logs and enables re-runs and automated ticketing end-to-end.
- Deliverable: Running `npx flaky analyze` generates `projects/03-ci-flaky/out/index.html` (HTML/CSV/JSON) retrievable from CI artifacts.
- Sample workflow: Ingest any JUnit XML via `npx flaky parse --input <path-to-xml>` and store the history for later analysis.

### 04. LLM Adapter — Provider Orchestration
- Connects OpenAI, Gemini, Ollama, and OpenRouter with resilient fallback strategies and shared telemetry hooks.
- `llm-adapter --provider adapter/config/providers/openai.yaml --prompt-file adapter/prompts/demo-04.yaml` runs a single provider.
- `python adapter/run_compare.py --prompts examples/prompts/ja_one_liner.jsonl` records comparison metrics from the JSONL prompt list for audits.
- Reference: [evidence/llm-adapter](https://ryosuke4219.github.io/portfolio/evidence/llm-adapter.html)

[View all weekly summaries &rarr;]({{ '/en/weekly-summary.html' | relative_url }})

## Evidence Library

- [QA Evidence Catalog]({{ '/en/evidence/README.html' | relative_url }})
- [Test Plan]({{ '/test-plan.html' | relative_url }})
- [Defect Report Sample]({{ '/defect-report-sample.html' | relative_url }})

## Operations Notes

- The `weekly-qa-summary.yml` workflow automatically updates `docs/weekly-summary.md`.
- `tools/generate_gallery_snippets.py` generates highlight cards from the weekly summary.
- `.github/workflows/pages.yml` deploys everything under `docs/` to GitHub Pages.
