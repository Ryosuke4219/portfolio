from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from adapter.core import providers as provider_module
from adapter.core.config import ProviderConfig
from adapter.core.metrics import RunMetric, estimate_cost

from .utils import LOGGER, _sanitize_message

ProviderResponse = provider_module.ProviderResponse
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
            response: ProviderResponse = await loop.run_in_executor(
                None, provider.generate, prompt
            )
        except Exception as exc:  # pragma: no cover - 実 API 呼び出し向けの防御
            latency_ms = int((time.perf_counter() - start) * 1000)
            friendly, error_kind = classify_error(exc, config, lang)
            LOGGER.error(_sanitize_message(friendly))
            LOGGER.debug("provider error", exc_info=True)
            stub = ProviderResponse(
                output_text="",
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
            )
            metric = RunMetric.from_resp(config, stub, prompt, cost_usd=0.0, error=friendly)
            return PromptResult(
                index=index,
                prompt=prompt,
                response=None,
                metric=metric,
                output_text="",
                error=friendly,
                error_kind=error_kind,
            )
        cost = estimate_cost(
            config,
            getattr(response, "input_tokens", 0),
            getattr(response, "output_tokens", 0),
        )
        metric = RunMetric.from_resp(config, response, prompt, cost_usd=cost)
        return PromptResult(
            index=index,
            prompt=prompt,
            response=response,
            metric=metric,
            output_text=getattr(response, "output_text", ""),
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
            _process_prompt(idx, prompt, provider, config, limiter, semaphore, lang, classify_error)
        )
        for idx, prompt in enumerate(prompts)
    ]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda item: item.index)


__all__ = ["RateLimiter", "PromptResult", "execute_prompts"]
