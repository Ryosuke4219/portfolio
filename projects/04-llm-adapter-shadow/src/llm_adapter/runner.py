"""Provider runner with fallback handling."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Sequence, Union

from .provider_spi import ProviderSPI, ProviderRequest, ProviderResponse
from .errors import TimeoutError, RateLimitError, RetriableError
from .shadow import run_with_shadow, DEFAULT_METRICS_PATH
from .metrics import log_event
from .utils import content_hash

MetricsPath = Optional[Union[str, Path]]


class Runner:
    """Attempt providers sequentially until one succeeds."""

    def __init__(self, providers: Sequence[ProviderSPI]):
        if not providers:
            raise ValueError("Runner requires at least one provider")
        self.providers: List[ProviderSPI] = list(providers)

    def run(
        self,
        request: ProviderRequest,
        shadow: Optional[ProviderSPI] = None,
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

        last_err: Optional[Exception] = None
        metrics_path_str = None if shadow_metrics_path is None else str(Path(shadow_metrics_path))
        request_fingerprint = content_hash("runner", request.prompt, request.options)

        def _record_error(err: Exception, attempt: int, provider: ProviderSPI) -> None:
            if not metrics_path_str:
                return
            log_event(
                "provider_error",
                metrics_path_str,
                request_fingerprint=request_fingerprint,
                request_hash=content_hash(provider.name(), request.prompt, request.options),
                provider=provider.name(),
                attempt=attempt,
                total_providers=len(self.providers),
                error_type=type(err).__name__,
                error_message=str(err),
            )

        for attempt_index, provider in enumerate(self.providers, start=1):
            try:
                response = run_with_shadow(provider, shadow, request, metrics_path=metrics_path_str)
            except RateLimitError as err:
                last_err = err
                _record_error(err, attempt_index, provider)
                time.sleep(0.05)
            except (TimeoutError, RetriableError) as err:
                last_err = err
                _record_error(err, attempt_index, provider)
                continue
            else:
                if metrics_path_str:
                    log_event(
                        "provider_success",
                        metrics_path_str,
                        request_fingerprint=request_fingerprint,
                        request_hash=content_hash(provider.name(), request.prompt, request.options),
                        provider=provider.name(),
                        attempt=attempt_index,
                        total_providers=len(self.providers),
                        latency_ms=response.latency_ms,
                        shadow_used=shadow is not None,
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
