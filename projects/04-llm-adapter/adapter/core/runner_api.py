"""共通ランナー API."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import inspect
import logging
from pathlib import Path
from typing import cast, Protocol, TYPE_CHECKING

from .budgets import BudgetManager
from .config import (
    load_budget_book,
    load_provider_config,
    load_provider_configs,
    ProviderConfig,
)
from .datasets import load_golden_tasks
from .runners import CompareRunner

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        class ProviderSPI(Protocol):
            """プロバイダ SPI フォールバック."""


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limit_sleep_s: float | None = None
    timeout_next_provider: bool = False
    retryable_next_provider: bool = False

class RunnerMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel-any"
    PARALLEL_ALL = "parallel-all"
    CONSENSUS = "consensus"


_MODE_ALIASES: dict[str, RunnerMode] = {
    "parallel": RunnerMode.PARALLEL_ANY,
    "serial": RunnerMode.SEQUENTIAL,
}


@dataclass(frozen=True)
class RunnerConfig:
    """ランナーの制御パラメータ."""

    mode: RunnerMode | str
    aggregate: str | None = None
    quorum: int | None = None
    tie_breaker: str | None = None
    provider_weights: dict[str, float] | None = None
    schema: Path | None = None
    judge: Path | None = None
    judge_provider: ProviderConfig | None = None
    max_concurrency: int | None = None
    rpm: int | None = None
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    shadow_provider: ProviderSPI | None = None
    metrics_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _normalize_mode(self.mode))


def default_budgets_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "budgets.yaml"


def default_metrics_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "runs-metrics.jsonl"


def _normalize_mode(value: RunnerMode | str) -> RunnerMode:
    if isinstance(value, RunnerMode):
        return value
    candidate = value.strip().lower().replace("_", "-")
    alias = _MODE_ALIASES.get(candidate)
    if alias is not None:
        return alias
    try:
        return RunnerMode(candidate)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"unknown mode: {value}") from exc


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


def _is_weighted_aggregate(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower().replace("-", "_")
    return normalized in {"weighted_vote", "weighted"}


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

    resolved_mode = _normalize_mode(mode)
    judge_path = _resolve_optional_path(judge)
    judge_provider = load_provider_config(judge_path) if judge_path else None
    sanitized_quorum = _sanitize_positive_int(quorum)
    sanitized_max_concurrency = _sanitize_positive_int(max_concurrency)
    sanitized_rpm = _sanitize_positive_int(rpm)

    is_weighted = _is_weighted_aggregate(aggregate)
    if is_weighted and provider_weights is None:
        raise ValueError("aggregate=weighted_vote requires provider_weights")
    sanitized_weights = provider_weights if is_weighted else None

    if runner_config is None:
        config = RunnerConfig(
            mode=resolved_mode,
            aggregate=aggregate,
            quorum=sanitized_quorum,
            tie_breaker=tie_breaker,
            provider_weights=sanitized_weights,
            schema=_resolve_optional_path(schema),
            judge=judge_path,
            judge_provider=judge_provider,
            max_concurrency=sanitized_max_concurrency,
            rpm=sanitized_rpm,
            backoff=backoff or BackoffPolicy(),
            shadow_provider=shadow_provider,
            metrics_path=metrics_path,
        )
    else:
        config = runner_config
        updates: dict[str, object] = {}
        if config.judge_provider is None and judge_provider is not None:
            updates["judge"] = judge_path
            updates["judge_provider"] = judge_provider
        if backoff is not None:
            updates["backoff"] = backoff
        if shadow_provider is not None:
            updates["shadow_provider"] = shadow_provider
        if sanitized_weights is not None:
            updates["provider_weights"] = sanitized_weights
        if config.metrics_path is None:
            updates["metrics_path"] = metrics_path
        if updates:
            try:
                config = replace(config, **updates)
            except (TypeError, AttributeError):
                if "judge" in updates:
                    config.judge = cast(Path | None, updates["judge"])
                if "judge_provider" in updates:
                    config.judge_provider = cast(
                        ProviderConfig | None, updates["judge_provider"]
                    )
                if "backoff" in updates:
                    config.backoff = cast(BackoffPolicy, updates["backoff"])
                if "shadow_provider" in updates:
                    config.shadow_provider = cast(
                        ProviderSPI | None, updates["shadow_provider"]
                    )
                if "provider_weights" in updates:
                    config.provider_weights = cast(
                        dict[str, float] | None, updates["provider_weights"]
                    )
                if "metrics_path" in updates:
                    config.metrics_path = cast(Path | None, updates["metrics_path"])

    current_metrics_path = getattr(config, "metrics_path", None)
    if current_metrics_path is None:
        try:
            config = replace(config, metrics_path=metrics_path)
        except (TypeError, AttributeError):
            config.metrics_path = metrics_path
        resolved_metrics_path = metrics_path
    else:
        resolved_metrics_path = current_metrics_path

    provider_configs = load_provider_configs(list(provider_paths))
    tasks = load_golden_tasks(prompt_path)
    budget_book = load_budget_book(budgets_path)
    budget_manager = BudgetManager(budget_book)

    runner = CompareRunner(
        provider_configs,
        tasks,
        budget_manager,
        resolved_metrics_path,
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
        mode=RunnerMode.PARALLEL_ANY,
        allow_overrun=False,
        log_level="INFO",
    )


__all__ = [
    "BackoffPolicy",
    "RunnerMode",
    "RunnerConfig",
    "default_budgets_path",
    "default_metrics_path",
    "run_batch",
    "run_compare",
]
