---
layout: default
title: LLM Adapter — Shadow Execution (EN)
description: Highlights of the adapter that keeps primary responses while shadow providers capture anomalies
---

> [日本語版]({{ '/evidence/llm-adapter.html' | relative_url }})

# LLM Adapter — Shadow Execution

The adapter keeps your primary LLM provider intact while running a shadow provider in parallel. It records response diffs and anomaly events as JSONL, offering a lightweight measurement foundation for fallbacks and vendor comparisons.

## Highlights

- `run_with_shadow` returns the primary result while collecting shadow metrics asynchronously.
- Replays timeout, rate limiting, and malformed responses using markers such as `[TIMEOUT]` for repeatable fallback testing.
- The `Runner` coordinates exception handling and provider switching, storing event logs under `artifacts/runs-metrics.jsonl`.

## Key Artifacts

- [README.md](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/README.md) — Overview and usage guide.
- [src/llm_adapter/runner.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/src/llm_adapter/runner.py) — Core fallback orchestration logic.
- [src/llm_adapter/metrics.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/src/llm_adapter/metrics.py) — JSONL metric recording utilities.
- [demo_shadow.py](https://github.com/Ryosuke4219/portfolio/blob/main/projects/04-llm-adapter-shadow/demo_shadow.py) — Demo showcasing shadow execution and event output.

## How to Reproduce

1. In `projects/04-llm-adapter-shadow/`, create a virtual environment and run `pip install -r requirements.txt`.
2. Execute `python demo_shadow.py` to observe shadow execution and the resulting `artifacts/runs-metrics.jsonl` log.
3. Run `pytest -q` to verify tests covering shadow diffs and error handling.

## Next Steps

- Add real provider SDKs under `providers/` and expand metrics (latency, token usage) for richer comparisons.
- Ship JSONL logs to your data platform and record weekly insights in the [summary index]({{ '/weekly-summary.html' | relative_url }}).
- Emit events in OpenTelemetry format to integrate with existing observability stacks.
