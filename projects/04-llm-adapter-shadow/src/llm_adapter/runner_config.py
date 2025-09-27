"""Configuration objects for runner backoff behavior."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackoffPolicy:
    rate_limit_sleep_s: float = 0.05
    timeout_next_provider: bool = True
    retryable_next_provider: bool = True


@dataclass(frozen=True)
class RunnerConfig:
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    max_attempts: int | None = None
