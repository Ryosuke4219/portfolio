from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from adapter.core import providers as provider_module
from adapter.core.config import ProviderConfig, load_provider_config
from adapter.core.metrics import RunMetric, estimate_cost

from .utils import (
    EXIT_ENV_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_PROVIDER_ERROR,
    EXIT_RATE_LIMIT,
    LOGGER,
    _coerce_exit_code,
    _configure_logging,
    _msg,
    _resolve_lang,
    _sanitize_message,
)

ProviderFactory = provider_module.ProviderFactory
ProviderResponse = provider_module.ProviderResponse


class RateLimiter:
    """簡易 RPM 制御。"""

    def __init__(self, rpm: int) -> None:
        self._rpm = max(0, int(rpm or 0))
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._rpm <= 0:
            return
        window = 60.0
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= window:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._rpm:
                    self._timestamps.append(now)
                    return
                wait = window - (now - self._timestamps[0])
            await asyncio.sleep(max(wait, 0.0))


@dataclass
class PromptResult:
    index: int
    prompt: str
    response: Optional[ProviderResponse]
    metric: RunMetric
    output_text: str
    error: Optional[str]
    error_kind: Optional[str] = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("llm-adapter")
    parser.add_argument("--provider", required=True, help="プロバイダ設定 YAML のパス")
    parser.add_argument("--prompt", help="単発プロンプト文字列")
    parser.add_argument("--prompt-file", help="テキストファイルからプロンプトを読み込む")
    parser.add_argument("--prompts", help="JSONL 形式のプロンプト一覧")
    parser.add_argument(
        "--format",
        choices=("text", "json", "jsonl"),
        default="text",
        help="出力フォーマット (text/json/jsonl)",
    )
    parser.add_argument("--out", type=Path, help="メトリクスを書き出すディレクトリ")
    parser.add_argument("--json-logs", action="store_true", help="ログを JSON 形式で出力")
    parser.add_argument("--parallel", action="store_true", help="プロンプトを並列実行する")
    parser.add_argument("--rpm", type=int, default=0, help="1 分あたりの実行上限 (RPM)")
    parser.add_argument("--env", help="指定した .env ファイルを読み込む")
    parser.add_argument("--log-prompts", action="store_true", help="JSON 出力にプロンプト本文を含める")
    parser.add_argument("--lang", choices=("ja", "en"), help="エラーメッセージの言語")
    return parser


def _load_env_file(path: Path, lang: str) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "python-dotenv がインストールされていないため --env オプションは利用できません。"
            " `pip install python-dotenv` を実行してください。"
        ) from exc
    if not path.exists():
        raise SystemExit(_msg(lang, "env_missing", path=path))
    load_dotenv(path, override=False)
    LOGGER.info(_sanitize_message(_msg(lang, "env_loaded", path=path)))


def _read_jsonl_prompts(path: Path, lang: str) -> List[str]:
    prompts: List[str] = []
    try:
        with path.open("r", encoding="utf-8") as fp:
            for line_no, raw_line in enumerate(fp, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, str):
                    prompts.append(obj)
                elif isinstance(obj, dict):
                    for key in ("prompt", "text", "input"):
                        value = obj.get(key)
                        if isinstance(value, str):
                            prompts.append(value)
                            break
                    else:
                        raise ValueError(_msg(lang, "jsonl_invalid_object", path=path, line=line_no))
                else:
                    raise ValueError(_msg(lang, "jsonl_unsupported", path=path, line=line_no))
    except FileNotFoundError as exc:
        raise SystemExit(_msg(lang, "jsonl_missing", path=path)) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(_msg(lang, "jsonl_decode_error", path=path, line=exc.lineno)) from exc
    return prompts


def _collect_prompts(args: argparse.Namespace, parser: argparse.ArgumentParser, lang: str) -> List[str]:
    prompts: List[str] = []
    if args.prompt is not None:
        prompts.append(args.prompt)
    if args.prompt_file:
        path = Path(args.prompt_file).expanduser().resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            parser.error(_msg(lang, "jsonl_missing", path=path))
            raise SystemExit from exc
        prompts.append(text.rstrip("\n"))
    if args.prompts:
        prompts.extend(_read_jsonl_prompts(Path(args.prompts).expanduser().resolve(), lang))
    if not prompts:
        parser.error(_msg(lang, "prompt_sources_missing"))
    return prompts


def _classify_error(
    exc: Exception,
    config: ProviderConfig,
    lang: str,
    factory: Optional[object] = None,
) -> Tuple[str, str]:
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
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or "429" in lower or "rate" in lower or "quota" in lower:
        return _msg(lang, "rate_limited"), "rate"
    if isinstance(exc, (OSError, socket.gaierror, TimeoutError)) or "ssl" in lower or "dns" in lower:
        return _msg(lang, "network_error"), "network"
    if exc.__class__.__name__.lower().endswith("ratelimiterror"):
        return _msg(lang, "rate_limited"), "rate"
    if exc.__class__.__name__.lower().endswith("authenticationerror") and has_auth_env:
        return _msg(lang, "api_key_missing", env=auth_env), "env"
    sanitized = _sanitize_message(raw_message)
    return _msg(lang, "provider_error", error=sanitized), "provider"


