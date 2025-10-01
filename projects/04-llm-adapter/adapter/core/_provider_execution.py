"""プロバイダ呼び出しの補助。"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep
from typing import TYPE_CHECKING

from .config import ProviderConfig
from .errors import (
    AuthError,
    ConfigError,
    ProviderSkip,
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from .providers import BaseProvider, ProviderResponse

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .runner_api import BackoffPolicy
else:  # pragma: no cover - 実行時フォールバック
    BackoffPolicy = object


@dataclass(slots=True)
class _ProviderCallResult:
    response: ProviderResponse
    status: str
    failure_kind: str | None
    error_message: str | None
    latency_ms: int
    retries: int
    error: Exception | None = None
    backoff_next_provider: bool = False


class ProviderCallExecutor:
    """プロバイダ呼び出しの結果を構築する。"""

    def __init__(self, backoff: BackoffPolicy | None) -> None:
        self._backoff = backoff

    def execute(
        self, provider_config: ProviderConfig, provider: BaseProvider, prompt: str
    ) -> _ProviderCallResult:
        result = self._invoke_provider(provider_config, provider, prompt)
        status, failure_kind = self._check_timeout(
            provider_config, result.latency_ms, result.status, result.failure_kind
        )
        status, failure_kind = self._enforce_output_guard(
            result.response.output_text, status, failure_kind
        )
        result.status = status
        result.failure_kind = failure_kind
        return result

    def _invoke_provider(
        self, provider_config: ProviderConfig, provider: BaseProvider, prompt: str
    ) -> _ProviderCallResult:
        start = perf_counter()
        try:
            response = provider.generate(prompt)
        except ProviderSkip as exc:
            latency_ms = int((perf_counter() - start) * 1000)
            response = self._build_error_response(prompt, latency_ms)
            return _ProviderCallResult(
                response=response,
                status="skip",
                failure_kind="skip",
                error_message=str(exc),
                latency_ms=latency_ms,
                retries=1,
                error=exc,
                backoff_next_provider=True,
            )
        except AuthError as exc:
            return self._build_error_result(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="auth",
                advance=True,
            )
        except ConfigError as exc:
            return self._build_error_result(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="config",
                advance=True,
            )
        except RateLimitError as exc:
            return self._handle_backoff_error(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="rate_limit",
                default_advance=True,
            )
        except TimeoutError as exc:
            return self._handle_backoff_error(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="timeout",
                default_advance=False,
            )
        except RetriableError as exc:
            return self._handle_backoff_error(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="retryable",
                default_advance=False,
            )
        except Exception as exc:  # pragma: no cover - 実プロバイダ利用時の防御
            return self._build_error_result(
                prompt,
                start,
                exc,
                status="error",
                failure_kind="provider_error",
                advance=False,
            )
        latency_ms = response.latency_ms
        return _ProviderCallResult(
            response=response,
            status="ok",
            failure_kind=None,
            error_message=None,
            latency_ms=latency_ms,
            retries=1,
        )

    def _build_error_result(
        self,
        prompt: str,
        started_at: float,
        error: Exception,
        *,
        status: str,
        failure_kind: str,
        advance: bool,
    ) -> _ProviderCallResult:
        latency_ms = int((perf_counter() - started_at) * 1000)
        response = self._build_error_response(prompt, latency_ms)
        return _ProviderCallResult(
            response=response,
            status=status,
            failure_kind=failure_kind,
            error_message=str(error),
            latency_ms=latency_ms,
            retries=1,
            error=error,
            backoff_next_provider=advance,
        )

    def _handle_backoff_error(
        self,
        prompt: str,
        started_at: float,
        error: Exception,
        *,
        status: str,
        failure_kind: str,
        default_advance: bool,
    ) -> _ProviderCallResult:
        advance = self._apply_backoff(error)
        if not advance:
            advance = default_advance
        return self._build_error_result(
            prompt,
            started_at,
            error,
            status=status,
            failure_kind=failure_kind,
            advance=advance,
        )

    @staticmethod
    def _build_error_response(prompt: str, latency_ms: int) -> ProviderResponse:
        return ProviderResponse(
            output_text="",
            input_tokens=len(prompt.split()),
            output_tokens=0,
            latency_ms=latency_ms,
        )

    def _apply_backoff(self, error: Exception) -> bool:
        policy = self._backoff
        if policy is None:
            return False
        should_advance = False
        delay = 0.0
        if isinstance(error, RateLimitError):
            delay = float(policy.rate_limit_sleep_s or 0.0)
            should_advance = True
        elif isinstance(error, TimeoutError):
            should_advance = bool(policy.timeout_next_provider)
        elif isinstance(error, RetriableError):
            should_advance = bool(policy.retryable_next_provider)
        if delay > 0.0:
            sleep(delay)
        return should_advance

    @staticmethod
    def _check_timeout(
        provider_config: ProviderConfig,
        latency_ms: int,
        status: str,
        failure_kind: str | None,
    ) -> tuple[str, str | None]:
        if (
            provider_config.timeout_s > 0
            and latency_ms > provider_config.timeout_s * 1000
            and status == "ok"
        ):
            return "error", "timeout"
        return status, failure_kind

    @staticmethod
    def _enforce_output_guard(
        output_text: str | None, status: str, failure_kind: str | None
    ) -> tuple[str, str | None]:
        if (output_text is None or not output_text.strip()) and status == "ok":
            return "error", failure_kind or "guard_violation"
        return status, failure_kind


__all__ = [
    "ProviderCallExecutor",
    "_ProviderCallResult",
]

