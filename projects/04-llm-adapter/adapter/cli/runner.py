from __future__ import annotations

from argparse import Namespace
import asyncio
from collections.abc import Iterable
import os
import socket
from typing import Protocol

from adapter.core import providers as provider_module
from adapter.core.config import ProviderConfig

from .prompt_io import emit_results, write_metrics
from .prompt_runner import execute_prompts, PromptResult
from .utils import (
    _msg,
    _sanitize_message,
    EXIT_ENV_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_PROVIDER_ERROR,
    EXIT_RATE_LIMIT,
    LOGGER,
)


class ProviderFactoryLike(Protocol):
    def create(self, config: ProviderConfig) -> object: ...


def classify_error(
    exc: Exception,
    config: ProviderConfig,
    lang: str,
    factory: ProviderFactoryLike | None = None,
) -> tuple[str, str]:
    raw_message = str(exc)
    lower = raw_message.lower()
    auth_env = (config.auth_env or "").strip()
    has_auth_env = bool(auth_env and auth_env.upper() != "NONE")
    if "unsupported provider prefix" in lower:
        provider_factory = factory or provider_module.ProviderFactory
        available_fn = getattr(provider_factory, "available", None)
        supported = "unknown"
        if callable(available_fn):
            try:
                choices = available_fn()
            except Exception:  # pragma: no cover - defensive
                choices = ()
            else:
                if isinstance(choices, str):
                    supported = choices
                elif isinstance(choices, Iterable):
                    supported = ", ".join(str(item) for item in choices)
        else:
            try:
                supported = ", ".join(provider_module.ProviderFactory.available())
            except Exception:  # pragma: no cover - defensive
                supported = "unknown"
        return (
            _msg(lang, "unsupported_provider", provider=config.provider, supported=supported),
            "input",
        )
    if has_auth_env and ("environment variable" in lower or "api key" in lower):
        return _msg(lang, "api_key_missing", env=auth_env), "env"
    status_code = getattr(exc, "status_code", None)
    if (
        status_code == 429
        or "429" in lower
        or "rate" in lower
        or "quota" in lower
    ):
        return _msg(lang, "rate_limited"), "rate"
    if (
        isinstance(exc, OSError | socket.gaierror | TimeoutError)
        or "ssl" in lower
        or "dns" in lower
    ):
        return _msg(lang, "network_error"), "network"
    if exc.__class__.__name__.lower().endswith("ratelimiterror"):
        return _msg(lang, "rate_limited"), "rate"
    if exc.__class__.__name__.lower().endswith("authenticationerror") and has_auth_env:
        return _msg(lang, "api_key_missing", env=auth_env), "env"
    sanitized = _sanitize_message(raw_message)
    return _msg(lang, "provider_error", error=sanitized), "provider"


def create_provider(
    factory: ProviderFactoryLike,
    config: ProviderConfig,
    lang: str,
) -> tuple[object | None, int | None]:
    try:
        provider = factory.create(config)
    except Exception as exc:  # pragma: no cover - 生成エラー
        friendly, kind = classify_error(exc, config, lang, factory)
        LOGGER.error(_sanitize_message(friendly))
        return None, _exit_code_for_error_kind(kind)
    return provider, None


def run_prompt_execution(
    args: Namespace,
    prompts: list[str],
    provider: object,
    config: ProviderConfig,
    lang: str,
    factory: ProviderFactoryLike | None,
) -> int:
    concurrency = determine_concurrency(args.parallel, len(prompts))
    try:
        results = asyncio.run(
            execute_prompts(
                prompts,
                provider,
                config,
                concurrency,
                args.rpm,
                lang,
                lambda exc, *_: classify_error(exc, config, lang, factory),
            )
        )
    except KeyboardInterrupt:  # pragma: no cover - ユーザー中断
        LOGGER.warning(_msg(lang, "interrupt"))
        return 130

    if args.out:
        metrics_dir = args.out.expanduser().resolve()
        write_metrics(metrics_dir, results, args.log_prompts, lang)
    emit_results(results, args.format, args.log_prompts)
    has_error = any(res.error for res in results)
    if has_error:
        LOGGER.error(_sanitize_message(_msg(lang, "prompt_errors")))
    exit_code = exit_code_for_results(results)
    return exit_code if has_error else EXIT_OK


def determine_concurrency(parallel: bool, prompt_count: int) -> int:
    if not parallel:
        return 1
    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, prompt_count, 8))


def exit_code_for_results(results: Iterable[PromptResult]) -> int:
    priority = [
        ("rate", EXIT_RATE_LIMIT),
        ("env", EXIT_ENV_ERROR),
        ("network", EXIT_NETWORK_ERROR),
        ("provider", EXIT_PROVIDER_ERROR),
    ]
    for kind, code in priority:
        if any(res.error_kind == kind for res in results):
            return code
    return EXIT_OK


def _exit_code_for_error_kind(kind: str) -> int:
    if kind == "rate":
        return EXIT_RATE_LIMIT
    if kind == "network":
        return EXIT_NETWORK_ERROR
    if kind == "env":
        return EXIT_ENV_ERROR
    if kind == "input":
        return EXIT_INPUT_ERROR
    return EXIT_PROVIDER_ERROR


__all__ = [
    "ProviderFactoryLike",
    "classify_error",
    "create_provider",
    "determine_concurrency",
    "exit_code_for_results",
    "run_prompt_execution",
]
