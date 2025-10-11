---
layout: default
title: LLM Adapter — Provider Benchmarking (EN)
description: Highlights of the adapter that compares, records, and visualizes multi-provider LLM responses
---

> [日本語版]({{ '/evidence/llm-adapter.html' | relative_url }})

# LLM Adapter — Provider Benchmarking

The adapter compares, records, and visualizes responses from multiple LLM providers without relying on shadow execution. It sends
the same prompts under production-like conditions, appends diffs, latency, cost, and failure classes to JSONL logs, and keeps
`datasets/golden/` tasks ready for regression testing together with `adapter/config/providers/` presets.

## Highlights

- The `llm-adapter` CLI invokes comparison modes implemented in `adapter/run_compare.py`, orchestrating sequential, parallel, and consensus runs with shared metrics.
- `adapter/core/runner_execution.py` handles retries and provider-specific exceptions, emitting comparison events for downstream tooling.
- `adapter/core/metrics/update.py` together with `adapter/core/metrics/models.py` shape JSONL metrics and derived summaries, appending results to paths provided via the CLI `--out` flag such as `out/metrics.jsonl` (while the default in `adapter/run_compare.py` remains `data/runs-metrics.jsonl`).

## Key Artifacts

- [projects/04-llm-adapter/README.md](../../projects/04-llm-adapter/README.md) — Comprehensive CLI usage and configuration reference.
- [projects/04-llm-adapter/adapter/run_compare.py](../../projects/04-llm-adapter/adapter/run_compare.py) — CLI comparison modes and their entry point implementation.
- [projects/04-llm-adapter/adapter/core/runner_execution.py](../../projects/04-llm-adapter/adapter/core/runner_execution.py) — Central logic covering provider execution, retries, and metric aggregation.
- [projects/04-llm-adapter/adapter/core/metrics/update.py](../../projects/04-llm-adapter/adapter/core/metrics/update.py) — Utilities that append JSONL metrics and derived summaries.
- [projects/04-llm-adapter/adapter/core/metrics/models.py](../../projects/04-llm-adapter/adapter/core/metrics/models.py) — Metric data models that define serialization helpers.

## How to Reproduce

1. `cd projects/04-llm-adapter`, create a virtual environment, and run `pip install -r requirements.txt` to install dependencies.
2. Install the CLI with `pip install -e .`, then execute `llm-adapter --provider adapter/config/providers/openai.yaml --prompt "Say hello in English" --out out --json-logs`. Use `--provider` to supply a single provider config and `--out` to choose the directory where metrics are appended (e.g., `out/metrics.jsonl`). When you invoke `python adapter/run_compare.py ...` directly, it defaults to writing into `data/runs-metrics.jsonl`.
3. Run `pytest -q` to ensure CLI, runner, and metric modules pass their test suites.

## Next Steps

- Extend `adapter/core/providers/` with additional SDK integrations to deepen latency and cost comparisons.
- Ship JSONL logs to your data platform and capture weekly insights in the [summary index]({{ '/weekly-summary.html' | relative_url }}).
- Explore `adapter/core/runner_async.py` to integrate asynchronous runners and evaluate streaming responses.
