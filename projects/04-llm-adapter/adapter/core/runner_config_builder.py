from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from .config import ProviderConfig

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック

        class ProviderSPI(Protocol):
            """プロバイダ SPI フォールバック."""


class RunnerMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL_ANY = "parallel_any"
    PARALLEL_ALL = "parallel_all"
    CONSENSUS = "consensus"

    @property
    def canonical(self) -> str:
        return str(self)

    @property
    def alias(self) -> str:
        if self is RunnerMode.PARALLEL_ANY:
            return "parallel-any"
        if self is RunnerMode.PARALLEL_ALL:
            return "parallel-all"
        return str(self).replace("_", "-")


_MODE_ALIASES: dict[str, RunnerMode] = {
    "parallel": RunnerMode.PARALLEL_ANY,
    "parallel_any": RunnerMode.PARALLEL_ANY,
    "parallel-any": RunnerMode.PARALLEL_ANY,
    "parallel_all": RunnerMode.PARALLEL_ALL,
    "parallel-all": RunnerMode.PARALLEL_ALL,
    "serial": RunnerMode.SEQUENTIAL,
}


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limit_sleep_s: float | None = None
    timeout_next_provider: bool = False
    retryable_next_provider: bool = False


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
        object.__setattr__(self, "mode", RunnerConfigBuilder._normalize_mode(self.mode))
        object.__setattr__(
            self, "schema", RunnerConfigBuilder._resolve_optional_path(self.schema)
        )
        object.__setattr__(
            self, "judge", RunnerConfigBuilder._resolve_optional_path(self.judge)
        )
        object.__setattr__(
            self,
            "metrics_path",
            RunnerConfigBuilder._resolve_optional_path(self.metrics_path),
        )


class RunnerConfigBuilder:
    def __init__(self, runner_config: RunnerConfig | None = None) -> None:
        self._base = runner_config

    def build_compare_config(
        self,
        *,
        mode: RunnerMode | str,
        aggregate: str | None,
        quorum: int | None,
        tie_breaker: str | None,
        provider_weights: dict[str, float] | None,
        schema: Path | str | None,
        judge: Path | str | None,
        judge_provider: ProviderConfig | None,
        max_concurrency: int | None,
        rpm: int | None,
        backoff: BackoffPolicy | None,
        shadow_provider: ProviderSPI | None,
        metrics_path: Path | str,
    ) -> RunnerConfig:
        sanitized_mode = self._normalize_mode(mode)
        sanitized_schema = self._resolve_optional_path(schema)
        sanitized_judge = self._resolve_optional_path(judge)
        sanitized_quorum = self._sanitize_positive_int(quorum)
        sanitized_max_concurrency = self._sanitize_positive_int(max_concurrency)
        sanitized_rpm = self._sanitize_positive_int(rpm)
        sanitized_metrics = self._resolve_optional_path(metrics_path)
        if sanitized_metrics is None:  # pragma: no cover - defensive
            raise ValueError("metrics_path must be provided")

        is_weighted = self._is_weighted_aggregate(aggregate)
        if is_weighted and provider_weights is None:
            raise ValueError("aggregate=weighted_vote requires provider_weights")
        sanitized_weights = provider_weights if is_weighted else None

        if self._base is None:
            return RunnerConfig(
                mode=sanitized_mode,
                aggregate=aggregate,
                quorum=sanitized_quorum,
                tie_breaker=tie_breaker,
                provider_weights=sanitized_weights,
                schema=sanitized_schema,
                judge=sanitized_judge,
                judge_provider=judge_provider,
                max_concurrency=sanitized_max_concurrency,
                rpm=sanitized_rpm,
                backoff=backoff or BackoffPolicy(),
                shadow_provider=shadow_provider,
                metrics_path=sanitized_metrics,
            )

        config = self._base
        judge_value = config.judge
        judge_provider_value = config.judge_provider
        if config.judge_provider is None and judge_provider is not None:
            judge_value = sanitized_judge
            judge_provider_value = judge_provider

        backoff_value = backoff if backoff is not None else config.backoff
        shadow_value = (
            shadow_provider if shadow_provider is not None else config.shadow_provider
        )
        provider_weights_value = (
            sanitized_weights
            if sanitized_weights is not None
            else config.provider_weights
        )

        return replace(
            config,
            judge=judge_value,
            judge_provider=judge_provider_value,
            backoff=backoff_value,
            shadow_provider=shadow_value,
            provider_weights=provider_weights_value,
            metrics_path=sanitized_metrics,
        )

    @staticmethod
    def _normalize_mode(value: RunnerMode | str) -> RunnerMode:
        if isinstance(value, RunnerMode):
            return value
        candidate = value.strip().lower().replace("-", "_")
        candidate = candidate.replace(" ", "_")
        alias = _MODE_ALIASES.get(candidate)
        if alias is not None:
            return alias
        try:
            return RunnerMode(candidate)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"unknown mode: {value}") from exc

    @staticmethod
    def _resolve_optional_path(value: Path | str | None) -> Path | None:
        if value is None:
            return None
        if isinstance(value, Path):
            return value
        if not value:
            return None
        return Path(value).expanduser().resolve()

    @staticmethod
    def _sanitize_positive_int(value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            return None
        return value

    @staticmethod
    def _is_weighted_aggregate(value: str | None) -> bool:
        if not value:
            return False
        normalized = value.strip().lower().replace("-", "_")
        return normalized in {"weighted_vote", "weighted"}


__all__ = [
    "BackoffPolicy",
    "RunnerMode",
    "RunnerConfig",
    "RunnerConfigBuilder",
]
