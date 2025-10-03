"""共通ランナー API."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import fields, is_dataclass
import inspect
import logging
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from .budgets import BudgetManager
from .config import (
    load_budget_book,
    load_provider_config,
    load_provider_configs,
)
from .datasets import load_golden_tasks
from .runner_config_builder import (
    BackoffPolicy,
    RunnerConfig,
    RunnerConfigBuilder,
    RunnerMode,
)
from .runners import CompareRunner

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック

        class ProviderSPI(Protocol):
            """プロバイダ SPI フォールバック."""


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
    mode: RunnerMode | str = RunnerMode.SEQUENTIAL,
    allow_overrun: bool = False,
    log_level: str = "INFO",
    aggregate: str | None = None,
    quorum: int | None = None,
    tie_breaker: str | None = None,
    provider_weights: dict[str, float] | None = None,
    schema: Path | str | None = None,
    judge: str | None = None,
    max_concurrency: int | None = None,
    rpm: int | None = None,
    runner_config: RunnerConfig | None = None,
    backoff: BackoffPolicy | None = None,
    shadow_provider: ProviderSPI | None = None,
) -> int:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    builder = RunnerConfigBuilder(runner_config=runner_config)
    judge_path = RunnerConfigBuilder._resolve_optional_path(judge)
    judge_provider = load_provider_config(judge_path) if judge_path else None
    config = builder.build_compare_config(
        mode=mode,
        aggregate=aggregate,
        quorum=quorum,
        tie_breaker=tie_breaker,
        provider_weights=provider_weights,
        schema=schema,
        judge=judge_path,
        judge_provider=judge_provider,
        max_concurrency=max_concurrency,
        rpm=rpm,
        backoff=backoff,
        shadow_provider=shadow_provider,
        metrics_path=metrics_path,
    )

    if RunnerConfig is not type(config) and is_dataclass(config):
        config_kwargs = {
            field.name: getattr(config, field.name) for field in fields(config)
        }
        _ = RunnerConfig(**config_kwargs)

    provider_configs = load_provider_configs(list(provider_paths))
    tasks = load_golden_tasks(prompt_path)
    budget_book = load_budget_book(budgets_path)
    budget_manager = BudgetManager(budget_book)

    assert config.metrics_path is not None
    runner = CompareRunner(
        provider_configs,
        tasks,
        budget_manager,
        config.metrics_path,
        allow_overrun=allow_overrun,
        runner_config=config,
    )
    run_signature = inspect.signature(runner.run)
    repeat_value = max(repeat, 1)
    parameters = run_signature.parameters
    args: list[object] = []
    kwargs: dict[str, object] = {}
    assigned: set[str] = set()

    def _assign(name: str, value: object) -> bool:
        parameter = parameters.get(name)
        if parameter is None:
            return False
        assigned.add(name)
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            args.append(value)
        else:
            kwargs[name] = value
        return True

    if not _assign("repeat", repeat_value):
        args.append(repeat_value)

    if not _assign("config", config):
        mode_value = config.mode
        if not _assign("mode", mode_value):
            needs_positional = any(
                parameter.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
                and name not in assigned
                for name, parameter in parameters.items()
            )
            if needs_positional:
                args.append(mode_value)

    results = runner.run(*args, **kwargs)
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
        mode=RunnerMode.PARALLEL_ANY,
        allow_overrun=False,
        log_level="INFO",
    )


def _normalize_mode(value: RunnerMode | str) -> RunnerMode:
    return RunnerConfigBuilder._normalize_mode(value)


__all__ = [
    "BackoffPolicy",
    "RunnerMode",
    "RunnerConfig",
    "_normalize_mode",
    "default_budgets_path",
    "default_metrics_path",
    "run_batch",
    "run_compare",
]
