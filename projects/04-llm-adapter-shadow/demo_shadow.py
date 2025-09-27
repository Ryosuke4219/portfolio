from __future__ import annotations

import sys

from src.llm_adapter.errors import ProviderSkip
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.factory import provider_from_environment
from src.llm_adapter.runner import Runner

if __name__ == "__main__":
    try:
        primary = provider_from_environment(
            "PRIMARY_PROVIDER", default="gemini:gemini-2.5-flash"
        )
        shadow = provider_from_environment(
            "SHADOW_PROVIDER",
            default="ollama:gemma3n:e2b",
            optional=True,
        )
    except ValueError as exc:  # pragma: no cover - defensive CLI guard
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    runner = Runner([primary])
    request = ProviderRequest(prompt="こんにちは、世界", model="gemini-2.5-flash")

    try:
        response = runner.run(request, shadow=shadow)
    except ProviderSkip as exc:  # pragma: no cover - configuration guard
        print(f"Provider skipped: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:  # pragma: no cover - demo script resilience
        print(f"Provider execution failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Primary provider: {primary.name()} -> {response.text}")
    print(f"Latency: {response.latency_ms} ms, tokens: {response.token_usage.total}")
    if shadow is not None:
        print(f"Shadow provider: {shadow.name()} (metrics only)")
    print("Shadow metrics are written to artifacts/runs-metrics.jsonl")
