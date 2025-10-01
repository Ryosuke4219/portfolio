from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import json
from json import JSONDecodeError
from pathlib import Path
import sys
from typing import Any

from .parallel_exec import ParallelAllResult
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .providers.factory import create_provider_from_spec, parse_provider_spec, ProviderFactory
from .runner import AsyncRunner, Runner
from .runner_config import (
    ConsensusConfig,
    DEFAULT_MAX_CONCURRENCY,
    RunnerConfig,
    RunnerMode,
)
from .shadow import DEFAULT_METRICS_PATH, MetricsPath


def _parse_csv(value: str) -> tuple[str, ...]:
    parts = tuple(entry.strip() for entry in value.split(",") if entry.strip())
    if not parts:
        raise argparse.ArgumentTypeError("expected at least one item")
    return parts


def _parse_weights(value: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for item in _parse_csv(value):
        key, sep, raw = item.partition("=")
        if not sep:
            raise argparse.ArgumentTypeError("weights must use key=value")
        try:
            weights[key.strip()] = float(raw.strip())
        except ValueError as exc:  # pragma: no cover - argparse reports error
            raise argparse.ArgumentTypeError("weight must be numeric") from exc
    if not weights:
        raise argparse.ArgumentTypeError("weights must not be empty")
    return weights


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="llm-adapter")
    parser.add_argument("--mode", required=True, choices=("sequential", "parallel-any", "parallel-all", "consensus"))
    parser.add_argument("--providers", required=True, type=_parse_csv)
    parser.add_argument("--max-concurrency", dest="max_concurrency", type=int)
    parser.add_argument("--rpm", type=int)
    parser.add_argument("--aggregate", choices=("majority_vote", "max_score", "weighted_vote"))
    parser.add_argument("--quorum", type=int)
    parser.add_argument("--tie-breaker", choices=("min_latency", "min_cost", "stable_order"), dest="tie_breaker")
    parser.add_argument("--schema")
    parser.add_argument("--judge")
    parser.add_argument("--weights", type=_parse_weights)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-format", dest="out_format", default="text", choices=("text", "json", "jsonl"))
    parser.add_argument("--metrics")
    parser.add_argument("--async-runner", action="store_true", dest="async_runner")
    return parser.parse_args(argv)


def _load_optional_text(path_text: str | None) -> str | None:
    if not path_text:
        return None
    return Path(path_text).read_text(encoding="utf-8")


def _build_consensus_config(args: argparse.Namespace) -> ConsensusConfig | None:
    schema_text = _load_optional_text(args.schema)
    if not any((args.aggregate, args.quorum, args.tie_breaker, schema_text, args.judge, args.weights)):
        return None
    payload: dict[str, Any] = {}
    if args.aggregate:
        payload["strategy"] = args.aggregate
    if args.quorum is not None:
        payload["quorum"] = args.quorum
    if args.tie_breaker is not None:
        payload["tie_breaker"] = args.tie_breaker
    if schema_text is not None:
        payload["schema"] = schema_text
    if args.judge is not None:
        payload["judge"] = args.judge
    if args.weights is not None:
        payload["provider_weights"] = dict(args.weights)
    return ConsensusConfig(**payload)


def build_runner_config(args: argparse.Namespace) -> RunnerConfig:
    metrics_path: MetricsPath
    if args.metrics:
        metrics_path = Path(args.metrics)
    else:
        metrics_path = DEFAULT_METRICS_PATH
    max_concurrency = (
        args.max_concurrency
        if args.max_concurrency is not None
        else DEFAULT_MAX_CONCURRENCY
    )
    return RunnerConfig(
        mode=RunnerMode(args.mode.replace("-", "_")),
        rpm=args.rpm,
        consensus=_build_consensus_config(args),
        metrics_path=metrics_path,
        max_concurrency=max_concurrency,
    )


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
    return json.dumps(payload, ensure_ascii=False)


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


__all__ = ["parse_args", "build_runner_config", "prepare_execution", "main"]
