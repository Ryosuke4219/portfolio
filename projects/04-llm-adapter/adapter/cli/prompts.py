from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable, Mapping
import os
from pathlib import Path
import socket
import textwrap

from adapter.core import providers as provider_module
from adapter.core.config import load_provider_config, ProviderConfig

from .prompt_io import collect_prompts, emit_results, write_metrics
from .prompt_runner import execute_prompts, PromptResult, RateLimiter
from .utils import (
    _coerce_exit_code,
    _configure_logging,
    _msg,
    _resolve_lang,
    _sanitize_message,
    EXIT_ENV_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_PROVIDER_ERROR,
    EXIT_RATE_LIMIT,
    LOGGER,
)

ProviderFactory = provider_module.ProviderFactory


def _looks_like_env_var_name(value: str) -> bool:
    if not value:
        return False
    for ch in value:
        if not (
            "A" <= ch <= "Z"
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
    for key in inline_keys:
        credential = _normalize_credential(raw.get(key))
        if credential:
            return True
    return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("llm-adapter")
    parser.add_argument(
        "--provider",
        required=True,
        help="プロバイダ設定 YAML のパス",
    )
    parser.add_argument("--prompt", help="単発プロンプト文字列")
    parser.add_argument(
        "--prompt-file",
        help="テキストファイルからプロンプトを読み込む",
    )
    parser.add_argument("--prompts", help="JSONL 形式のプロンプト一覧")
    parser.add_argument(
        "--format",
        choices=("text", "json", "jsonl"),
        default="text",
        help="出力フォーマット (text/json/jsonl)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="メトリクスを書き出すディレクトリ",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="ログを JSON 形式で出力",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="プロンプトを並列実行する",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=0,
        help="1 分あたりの実行上限 (RPM)",
    )
    parser.add_argument("--env", help="指定した .env ファイルを読み込む")
    parser.add_argument(
        "--log-prompts",
        action="store_true",
        help="JSON 出力にプロンプト本文を含める",
    )
    parser.add_argument(
        "--lang",
        choices=("ja", "en"),
        help="エラーメッセージの言語",
    )
    return parser


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


def _classify_error(
    exc: Exception,
    config: ProviderConfig,
    lang: str,
    factory: object | None = None,
) -> tuple[str, str]:
    raw_message = str(exc)
    lower = raw_message.lower()
    auth_env = (config.auth_env or "").strip()
    has_auth_env = bool(auth_env and auth_env.upper() != "NONE")
    if "unsupported provider prefix" in lower:
        provider_factory = factory or ProviderFactory
        supported = ", ".join(provider_factory.available())
        return (
            _msg(lang, "unsupported_provider", provider=config.provider, supported=supported),
            "input",
        )
    if has_auth_env and ("environment variable" in lower or "api key" in lower):
        return _msg(lang, "api_key_missing", env=auth_env), "env"
    status_code = exc.status_code if hasattr(exc, "status_code") else None
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


def _determine_concurrency(parallel: bool, prompt_count: int) -> int:
    if not parallel:
        return 1
    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, prompt_count, 8))


def _exit_code_for_results(results: Iterable[PromptResult]) -> int:
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


def run_prompts(argv: list[str] | None, provider_factory: object | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse は内部で exit(2) を呼ぶ
        code = exc.code if exc.code is not None else None
        return _coerce_exit_code(code)

    requested_lang = args.lang if args.lang is not None else None
    lang = _resolve_lang(requested_lang)
    _configure_logging(args.json_logs)
    if args.env:
        _load_env_file(Path(args.env).expanduser().resolve(), lang)

    try:
        config = load_provider_config(Path(args.provider).expanduser().resolve())
    except Exception as exc:  # pragma: no cover - 設定ファイル不備
        LOGGER.error(_sanitize_message(str(exc)))
        return EXIT_INPUT_ERROR

    auth_env = (config.auth_env or "").strip()
    aliases: list[str] = []
    literal_credentials: list[str] = []
    raw_mapping = config.raw if isinstance(config.raw, Mapping) else None
    raw_env = raw_mapping.get("env") if isinstance(raw_mapping, Mapping) else None
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
        resolved_credentials = any(
            os.getenv(name) for name in env_candidates if name
        )
        if not resolved_credentials and literal_credentials:
            resolved_credentials = True
        if not resolved_credentials and isinstance(raw_mapping, Mapping):
            resolved_credentials = _has_embedded_credentials(raw_mapping)
    if requires_env and not resolved_credentials:
        message = _msg(lang, "api_key_missing", env=auth_env)
        LOGGER.error(_sanitize_message(message))
        return EXIT_ENV_ERROR

    factory = provider_factory or ProviderFactory

    try:
        provider = factory.create(config)
    except Exception as exc:  # pragma: no cover - 生成エラー
        friendly, kind = _classify_error(exc, config, lang, factory)
        LOGGER.error(_sanitize_message(friendly))
        if kind == "rate":
            return EXIT_RATE_LIMIT
        if kind == "network":
            return EXIT_NETWORK_ERROR
        if kind == "env":
            return EXIT_ENV_ERROR
        if kind == "input":
            return EXIT_INPUT_ERROR
        return EXIT_PROVIDER_ERROR

    try:
        prompts = collect_prompts(args, parser, lang)
    except SystemExit as exc:
        code = exc.code if exc.code is not None else None
        return _coerce_exit_code(code)

    LOGGER.info("プロンプト数: %d", len(prompts))
    concurrency = _determine_concurrency(args.parallel, len(prompts))
    try:
        results = asyncio.run(
            execute_prompts(
                prompts,
                provider,
                config,
                concurrency,
                args.rpm,
                lang,
                _classify_error,
            )
        )
    except KeyboardInterrupt:  # pragma: no cover - ユーザー中断
        LOGGER.warning(_msg(lang, "interrupt"))
        return 130

    if args.out:
        metrics_dir = Path(args.out).expanduser().resolve()
        write_metrics(metrics_dir, results, args.log_prompts, lang)
    emit_results(results, args.format, args.log_prompts)
    has_error = any(res.error for res in results)
    if has_error:
        LOGGER.error(_sanitize_message(_msg(lang, "prompt_errors")))
    exit_code = _exit_code_for_results(results)
    return exit_code if has_error else EXIT_OK


__all__ = [
    "PromptResult",
    "RateLimiter",
    "run_prompts",
]
