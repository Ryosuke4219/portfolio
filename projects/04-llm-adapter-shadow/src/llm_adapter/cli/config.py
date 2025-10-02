from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..runner_config import (
    ConsensusConfig,
    DEFAULT_MAX_CONCURRENCY,
    RunnerConfig,
    RunnerMode,
)
from ..shadow import DEFAULT_METRICS_PATH, MetricsPath


def _load_optional_text(path_text: str | None) -> str | None:
    if not path_text:
        return None
    return Path(path_text).read_text(encoding="utf-8")


def _build_consensus_config(args: argparse.Namespace) -> ConsensusConfig | None:
    schema_text = _load_optional_text(args.schema)
    if not any(
        (
            args.aggregate,
            args.quorum,
            args.tie_breaker,
            schema_text,
            args.judge,
            args.weights,
            args.max_latency_ms is not None,
            args.max_cost_usd is not None,
        )
    ):
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
    if args.max_latency_ms is not None:
        payload["max_latency_ms"] = args.max_latency_ms
    if args.max_cost_usd is not None:
        payload["max_cost_usd"] = args.max_cost_usd
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


__all__ = ["build_runner_config"]
