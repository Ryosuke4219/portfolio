"""シャドウプロバイダ実行のヘルパー。"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Thread
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック
        from typing import Protocol

        class ProviderSPI(Protocol):
            """プロバイダ SPI フォールバック."""

from ..config import ProviderConfig
from ..provider_spi import ProviderRequest

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ShadowRunnerResult:
    provider_id: str | None
    latency_ms: int | None = None
    status: str | None = None
    error_message: str | None = None


class ShadowRunner:
    """シャドウプロバイダ呼び出しを管理する。"""

    def __init__(self, provider: ProviderSPI | None) -> None:
        self._provider = provider
        self._thread: Thread | None = None
        self._result: ShadowRunnerResult | None = None
        self._provider_id: str | None = None

    def start(self, provider_config: ProviderConfig, prompt: str) -> None:
        if self._provider is None:
            return
        provider = self._provider
        try:
            provider_id = provider.name()
        except Exception:  # pragma: no cover - name() 実装の防御
            provider_id = None
        self._provider_id = provider_id
        request = ProviderRequest(
            model=provider_config.model,
            prompt=prompt,
            max_tokens=provider_config.max_tokens,
            temperature=provider_config.temperature,
            top_p=provider_config.top_p,
            timeout_s=(
                float(provider_config.timeout_s)
                if provider_config.timeout_s > 0
                else None
            ),
        )
        result = ShadowRunnerResult(provider_id=provider_id)

        def _run() -> None:
            start = perf_counter()
            try:
                response = provider.invoke(request)
            except Exception as exc:  # pragma: no cover - 影響範囲縮小のため
                latency_ms = int((perf_counter() - start) * 1000)
                LOGGER.exception(
                    "Shadow provider %s failed", provider_id, exc_info=exc
                )
                result.status = "error"
                result.error_message = str(exc)
                result.latency_ms = latency_ms
            else:
                latency_ms = int(getattr(response, "latency_ms", 0))
                LOGGER.info(
                    "Shadow provider %s completed in %sms", provider_id, latency_ms
                )
                result.status = "ok"
                result.latency_ms = latency_ms
            finally:
                if result.latency_ms is None:
                    result.latency_ms = int((perf_counter() - start) * 1000)

        thread = Thread(
            target=_run,
            name=f"shadow-{provider_id or 'unknown'}",
            daemon=True,
        )
        thread.start()
        self._thread = thread
        self._result = result

    def finalize(self) -> ShadowRunnerResult | None:
        if self._thread is None:
            return None
        self._thread.join()
        result = self._result
        if result is None:
            return ShadowRunnerResult(provider_id=self._provider_id)
        if result.provider_id is None:
            result.provider_id = self._provider_id
        return result

    @property
    def provider_id(self) -> str | None:
        return self._provider_id


__all__ = ["ShadowRunner", "ShadowRunnerResult"]