async def _process_prompt(
    index: int,
    prompt: str,
    provider: object,
    config: ProviderConfig,
    limiter: RateLimiter,
    semaphore: asyncio.Semaphore,
    lang: str,
) -> PromptResult:
    async with semaphore:
        await limiter.wait()
        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        try:
            response: ProviderResponse = await loop.run_in_executor(None, provider.generate, prompt)
        except Exception as exc:  # pragma: no cover - 実 API 呼び出し向けの防御
            latency_ms = int((time.perf_counter() - start) * 1000)
            friendly, error_kind = _classify_error(exc, config, lang)
            LOGGER.error(_sanitize_message(friendly))
            LOGGER.debug("provider error", exc_info=True)
            stub = ProviderResponse(
                output_text="",
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
            )
            metric = RunMetric.from_resp(config, stub, prompt, cost_usd=0.0, error=friendly)
            return PromptResult(
                index=index,
                prompt=prompt,
                response=None,
                metric=metric,
                output_text="",
                error=friendly,
                error_kind=error_kind,
            )
        cost = estimate_cost(
            config,
            getattr(response, "input_tokens", 0),
            getattr(response, "output_tokens", 0),
        )
        metric = RunMetric.from_resp(config, response, prompt, cost_usd=cost)
        return PromptResult(
            index=index,
            prompt=prompt,
            response=response,
            metric=metric,
            output_text=getattr(response, "output_text", ""),
            error=None,
        )


async def _execute_prompts(
    prompts: List[str],
    provider: object,
    config: ProviderConfig,
    concurrency: int,
    rpm: int,
    lang: str,
) -> List[PromptResult]:
    limiter = RateLimiter(rpm)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    tasks = [
        asyncio.create_task(_process_prompt(idx, prompt, provider, config, limiter, semaphore, lang))
        for idx, prompt in enumerate(prompts)
    ]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda item: item.index)


def _emit_results(results: Iterable[PromptResult], output_format: str, include_prompts: bool) -> None:
    metrics = []
    for res in results:
        payload = res.metric.model_dump()
        if include_prompts:
            payload["prompt"] = res.prompt
        metrics.append(payload)
    if output_format == "text":
        for res in results:
            if res.error:
                continue
            text = res.output_text
            if text:
                print(text)
    elif output_format == "json":
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        for payload in metrics:
            print(json.dumps(payload, ensure_ascii=False))


def _write_metrics(out_dir: Path, results: Iterable[PromptResult], include_prompts: bool, lang: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "metrics.jsonl"
    with path.open("a", encoding="utf-8") as fp:
        for res in results:
            payload = res.metric.model_dump()
            if include_prompts:
                payload["prompt"] = res.prompt
            fp.write(json.dumps(payload, ensure_ascii=False))
            fp.write("\n")
    LOGGER.info(_sanitize_message(_msg(lang, "metrics_written", path=path)))


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


def run_prompts(argv: Optional[List[str]], provider_factory: Optional[object] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse は内部で exit(2) を呼ぶ
        return _coerce_exit_code(getattr(exc, "code", None))

    lang = _resolve_lang(getattr(args, "lang", None))
    _configure_logging(args.json_logs)
    if args.env:
        _load_env_file(Path(args.env).expanduser().resolve(), lang)

    try:
        config = load_provider_config(Path(args.provider).expanduser().resolve())
    except Exception as exc:  # pragma: no cover - 設定ファイル不備
        LOGGER.error(_sanitize_message(str(exc)))
        return EXIT_INPUT_ERROR

    auth_env = (config.auth_env or "").strip()
    if auth_env and auth_env.upper() != "NONE" and not os.getenv(auth_env):
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
        prompts = _collect_prompts(args, parser, lang)
    except SystemExit as exc:
        return _coerce_exit_code(getattr(exc, "code", None))

    LOGGER.info("プロンプト数: %d", len(prompts))
    concurrency = _determine_concurrency(args.parallel, len(prompts))
    try:
        results = asyncio.run(
            _execute_prompts(prompts, provider, config, concurrency, args.rpm, lang)
        )
    except KeyboardInterrupt:  # pragma: no cover - ユーザー中断
        LOGGER.warning(_msg(lang, "interrupt"))
        return 130

    if args.out:
        _write_metrics(Path(args.out).expanduser().resolve(), results, args.log_prompts, lang)
    _emit_results(results, args.format, args.log_prompts)
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
