"""ShadowRunner 補助。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import ProviderConfig
from .execution.shadow_runner import ShadowRunner, ShadowRunnerResult

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
else:  # pragma: no cover - 実行時フォールバック
    try:
        from src.llm_adapter.provider_spi import ProviderSPI  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - テスト用フォールバック

        class ProviderSPI:  # pragma: no cover - 型補完不要
            """プロバイダ SPI フォールバック."""


@dataclass(slots=True)
class ShadowSession:
    """シャドウ呼び出しのライフサイクル管理。"""

    runner: ShadowRunner
    fallback_provider_id: str | None


def start_shadow_session(
    shadow_provider: ProviderSPI | None, provider_config: ProviderConfig, prompt: str
) -> ShadowSession | None:
    if shadow_provider is None:
        return None
    runner = ShadowRunner(shadow_provider)
    runner.start(provider_config, prompt)
    return ShadowSession(runner=runner, fallback_provider_id=runner.provider_id)


def finalize_shadow_session(
    session: ShadowSession | None,
) -> tuple[ShadowRunnerResult | None, str | None]:
    if session is None:
        return None, None
    result = session.runner.finalize()
    return result, session.fallback_provider_id


__all__ = [
    "ShadowSession",
    "start_shadow_session",
    "finalize_shadow_session",
]

