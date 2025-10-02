from __future__ import annotations

import argparse
from collections.abc import Sequence


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


def _parse_non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:  # pragma: no cover - argparse reports error
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _parse_non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:  # pragma: no cover - argparse reports error
        raise argparse.ArgumentTypeError("value must be numeric") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


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
    parser.add_argument(
        "--max-latency-ms",
        dest="max_latency_ms",
        type=_parse_non_negative_int,
        help="Maximum provider latency allowed during consensus (milliseconds)",
    )
    parser.add_argument(
        "--max-cost-usd",
        dest="max_cost_usd",
        type=_parse_non_negative_float,
        help="Maximum cumulative provider cost allowed during consensus (USD)",
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-format", dest="out_format", default="text", choices=("text", "json", "jsonl"))
    parser.add_argument("--metrics")
    parser.add_argument("--async-runner", action="store_true", dest="async_runner")
    return parser.parse_args(argv)


__all__ = ["parse_args"]
