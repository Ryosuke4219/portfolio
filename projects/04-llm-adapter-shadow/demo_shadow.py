from __future__ import annotations

import sys

from src.llm_adapter.errors import ProviderSkip
from src.llm_adapter.metrics import (
    PrometheusMetricsExporter,
    register_metrics_exporter,
)
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.providers.factory import provider_from_environment
from src.llm_adapter.runner import Runner


def _resolve_model_name(provider) -> str:
    # Provider 実装が保持しているモデル名を優先して取得
    for attr in ("model", "_model"):
        val = getattr(provider, attr, None)
        if isinstance(val, str) and val.strip():
            return val

    # name() が "prefix:model" 形式ならモデル部を抽出（念のため）
    try:
        name = provider.name()
        if isinstance(name, str) and ":" in name:
            _, model_part = name.split(":", 1)
            if model_part.strip():
                return model_part
    except Exception:
        pass

    # 最後の保険（ここに来ることは基本想定しない）
    return "primary-model"


if __name__ == "__main__":
    try:
        from prometheus_client import start_http_server
    except ModuleNotFoundError:  # pragma: no cover - optional dependency
        start_http_server = None

    try:
        primary = provider_from_environment(
            "PRIMARY_PROVIDER",
            default="gemini:gemini-2.5-flash",
        )
        shadow = provider_from_environment(
            "SHADOW_PROVIDER",
            default="ollama:gemma3n:e2b",
            optional=True,
        )
    except ValueError as exc:  # pragma: no cover - defensive CLI guard
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if primary is None:  # pragma: no cover - configuration guard
        raise SystemExit("Primary provider is required")

    if start_http_server is not None:
        try:
            register_metrics_exporter(PrometheusMetricsExporter())
            start_http_server(8000)
            print("Prometheus metrics at http://localhost:8000/metrics")
        except RuntimeError as exc:
            print(f"Prometheus exporter disabled: {exc}", file=sys.stderr)
    else:
        print("Install prometheus_client to expose /metrics (optional)")

    runner = Runner([primary])

    # ProviderRequest.model は必須。CLI/Factory 層で必ず決める。
    request = ProviderRequest(
        prompt="こんにちは、世界",
        model=_resolve_model_name(primary),
    )

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
