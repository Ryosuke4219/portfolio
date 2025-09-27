"""共通ランナー API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Literal, Sequence

from .budgets import BudgetManager
from .config import load_budget_book, load_provider_configs
from .datasets import load_golden_tasks
from .runners import CompareRunner

Mode = Literal["parallel", "serial"]


def default_budgets_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "budgets.yaml"


def default_metrics_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "runs-metrics.jsonl"


def run_compare(
    provider_paths: Sequence[Path],
    prompt_path: Path,
    *,
    budgets_path: Path,
    metrics_path: Path,
    repeat: int = 1,
    mode: Mode = "parallel",
    allow_overrun: bool = False,
    log_level: str = "INFO",
) -> int:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

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
    )
    results = runner.run(repeat=max(repeat, 1), mode=mode)
    logging.getLogger(__name__).info("%d 件の試行を記録しました", len(results))
    return 0


def run_batch(provider_specs: Iterable[str], prompts_path: str) -> int:
    provider_paths: List[Path] = [
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
        mode="parallel",
        allow_overrun=False,
        log_level="INFO",
    )


__all__ = [
    "Mode",
    "default_budgets_path",
    "default_metrics_path",
    "run_batch",
    "run_compare",
]
