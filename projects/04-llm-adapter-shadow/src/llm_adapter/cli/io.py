from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ..provider_spi import ProviderRequest, ProviderSPI
from ..providers.factory import ProviderFactory, create_provider_from_spec, parse_provider_spec
from ..runner import AsyncRunner, Runner
from ..shadow import MetricsPath
from .config import build_runner_config

def _read_structured_payload(text: str, *, jsonl: bool = False) -> dict[str, Any] | None:
    if jsonl:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
            except JSONDecodeError as exc:  # pragma: no cover - invalid JSON handled by caller
                raise ValueError("failed to parse JSONL input") from exc
            if not isinstance(data, Mapping):
                raise ValueError("JSONL input must contain JSON objects")
            return dict(data)
        return None
    try:
        data = json.loads(text)
    except JSONDecodeError as exc:  # pragma: no cover - invalid JSON handled by caller
        raise ValueError("failed to parse JSON input") from exc
    if not isinstance(data, Mapping):
        raise ValueError("JSON input must be an object")
    return dict(data)


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
    providers = [
        create_provider_from_spec(spec, factories=factories)
        for spec in args.providers
    ]
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
    runner: Runner | AsyncRunner
    if use_async:
        runner = AsyncRunner(providers, config=config)
    else:
        runner = Runner(providers, config=config)
    return runner, request, metrics_path


__all__ = ["prepare_execution"]