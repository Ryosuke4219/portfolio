"""共通ランナー API."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
import inspect
import logging
from pathlib import Path
from typing import cast, Literal

from .budgets import BudgetManager
from .config import (
    load_budget_book,
    load_provider_config,
    load_provider_configs,
    ProviderConfig,
)
from .datasets import load_golden_tasks
from .runners import CompareRunner

Mode = Literal["sequential", "parallel-any", "parallel-all", "consensus"]

_MODE_CHOICES: tuple[Mode, ...] = (
    "sequential",
    "parallel-any",
    "parallel-all",
    "consensus",
)

_MODE_ALIASES: dict[str, Mode] = {
    "parallel": "parallel-any",
    "serial": "sequential",
}


@dataclass(frozen=True)
class RunnerConfig:
    """ランナーの制御パラメータ."""

    mode: Mode
    aggregate: str | None = None
    quorum: int | None = None
    tie_breaker: str | None = None
    schema: Path | None = None
    judge: Path | None = None
    judge_provider: ProviderConfig | None = None
    max_concurrency: int | None = None
    rpm: int | None = None


def default_budgets_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "budgets.yaml"


def default_metrics_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "runs-metrics.jsonl"


def _normalize_mode(value: Mode | str) -> Mode:
    candidate: str
    if isinstance(value, str):
        candidate = _MODE_ALIASES.get(value, value)
    else:
        candidate = value
    if candidate not in _MODE_CHOICES:
        raise ValueError(f"unknown mode: {value}")
    return cast(Mode, candidate)


def _sanitize_positive_int(value: int | None) -> int | None:
    if value is None:
        return None
    if value <= 0:
        return None
    return value


def _resolve_optional_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if not value:
        return None
    return Path(value).expanduser().resolve()


def run_compare(
    provider_paths: Sequence[Path],
    prompt_path: Path,
    *,
    budgets_path: Path,
    metrics_path: Path,
    repeat: int = 1,
    mode: Mode | str = "sequential",
    allow_overrun: bool = False,
    log_level: str = "INFO",
    aggregate: str | None = None,
    quorum: int | None = None,
    tie_breaker: str | None = None,
    schema: Path | str | None = None,
    judge: str | None = None,
    max_concurrency: int | None = None,
    rpm: int | None = None,
    runner_config: RunnerConfig | None = None,
) -> int:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    resolved_mode = _normalize_mode(mode)
    judge_path = _resolve_optional_path(judge)
    judge_provider = load_provider_config(judge_path) if judge_path else None
    if runner_config is None:
        config = RunnerConfig(
            mode=resolved_mode,
            aggregate=aggregate,
            quorum=_sanitize_positive_int(quorum),
            tie_breaker=tie_breaker,
            schema=_resolve_optional_path(schema),
            judge=judge_path,
            judge_provider=judge_provider,
            max_concurrency=_sanitize_positive_int(max_concurrency),
            rpm=_sanitize_positive_int(rpm),
        )
    else:
        config = runner_config
        if config.judge_provider is None and judge_provider is not None:
            config = replace(config, judge=judge_path, judge_provider=judge_provider)

    provider_configs = load_provider_configs(list(provider_paths))
    tasks = load_golden_tasks(prompt_path)
    budget_book = load_budget_book(budgets_path)
    budget_manager = BudgetManager(budget_book)

    runner = CompareRunner(
        provider_configs,
        tasks,
        budget_manager,
        metrics_path,
        allow_overrun=allow_overrun,
        runner_config=config,
    )
    run_kwargs: dict[str, object] = {"repeat": max(repeat, 1)}
    run_signature = inspect.signature(runner.run)
    if "config" in run_signature.parameters:
        run_kwargs["config"] = config
    else:
        run_kwargs["mode"] = config.mode
    results = runner.run(**run_kwargs)
    logging.getLogger(__name__).info("%d 件の試行を記録しました", len(results))
    return 0


def run_batch(provider_specs: Iterable[str], prompts_path: str) -> int:
    provider_paths: list[Path] = [
        Path(spec).expanduser().resolve() for spec in provider_specs if spec
    ]
    if not provider_paths:
        raise ValueError("provider_specs must include at least one path")

    prompt_path = Path(prompts_path).expanduser().resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"ゴールデンタスクが見つかりません: {prompt_path}")

    return run_compare(
        provider_paths,
        prompt_path,
        budgets_path=default_budgets_path(),
        metrics_path=default_metrics_path(),
        repeat=1,
        mode="parallel-any",
        allow_overrun=False,
        log_level="INFO",
    )


__all__ = [
    "Mode",
    "RunnerConfig",
    "default_budgets_path",
    "default_metrics_path",
    "run_batch",
    "run_compare",
]
