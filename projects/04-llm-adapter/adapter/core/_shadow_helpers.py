"""ShadowRunner 補助。"""

from __future__ import annotations

from dataclasses import dataclass

from .config import ProviderConfig
from .execution.shadow_runner import ShadowRunner, ShadowRunnerResult
from .provider_spi import ProviderSPI


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
