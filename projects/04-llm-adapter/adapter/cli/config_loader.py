from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import os
from pathlib import Path
import textwrap

from adapter.core.config import load_provider_config, ProviderConfig

from .args import ProviderOption
from .utils import _msg, _sanitize_message, EXIT_ENV_ERROR, LOGGER


@dataclass(slots=True)
class PreparedProviderConfig:
    config: ProviderConfig
    cli_has_credentials: bool


def load_env_from_option(env: str | None, lang: str) -> None:
    if not env:
        return
    _load_env_file(Path(env).expanduser().resolve(), lang)


def load_provider_configuration(
    provider_path: str,
    model_override: str | None,
    option_pairs: Iterable[ProviderOption] | None,
) -> PreparedProviderConfig:
    config = load_provider_config(Path(provider_path).expanduser().resolve())
    cli_options: dict[str, object] = {}
    if option_pairs:
        for key, value in option_pairs:
            cli_options[key] = value
    cli_has_credentials = bool(cli_options and _has_embedded_credentials(cli_options))

    raw_copy: dict[str, object] | None = None

    def ensure_raw_copy() -> dict[str, object]:
        nonlocal raw_copy
        if raw_copy is None:
            raw_value = config.raw if isinstance(config.raw, Mapping) else {}
            raw_copy = dict(deepcopy(raw_value))
        return raw_copy

    if cli_options:
        raw_copy_map = ensure_raw_copy()
        existing_options = raw_copy_map.get("options")
        merged_options: dict[str, object]
        if isinstance(existing_options, Mapping):
            merged_options = dict(deepcopy(existing_options))
        else:
            merged_options = {}
        merged_options.update(cli_options)
        raw_copy_map["options"] = merged_options
        config = replace(config, raw=raw_copy_map)

    override_model = (model_override or "").strip()
    if override_model:
        raw_copy_map = ensure_raw_copy()
        raw_copy_map["model"] = override_model
        config = replace(config, model=override_model, raw=raw_copy_map)

    return PreparedProviderConfig(config=config, cli_has_credentials=cli_has_credentials)


def ensure_credentials(config: ProviderConfig, cli_has_credentials: bool, lang: str) -> int | None:
    auth_env = (config.auth_env or "").strip()
    raw_mapping = config.raw if isinstance(config.raw, Mapping) else None
    raw_env = raw_mapping.get("env") if isinstance(raw_mapping, Mapping) else None
    raw_options = raw_mapping.get("options") if isinstance(raw_mapping, Mapping) else None
    aliases: list[str] = []
    literal_credentials: list[str] = []

    if auth_env and isinstance(raw_env, Mapping):
        alias_raw = raw_env.get(auth_env)
        candidate = _normalize_credential(alias_raw)
        if candidate and candidate.upper() != "NONE":
            if _looks_like_env_var_name(candidate):
                aliases.append(candidate)
            else:
                literal_credentials.append(candidate)

    env_candidates = [auth_env, *aliases]
    requires_env = bool(auth_env and auth_env.upper() != "NONE")
    resolved_credentials = False
    if requires_env:
        resolved_credentials = any(os.getenv(name) for name in env_candidates if name)
        if not resolved_credentials and literal_credentials:
            resolved_credentials = True
        if not resolved_credentials and isinstance(raw_mapping, Mapping):
            resolved_credentials = _has_embedded_credentials(raw_mapping)
        if not resolved_credentials and isinstance(raw_options, Mapping):
            resolved_credentials = _has_embedded_credentials(raw_options)
        if not resolved_credentials and cli_has_credentials:
            resolved_credentials = True
        if not resolved_credentials:
            message = _msg(lang, "api_key_missing", env=auth_env)
            LOGGER.error(_sanitize_message(message))
            return EXIT_ENV_ERROR
    return None


def _looks_like_env_var_name(value: str) -> bool:
    if not value:
        return False
    for ch in value:
        if not (
            "A" <= ch <= "Z"
            or "a" <= ch <= "z"
            or "0" <= ch <= "9"
            or ch == "_"
        ):
            return False
    return True


def _normalize_credential(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _has_embedded_credentials(raw: Mapping[str, object]) -> bool:
    inline_keys = ("api_key", "api_token", "token", "access_token")

    def _search(node: object) -> bool:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in inline_keys and _normalize_credential(value):
                    return True
                if _search(value):
                    return True
            return False
        if isinstance(node, list | tuple | set):
            return any(_search(item) for item in node)
        return False

    return _search(raw)


def _load_env_file(path: Path, lang: str) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            textwrap.dedent(
                """
                python-dotenv がインストールされていないため --env オプションは利用できません。
                `pip install python-dotenv` を実行してください。
                """
            ).strip()
        ) from exc
    if not path.exists():
        raise SystemExit(_msg(lang, "env_missing", path=path))
    load_dotenv(path, override=False)
    LOGGER.info(_sanitize_message(_msg(lang, "env_loaded", path=path)))


__all__ = [
    "PreparedProviderConfig",
    "ensure_credentials",
    "load_env_from_option",
    "load_provider_configuration",
]
