from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys
from typing import Any, cast

from .parallel_exec import ParallelAllResult
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .providers.factory import create_provider_from_spec, parse_provider_spec, ProviderFactory
from .runner import AsyncRunner, Runner
from .runner_config import ConsensusConfig, RunnerConfig, RunnerMode
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
    config_kwargs: dict[str, object] = {
        "mode": RunnerMode(args.mode.replace("-", "_")),
        "rpm": args.rpm,
        "consensus": _build_consensus_config(args),
        "metrics_path": metrics_path,
    }
    if args.max_concurrency is not None:
        config_kwargs["max_concurrency"] = args.max_concurrency
    return RunnerConfig(**cast(dict[str, Any], config_kwargs))


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
    request = ProviderRequest(
        prompt=Path(args.input).read_text(encoding="utf-8") if args.input != "-" else sys.stdin.read(),
        model=_resolve_model_name(args.providers[0], providers[0]),
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
    payload = {"text": response.text, "model": response.model, "latency_ms": response.latency_ms}
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
