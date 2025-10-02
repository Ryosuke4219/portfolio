from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

from ..parallel_exec import ParallelAllResult
from ..provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from ..providers.factory import ProviderFactory, create_provider_from_spec, parse_provider_spec
from ..runner import AsyncRunner, Runner
from ..shadow import MetricsPath
from .args import parse_args
from .config import build_runner_config
from .io import _format_output, _read_structured_payload


def _resolve_model_name(spec: str, provider: ProviderSPI) -> str:
    _, remainder = parse_provider_spec(spec)
    if remainder:
        return remainder
    name = provider.name()
    if ":" in name:
        return name.split(":", 1)[1]
    model_attr = getattr(provider, "model", None)
    if isinstance(model_attr, str) and model_attr.strip():
        return model_attr
    return "primary-model"


def prepare_execution(
    args: argparse.Namespace,
    *,
    async_mode: bool | None = None,
    factories: Mapping[str, ProviderFactory] | None = None,
) -> tuple[Runner | AsyncRunner, ProviderRequest, MetricsPath]:
    providers = [create_provider_from_spec(spec, factories=factories) for spec in args.providers]
    if not providers:
        raise ValueError("at least one provider is required")
    raw_payload: dict[str, Any] | None = None
    if args.input == "-":
        prompt_text = sys.stdin.read()
    else:
        input_path = Path(args.input)
        text = input_path.read_text(encoding="utf-8")
        suffix = input_path.suffix.lower()
        if suffix == ".jsonl":
            raw_payload = _read_structured_payload(text, jsonl=True)
            if not raw_payload:
                prompt_text = text
            else:
                prompt_text = raw_payload.get("prompt")
        elif suffix == ".json" or text.lstrip().startswith("{"):
            raw_payload = _read_structured_payload(text)
            prompt_text = raw_payload.get("prompt") if raw_payload else ""
        else:
            prompt_text = text

    request_kwargs: dict[str, Any] = {}
    if raw_payload:
        prompt_value = raw_payload.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value:
            input_prompt = raw_payload.get("input")
            prompt_value = input_prompt if isinstance(input_prompt, str) else ""
        request_kwargs["prompt"] = prompt_value
        messages = raw_payload.get("messages")
        if isinstance(messages, Sequence) and not isinstance(
            messages, str | bytes | bytearray
        ):
            normalized = [dict(entry) for entry in messages if isinstance(entry, Mapping)]
            if normalized:
                request_kwargs["messages"] = normalized
        options = raw_payload.get("options")
        if isinstance(options, Mapping):
            request_kwargs["options"] = dict(options)
        metadata = raw_payload.get("metadata")
        if isinstance(metadata, Mapping):
            request_kwargs["metadata"] = dict(metadata)
    else:
        request_kwargs["prompt"] = prompt_text

    request = ProviderRequest(
        model=_resolve_model_name(args.providers[0], providers[0]),
        **request_kwargs,
    )
    config = build_runner_config(args)
    metrics_path_value = config.metrics_path
    metrics_path: MetricsPath
    if isinstance(metrics_path_value, Path):
        metrics_path = str(metrics_path_value)
    else:
        metrics_path = metrics_path_value
    use_async = async_mode if async_mode is not None else args.async_runner
    runner: Runner | AsyncRunner = AsyncRunner(providers, config=config) if use_async else Runner(providers, config=config)
    return runner, request, metrics_path


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


__all__ = ["prepare_execution", "main"]
