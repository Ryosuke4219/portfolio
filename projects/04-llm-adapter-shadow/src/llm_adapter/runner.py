"""Provider runner with fallback handling."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from .errors import ProviderSkip, RateLimitError, RetriableError, TimeoutError
from .metrics import log_event
from .provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from .shadow import DEFAULT_METRICS_PATH, run_with_shadow
from .utils import content_hash

MetricsPath = str | Path | None


class Runner:
    """Attempt providers sequentially until one succeeds."""

    def __init__(self, providers: Sequence[ProviderSPI]):
        if not providers:
            raise ValueError("Runner requires at least one provider")
        self.providers: list[ProviderSPI] = list(providers)

    def run(
        self,
        request: ProviderRequest,
        shadow: ProviderSPI | None = None,
        shadow_metrics_path: MetricsPath = DEFAULT_METRICS_PATH,
    ) -> ProviderResponse:
        """Execute ``request`` with fallback semantics.

        Parameters
        ----------
        request:
            The prompt/options payload shared across providers.
        shadow:
            Optional provider that will be executed in the background for
            telemetry purposes.
        shadow_metrics_path:
            JSONL file path for recording metrics. ``None`` disables logging.
        """

        last_err: Exception | None = None
        metrics_path_str = None if shadow_metrics_path is None else str(Path(shadow_metrics_path))
        request_fingerprint = content_hash(
            "runner", request.prompt, request.options, request.max_tokens
        )

        def _record_skip(err: ProviderSkip, attempt: int, provider: ProviderSPI) -> None:
            if not metrics_path_str:
                return
            log_event(
                "provider_skipped",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(
                    provider.name(), request.prompt, request.options, request.max_tokens
                ),
                provider=provider.name(),
                attempt=attempt,
                total_providers=len(self.providers),
                reason=getattr(err, "reason", None),
                error_message=str(err),
            )

        def _provider_model(provider: ProviderSPI) -> str | None:
            for attr in ("model", "_model"):
                value = getattr(provider, attr, None)
                if isinstance(value, str) and value:
                    return value
            return None

        def _elapsed_ms(start_ts: float) -> int:
            return max(0, int((time.time() - start_ts) * 1000))

        def _log_provider_call(
            provider: ProviderSPI,
            attempt: int,
            *,
            status: str,
            latency_ms: int | None,
            tokens_in: int | None,
            tokens_out: int | None,
            error: Exception | None = None,
        ) -> None:
            if not metrics_path_str:
                return

            metadata = request.metadata or {}
            error_type = type(error).__name__ if error is not None else None
            error_message = str(error) if error is not None else None

            log_event(
                "provider_call",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(
                    provider.name(), request.prompt, request.options, request.max_tokens
                ),
                provider=provider.name(),
                model=_provider_model(provider),
                attempt=attempt,
                total_providers=len(self.providers),
                status=status,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error_type=error_type,
                error_message=error_message,
                shadow_used=shadow is not None,
                trace_id=metadata.get("trace_id"),
                project_id=metadata.get("project_id"),
            )

        for attempt_index, provider in enumerate(self.providers, start=1):
            attempt_started = time.time()
            try:
                response = run_with_shadow(provider, shadow, request, metrics_path=metrics_path_str)
            except ProviderSkip as err:
                last_err = err
                _record_skip(err, attempt_index, provider)
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                continue
            except RateLimitError as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                time.sleep(0.05)
            except (TimeoutError, RetriableError) as err:
                last_err = err
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="error",
                    latency_ms=_elapsed_ms(attempt_started),
                    tokens_in=None,
                    tokens_out=None,
                    error=err,
                )
                continue
            else:
                _log_provider_call(
                    provider,
                    attempt_index,
                    status="ok",
                    latency_ms=response.latency_ms,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=None,
                )
                return response
        if metrics_path_str:
            log_event(
                "provider_chain_failed",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                provider_attempts=len(self.providers),
                providers=[provider.name() for provider in self.providers],
                last_error_type=type(last_err).__name__ if last_err else None,
                last_error_message=str(last_err) if last_err else None,
            )
        raise last_err if last_err is not None else RuntimeError("No providers succeeded")


__all__ = ["Runner"]
