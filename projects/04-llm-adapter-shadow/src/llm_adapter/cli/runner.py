from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from ..parallel_exec import ParallelAllResult
from ..provider_spi import ProviderResponse
from ..runner import AsyncRunner
from .args import parse_args
from .io import prepare_execution


def _format_output(response: ProviderResponse, fmt: str) -> str:
    if fmt == "text":
        return response.text
    provider_name: str | None = None
    raw_payload = response.raw
    if isinstance(raw_payload, Mapping):
        provider_candidate = raw_payload.get("provider")
        if isinstance(provider_candidate, str) and provider_candidate.strip():
            provider_name = provider_candidate.strip()
    if not provider_name:
        provider_name = response.model or ""
    token_usage = response.token_usage
    payload: dict[str, Any] = {
        "status": "success",
        "text": response.text,
        "provider": provider_name,
        "model": response.model,
        "latency_ms": response.latency_ms,
        "token_usage": {
            "prompt": token_usage.prompt,
            "completion": token_usage.completion,
            "total": token_usage.total,
        },
    }
    if response.finish_reason is not None:
        payload["finish_reason"] = response.finish_reason
    if isinstance(raw_payload, Mapping):
        payload["raw"] = raw_payload
    return json.dumps(
        payload,
        ensure_ascii=False,
    )


def _coerce_response(
    result: ProviderResponse | ParallelAllResult[Any, ProviderResponse]
) -> ProviderResponse:
    if isinstance(result, ParallelAllResult):
        return result.primary_response
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        runner, request, metrics_path = prepare_execution(args)
        raw_response: ProviderResponse | ParallelAllResult[Any, ProviderResponse]
        if isinstance(runner, AsyncRunner):
            raw_response = asyncio.run(
                runner.run_async(request, shadow=None, shadow_metrics_path=metrics_path)
            )
        else:
            raw_response = runner.run(request, shadow=None, shadow_metrics_path=metrics_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Execution failed: {exc}", file=sys.stderr)
        return 1
    response = _coerce_response(raw_response)
    print(_format_output(response, args.out_format))
    return 0


__all__ = ["main"]
