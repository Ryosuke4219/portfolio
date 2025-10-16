"""Utility helpers for OpenRouter authentication and environment resolution."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from collections.abc import Callable
from dataclasses import dataclass
import os
import re
from typing import Any, cast

from ..config import ProviderConfig
from ._requests_compat import SessionProtocol, create_session

__all__ = [
    "OPTION_CREDENTIAL_KEYS",
    "INTERNAL_OPTION_KEYS",
    "normalize_option_credential",
    "OpenRouterAuthContext",
    "prepare_auth",
]


OPTION_CREDENTIAL_KEYS: tuple[str, ...] = (
    "api_key",
    "api_token",
    "token",
    "access_token",
)


INTERNAL_OPTION_KEYS: set[str] = {
    "stream",
    "request_timeout_s",
    "REQUEST_TIMEOUT_S",
    *OPTION_CREDENTIAL_KEYS,
}


_LITERAL_ENV_VALUE_PREFIXES = ("file:", "mailto:")
_INLINE_SECRET_PREFIXES = (
    "sk-",
    "sk_",
    "rk-",
    "rk_",
    "pk-",
    "pk_",
    "ak-",
    "ak_",
    "gsk-",
    "gsk_",
    "hf-",
    "hf_",
    "xai-",
    "xai_",
)
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class OpenRouterAuthContext:
    """Resolved OpenRouter authentication configuration."""

    session: SessionProtocol
    api_key: str
    base_url: str
    default_timeout: float
    auth_env_name: str
    configured_auth_env: str
    config_options: dict[str, Any]


def normalize_option_credential(value: object) -> str:
    """Normalize credentials provided via request options."""

    if value is None:
        return ""
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate


def _resolve_env(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    env_name = name.strip()
    if not env_name or env_name.upper() == "NONE":
        return ""
    return (os.getenv(env_name) or "").strip()


def _looks_like_env_name(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    return bool(_ENV_NAME_PATTERN.fullmatch(candidate))


def _is_literal_env_value(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if _looks_like_env_name(candidate):
        return False
    if "://" in candidate:
        return True
    candidate_lower = candidate.lower()
    if any(candidate_lower.startswith(prefix) for prefix in _INLINE_SECRET_PREFIXES):
        return True
    if any(candidate_lower.startswith(prefix) for prefix in _LITERAL_ENV_VALUE_PREFIXES):
        return True
    return True


def _resolve_literal_or_env(name: str) -> str:
    if not isinstance(name, str):
        return ""
    candidate = name.strip()
    if not candidate:
        return ""
    if _is_literal_env_value(candidate):
        return candidate
    resolved = _resolve_env(candidate)
    if resolved:
        return resolved
    candidate_lower = candidate.lower()
    if any(candidate_lower.startswith(prefix) for prefix in _INLINE_SECRET_PREFIXES):
        return candidate
    return resolved


def _resolve_from_env_mapping(
    raw_env: Mapping[str, object] | None, default_name: str
) -> str:
    if not isinstance(default_name, str):
        return ""
    override_name = None
    if isinstance(raw_env, Mapping):
        override_name = raw_env.get(default_name)
    candidates: list[str] = []
    if isinstance(override_name, str):
        candidate = override_name.strip()
        if candidate:
            candidates.append(candidate)
    elif isinstance(override_name, Iterable) and not isinstance(override_name, Mapping):
        for item in override_name:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
    for candidate in candidates:
        resolved_value = _resolve_literal_or_env(candidate)
        if resolved_value:
            return resolved_value
    return _resolve_literal_or_env(default_name)


def prepare_auth(
    config: ProviderConfig,
    *,
    session_factory: Callable[[], SessionProtocol] | None = None,
) -> OpenRouterAuthContext:
    """Resolve OpenRouter authentication and connection settings."""

    raw = config.raw if isinstance(config.raw, Mapping) else {}
    raw_env = raw.get("env") if isinstance(raw, Mapping) else None

    auth_env_name = ""
    if isinstance(config.auth_env, str):
        auth_env_name = config.auth_env.strip()
    if not auth_env_name or auth_env_name.upper() == "NONE":
        auth_env_name = "OPENROUTER_API_KEY"
    configured_auth_env = auth_env_name

    override_candidates: list[str] = []
    resolved_auth_env_name = auth_env_name
    if isinstance(raw_env, Mapping):
        override_name = raw_env.get(auth_env_name)
        if isinstance(override_name, str):
            candidate = override_name.strip()
            if candidate:
                override_candidates.append(candidate)
        elif isinstance(override_name, Iterable) and not isinstance(override_name, Mapping):
            for item in override_name:
                if isinstance(item, str):
                    candidate = item.strip()
                    if candidate and candidate not in override_candidates:
                        override_candidates.append(candidate)
    if override_candidates:
        resolved_auth_env_name = override_candidates[0]

    mapped_api_key = _resolve_from_env_mapping(raw_env, "OPENROUTER_API_KEY")
    seen_candidates: set[str] = set()
    api_key_value = ""
    for candidate_name in override_candidates:
        normalized = candidate_name.strip()
        if not normalized or normalized in seen_candidates:
            continue
        seen_candidates.add(normalized)
        resolved_value = _resolve_literal_or_env(normalized)
        if resolved_value:
            api_key_value = resolved_value
            break
    if not api_key_value:
        configured_value = _resolve_from_env_mapping(raw_env, auth_env_name)
        if configured_value:
            api_key_value = configured_value
    if not api_key_value and mapped_api_key:
        api_key_value = mapped_api_key
    if not api_key_value:
        api_key_obj = raw.get("api_key")
        if isinstance(api_key_obj, str):
            api_key_value = api_key_obj.strip()
        elif api_key_obj is not None:
            api_key_value = str(api_key_obj).strip()
    if not api_key_value:
        api_key_value = mapped_api_key

    session_override = raw.get("session") if isinstance(raw, Mapping) else None
    if session_override is None:
        factory = session_factory or create_session
        session: SessionProtocol = factory()
    else:
        session = cast(SessionProtocol, session_override)

    base_url_value: str | None = None
    mapped_base_url = _resolve_from_env_mapping(raw_env, "OPENROUTER_BASE_URL")
    if mapped_base_url:
        base_url_value = mapped_base_url
    else:
        env_candidate = _resolve_env(raw.get("base_url_env"))
        if env_candidate:
            base_url_value = env_candidate
    if base_url_value is None and isinstance(raw, Mapping):
        base_candidate = raw.get("base_url")
        if isinstance(base_candidate, str):
            base_url_value = base_candidate
    if base_url_value is None and config.endpoint:
        base_url_value = config.endpoint
    default_base = mapped_base_url or "https://openrouter.ai/api/v1"
    base_url = (base_url_value or default_base).rstrip("/")

    headers = getattr(session, "headers", None)
    if isinstance(headers, MutableMapping):
        headers.setdefault("Content-Type", "application/json")
        if api_key_value:
            headers["Authorization"] = f"Bearer {api_key_value}"

    default_timeout = float(config.timeout_s or 30)
    options_from_config = raw.get("options") if isinstance(raw, Mapping) else None
    if isinstance(options_from_config, Mapping):
        config_options = {
            key: value
            for key, value in options_from_config.items()
            if key not in INTERNAL_OPTION_KEYS
        }
    else:
        config_options = {}

    return OpenRouterAuthContext(
        session=session,
        api_key=api_key_value or "",
        base_url=base_url,
        default_timeout=default_timeout,
        auth_env_name=resolved_auth_env_name,
        configured_auth_env=configured_auth_env,
        config_options=config_options,
    )
