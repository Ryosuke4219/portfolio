"""Connection helpers for the Ollama provider."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from typing import Any, cast

from ..config import ProviderConfig
from ..errors import ProviderSkip, SkipReason
from ._requests_compat import create_session, SessionProtocol
from .ollama_client import OllamaClient

DEFAULT_HOST = "http://127.0.0.1:11434"


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class OllamaConnectionHelper:
    """Resolves host, timeout and offline behaviour for the Ollama client."""

    host: str
    timeout: float
    pull_timeout: float
    offline: bool
    auto_pull: bool
    allow_network: bool
    client: OllamaClient

    @classmethod
    def from_config(
        cls,
        config: ProviderConfig,
        *,
        client_cls: type[OllamaClient] | None = None,
        session_factory: Callable[[], SessionProtocol] | None = None,
    ) -> OllamaConnectionHelper:
        raw = config.raw if isinstance(config.raw, Mapping) else {}
        client_type = client_cls or OllamaClient
        session_fn = session_factory or create_session

        host_candidate: str | None = None
        raw_host = raw.get("host") or raw.get("base_url") if raw else None
        if isinstance(raw_host, str):
            host_candidate = raw_host
        elif raw_host is not None:
            host_candidate = str(raw_host)
        if host_candidate is None and config.endpoint:
            host_candidate = config.endpoint

        env_host = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST")
        host_value = (host_candidate or env_host or DEFAULT_HOST).strip()
        if not host_value:
            raise ProviderSkip(
                "ollama: endpoint not configured",
                reason=SkipReason.MISSING_OLLAMA_ENDPOINT,
            )

        timeout_default = float(config.timeout_s or 60)
        pull_timeout_default = 300.0
        timeout_env = os.getenv("OLLAMA_TIMEOUT_S")
        pull_timeout_env = os.getenv("OLLAMA_PULL_TIMEOUT_S")
        timeout_value = _coerce_float(timeout_env, timeout_default)
        pull_timeout_value = _coerce_float(pull_timeout_env, pull_timeout_default)
        if raw:
            if "timeout_s" in raw:
                timeout_value = _coerce_float(raw.get("timeout_s"), timeout_value)
            if "pull_timeout_s" in raw:
                pull_timeout_value = _coerce_float(
                    raw.get("pull_timeout_s"), pull_timeout_value
                )

        offline_env = os.getenv("LLM_ADAPTER_OFFLINE")
        ci_flag = os.getenv("CI", "").strip().lower() == "true"
        if offline_env is not None:
            normalized_offline = offline_env.strip().lower()
            if normalized_offline in {"0", "false"}:
                offline = False
            elif normalized_offline in {"1", "true", "yes", "on"}:
                offline = True
            else:
                offline = _coerce_bool(offline_env, True)
        else:
            offline = ci_flag

        session_override = raw.get("session") if raw else None
        client_override = raw.get("client") if raw else None
        allow_network = session_override is not None or client_override is not None

        auto_pull_env = os.getenv("OLLAMA_AUTO_PULL")
        auto_pull_source = raw.get("auto_pull") if raw else None
        auto_pull_value = _coerce_bool(auto_pull_source, True)
        auto_pull_value = _coerce_bool(auto_pull_env, auto_pull_value)

        if client_override is not None:
            client = cast(OllamaClient, client_override)
        else:
            if session_override is not None:
                session = cast(SessionProtocol, session_override)
            else:
                session = session_fn()
            client = client_type(
                host=host_value,
                session=session,
                timeout=timeout_value,
                pull_timeout=pull_timeout_value,
            )

        return cls(
            host=host_value,
            timeout=timeout_value,
            pull_timeout=pull_timeout_value,
            offline=offline,
            auto_pull=auto_pull_value,
            allow_network=allow_network,
            client=client,
        )


__all__ = ["DEFAULT_HOST", "OllamaConnectionHelper"]


