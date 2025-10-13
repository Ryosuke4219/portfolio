"""Shadow runner helpers for :mod:`adapter.core.runner_execution`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._shadow_helpers import finalize_shadow_session, ShadowSession, start_shadow_session

if TYPE_CHECKING:  # pragma: no cover - 型補完用
    from .config import ProviderConfig
    from .execution.shadow_runner import ShadowRunnerResult
    from .provider_spi import ProviderSPI


def open_shadow_session(
    shadow_provider: ProviderSPI | None, provider_config: ProviderConfig, prompt: str
) -> ShadowSession | None:
    """Start a shadow session when a provider is available."""

    return start_shadow_session(shadow_provider, provider_config, prompt)


def close_shadow_session(
    session: ShadowSession | None,
) -> tuple[ShadowRunnerResult | None, str | None]:
    """Finalize a shadow session and return the results."""

    return finalize_shadow_session(session)


__all__ = ["open_shadow_session", "close_shadow_session"]
