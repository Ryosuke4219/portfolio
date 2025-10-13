from __future__ import annotations

from typing import cast

from adapter.core import providers as provider_module

from .args import parse_cli_arguments
from .config_loader import (
    ensure_credentials,
    load_env_from_option,
    load_provider_configuration,
)
from .prompt_io import collect_prompts
from .prompt_runner import PromptResult, RateLimiter
from .runner import create_provider, ProviderFactoryLike, run_prompt_execution
from .utils import (
    _coerce_exit_code,
    _configure_logging,
    _resolve_lang,
    _sanitize_message,
    EXIT_INPUT_ERROR,
    LOGGER,
)

ProviderFactory = provider_module.ProviderFactory


def run_prompts(
    argv: list[str] | None, provider_factory: ProviderFactoryLike | None = None
) -> int:
    args, parser, parse_error = parse_cli_arguments(argv)
    if parse_error is not None:
        return parse_error
    assert args is not None  # mypy safety

    requested_lang = args.lang if args.lang is not None else None
    lang = _resolve_lang(requested_lang)
    _configure_logging(args.json_logs)

    load_env_from_option(args.env, lang)

    try:
        prepared = load_provider_configuration(
            args.provider, args.model, args.provider_option
        )
    except Exception as exc:  # pragma: no cover - 設定ファイル不備
        LOGGER.error(_sanitize_message(str(exc)))
        return EXIT_INPUT_ERROR

    credential_error = ensure_credentials(prepared.config, prepared.cli_has_credentials, lang)
    if credential_error is not None:
        return credential_error

    factory = cast(ProviderFactoryLike, provider_factory or ProviderFactory)
    provider, provider_error = create_provider(factory, prepared.config, lang)
    if provider is None:
        return provider_error if provider_error is not None else EXIT_INPUT_ERROR

    try:
        prompts = collect_prompts(args, parser, lang)
    except SystemExit as exc:
        raw_code = exc.code
        normalized = raw_code if isinstance(raw_code, int) or raw_code is None else None
        return _coerce_exit_code(normalized)

    LOGGER.info("プロンプト数: %d", len(prompts))
    return run_prompt_execution(args, prompts, provider, prepared.config, lang, factory)


__all__ = [
    "PromptResult",
    "RateLimiter",
    "run_prompts",
]
