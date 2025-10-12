from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Any, cast

from adapter.core import providers as provider_module
from adapter.core.config import ProviderConfig
from adapter.core.metrics.costs import estimate_cost
from adapter.core.metrics.models import RunMetric

from .utils import _sanitize_message, LOGGER

ProviderRequest = provider_module.ProviderRequest
ProviderResponse = provider_module.ProviderResponse
TokenUsage = provider_module.TokenUsage
Classifier = Callable[[Exception, ProviderConfig, str], tuple[str, str]]


class RateLimiter:
    """簡易 RPM 制御。"""

    def __init__(self, rpm: int) -> None:
        self._rpm = max(0, int(rpm or 0))
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._rpm <= 0:
            return
        window = 60.0
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= window:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._rpm:
                    self._timestamps.append(now)
                    return
                wait = window - (now - self._timestamps[0])
            await asyncio.sleep(max(wait, 0.0))


@dataclass
class PromptResult:
    index: int
    prompt: str
    response: ProviderResponse | None
    metric: RunMetric
    output_text: str
    error: str | None
    error_kind: str | None = None


def _request_options(config: ProviderConfig) -> dict[str, Any]:
    raw_options = config.raw.get("options")
    if isinstance(raw_options, Mapping):
        return dict(raw_options)
    return {}


def _request_metadata(config: ProviderConfig) -> Mapping[str, Any] | None:
    raw_metadata = config.raw.get("metadata")
    if isinstance(raw_metadata, Mapping):
        return dict(raw_metadata)
    return None


def _build_request(prompt: str, config: ProviderConfig) -> ProviderRequest:
    model = (config.model or config.provider).strip() or config.provider
    timeout: float | None = None
    if config.timeout_s > 0:
        timeout = float(config.timeout_s)
    return ProviderRequest(
        model=model,
        prompt=prompt,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        top_p=config.top_p,
        timeout_s=timeout,
        metadata=_request_metadata(config),
        options=_request_options(config),
    )


async def _process_prompt(
    index: int,
    prompt: str,
    provider: object,
    config: ProviderConfig,
    limiter: RateLimiter,
    semaphore: asyncio.Semaphore,
    lang: str,
    classify_error: Classifier,
) -> PromptResult:
    async with semaphore:
        await limiter.wait()
        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        try:
            request = _build_request(prompt, config)
            invoke = getattr(provider, "invoke", None)
            if not callable(invoke):
                raise TypeError("Provider must implement invoke(request).")
            response = await loop.run_in_executor(  # type: ignore[arg-type]
                None, invoke, request
            )
        except Exception as exc:  # pragma: no cover - 実 API 呼び出し向けの防御
            latency_ms = int((time.perf_counter() - start) * 1000)
            friendly, error_kind = classify_error(exc, config, lang)
            LOGGER.error(_sanitize_message(friendly))
            LOGGER.debug("provider error", exc_info=True)
            stub = ProviderResponse(
                text="",
                latency_ms=latency_ms,
                token_usage=TokenUsage(prompt=0, completion=0),
            )
            metric = RunMetric.from_resp(
                config, stub, prompt, cost_usd=0.0, error=friendly
            )
            return PromptResult(
                index=index,
                prompt=prompt,
                response=None,
                metric=metric,
                output_text="",
                error=friendly,
                error_kind=error_kind,
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        provider_response = cast(ProviderResponse, response)

        if hasattr(response, "input_tokens"):
            input_tokens = int(provider_response.input_tokens)
        else:
            input_tokens = 0

        if hasattr(response, "output_tokens"):
            output_tokens = int(provider_response.output_tokens)
        else:
            output_tokens = 0

        if hasattr(response, "output_text"):
            output_text = provider_response.output_text
        elif hasattr(response, "text"):
            output_text = cast(str, provider_response.text)
        else:
            output_text = ""

        if hasattr(response, "latency_ms"):
            latency_ms = int(provider_response.latency_ms)
        else:
            latency_ms = elapsed_ms

        cost = estimate_cost(config, input_tokens, output_tokens)
        metric_base = ProviderResponse(
            text=output_text,
            latency_ms=latency_ms,
            token_usage=TokenUsage(prompt=input_tokens, completion=output_tokens),
        )
        metric = RunMetric.from_resp(config, metric_base, prompt, cost_usd=cost)
        return PromptResult(
            index=index,
            prompt=prompt,
            response=provider_response,
            metric=metric,
            output_text=output_text,
            error=None,
        )


async def execute_prompts(
    prompts: list[str],
    provider: object,
    config: ProviderConfig,
    concurrency: int,
    rpm: int,
    lang: str,
    classify_error: Classifier,
) -> list[PromptResult]:
    limiter = RateLimiter(rpm)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    tasks = [
        asyncio.create_task(
            _process_prompt(
                idx, prompt, provider, config, limiter, semaphore, lang, classify_error
            )
        )
        for idx, prompt in enumerate(prompts)
    ]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda item: item.index)


__all__ = ["RateLimiter", "PromptResult", "execute_prompts"]
