from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import logging
import os
import platform
import re
import socket
import sys
import time
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from adapter.core.config import ProviderConfig, load_provider_config
from adapter.core.metrics import RunMetric, estimate_cost
from adapter.core.providers import ProviderFactory, ProviderResponse

LOGGER = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_ENV_ERROR = 3
EXIT_NETWORK_ERROR = 4
EXIT_PROVIDER_ERROR = 5
EXIT_RATE_LIMIT = 6


LANG_MESSAGES: Dict[str, Dict[str, str]] = {
    "ja": {
        "env_loaded": ".env を読み込みました: {path}",
        "prompt_sources_missing": "--prompt / --prompt-file / --prompts のいずれかを指定してください",
        "unsupported_provider": "プロバイダ {provider} は未対応です。利用可能: {supported}。",
        "api_key_missing": "API キーが未設定です。環境変数 {env} を設定してから再実行してください。",
        "rate_limited": "OpenAI/Gemini のレートまたは使用量制限に到達しました。プラン・請求状況・プロジェクトキーのクォータを確認してください。",
        "network_error": "ネットワークに接続できません。プロキシ・ファイアウォール・VPN の設定を確認してください。",
        "provider_error": "プロバイダで予期しないエラーが発生しました: {error}",
        "jsonl_missing": "JSONL が見つかりません: {path}",
        "jsonl_decode_error": "JSONL の読み込みに失敗しました: {path}:{line}",
        "jsonl_invalid_object": "{path}:{line} は 'prompt' キーを含む JSON オブジェクトではありません",
        "jsonl_unsupported": "{path}:{line} がサポート外の JSON 形式です",
        "metrics_written": "メトリクスを追記しました: {path}",
        "interrupt": "ユーザー操作により中断しました",
        "env_missing": ".env ファイルが見つかりません: {path}",
        "prompt_errors": "一部のプロンプトでエラーが発生しました",
        "doctor_header": "環境診断を開始します",
        "doctor_ok": "✅ {name}: {detail}",
        "doctor_fail": "❌ {name}: {detail}",
        "doctor_warn": "⚠️ {name}: {detail}",
        "doctor_summary_ok": "すべてのチェックを通過しました",
        "doctor_summary_fail": "一部のチェックで問題が見つかりました",
        "doctor_name_python": "Python バージョン",
        "doctor_name_os": "OS / 仮想環境",
        "doctor_name_api": "API キー",
        "doctor_name_dns": "DNS / HTTPS",
        "doctor_name_encoding": "PYTHONIOENCODING",
        "doctor_name_windows": "Windows エンコーディング",
        "doctor_name_env_file": ".env 依存関係",
        "doctor_name_rpm": "RPM 上限設定",
        "doctor_info_os": "OS={os}, venv={venv}",
        "doctor_fix_python": "Python {required} 以上をインストールしてください",
        "doctor_fix_api": "OPENAI_API_KEY などの API キーを環境変数で設定してください",
        "doctor_fix_dns": "api.openai.com への DNS/HTTPS を確認してください（プロキシ/ファイアウォール）",
        "doctor_fix_encoding": "PowerShell などで PYTHONIOENCODING=utf-8 を設定してください",
        "doctor_fix_windows": "[Console]::OutputEncoding などを UTF-8 に設定してください",
        "doctor_fix_env_file": "python-dotenv をインストールするか .env を作成してください",
        "doctor_fix_rpm": "LLM_ADAPTER_RPM で安全な上限を設定することを検討してください",
        "doctor_info_rpm": "現在の上限: {rpm}",
    },
    "en": {
        "env_loaded": "Loaded .env file: {path}",
        "prompt_sources_missing": "Please provide --prompt, --prompt-file, or --prompts",
        "unsupported_provider": "Provider {provider} is not supported. Available: {supported}.",
        "api_key_missing": "API key is missing. Set environment variable {env} and retry.",
        "rate_limited": "Rate or quota limit reached. Check your plan, billing status, and project quota.",
        "network_error": "Network connectivity failed. Verify proxy, firewall, or VPN settings.",
        "provider_error": "Unexpected provider error occurred: {error}",
        "jsonl_missing": "JSONL file not found: {path}",
        "jsonl_decode_error": "Failed to read JSONL: {path}:{line}",
        "jsonl_invalid_object": "{path}:{line} must be a JSON object containing a 'prompt' key",
        "jsonl_unsupported": "Unsupported JSON entry at {path}:{line}",
        "metrics_written": "Appended metrics: {path}",
        "interrupt": "Interrupted by user",
        "env_missing": ".env file not found: {path}",
        "prompt_errors": "Some prompts reported errors",
        "doctor_header": "Starting environment diagnostics",
        "doctor_ok": "✅ {name}: {detail}",
        "doctor_fail": "❌ {name}: {detail}",
        "doctor_warn": "⚠️ {name}: {detail}",
        "doctor_summary_ok": "All checks passed",
        "doctor_summary_fail": "Some checks failed",
        "doctor_name_python": "Python version",
        "doctor_name_os": "OS / virtualenv",
        "doctor_name_api": "API keys",
        "doctor_name_dns": "DNS / HTTPS",
        "doctor_name_encoding": "PYTHONIOENCODING",
        "doctor_name_windows": "Windows encoding",
        "doctor_name_env_file": ".env dependency",
        "doctor_name_rpm": "RPM limit",
        "doctor_info_os": "OS={os}, venv={venv}",
        "doctor_fix_python": "Install Python {required}+.",
        "doctor_fix_api": "Set API keys such as OPENAI_API_KEY in your environment.",
        "doctor_fix_dns": "Ensure DNS/HTTPS access to api.openai.com (proxy/firewall).",
        "doctor_fix_encoding": "Set PYTHONIOENCODING=utf-8 before running the CLI.",
        "doctor_fix_windows": "Configure [Console]::OutputEncoding to UTF-8.",
        "doctor_fix_env_file": "Install python-dotenv or create a .env file.",
        "doctor_fix_rpm": "Consider configuring a safe limit via LLM_ADAPTER_RPM.",
        "doctor_info_rpm": "Current limit: {rpm}",
    },
}


def _resolve_lang(requested: Optional[str]) -> str:
    env_lang = os.getenv("LLM_ADAPTER_LANG")
    for candidate in (requested, env_lang):
        if candidate:
            lowered = candidate.lower()
            if lowered in LANG_MESSAGES:
                return lowered
    return "ja"


def _msg(lang: str, key: str, **params: object) -> str:
    catalog = LANG_MESSAGES.get(lang) or LANG_MESSAGES["ja"]
    template = catalog.get(key) or LANG_MESSAGES["en"].get(key) or key
    return template.format(**params)


_SENSITIVE_ENV_PATTERNS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "BEARER")


def _sanitize_message(text: str) -> str:
    if not text:
        return text
    sanitized = text
    for name, value in os.environ.items():
        if not value:
            continue
        upper_name = name.upper()
        if any(pattern in upper_name for pattern in _SENSITIVE_ENV_PATTERNS):
            sanitized = sanitized.replace(value, "***")
    sanitized = re.sub(r"(Authorization\s*:\s*)([^\s]+)", r"\1***", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"([?&][^=]+=)([^&#\s]+)", r"\1***", sanitized)
    return sanitized


class JsonLogFormatter(logging.Formatter):
    """JSON 形式でログを吐き出すフォーマッタ。"""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload = {
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


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


def _configure_logging(as_json: bool) -> None:
    handler = logging.StreamHandler()
    if as_json:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


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
                        raise ValueError(
                            _msg(lang, "jsonl_invalid_object", path=path, line=line_no)
                        )
                else:
                    raise ValueError(_msg(lang, "jsonl_unsupported", path=path, line=line_no))
    except FileNotFoundError as exc:
        raise SystemExit(_msg(lang, "jsonl_missing", path=path)) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(_msg(lang, "jsonl_decode_error", path=path, line=exc.lineno)) from exc
    return prompts


def _collect_prompts(
    args: argparse.Namespace, parser: argparse.ArgumentParser, lang: str
) -> List[str]:
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
        prompts.extend(
            _read_jsonl_prompts(Path(args.prompts).expanduser().resolve(), lang)
        )
    if not prompts:
        parser.error(_msg(lang, "prompt_sources_missing"))
    return prompts


def _classify_error(exc: Exception, config: ProviderConfig, lang: str) -> Tuple[str, str]:
    raw_message = str(exc)
    lower = raw_message.lower()
    auth_env = (config.auth_env or "").strip()
    has_auth_env = bool(auth_env and auth_env.upper() != "NONE")
    if "unsupported provider prefix" in lower:
        supported = ", ".join(ProviderFactory.available())
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
        cost = estimate_cost(config, getattr(response, "input_tokens", 0), getattr(response, "output_tokens", 0))
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
        asyncio.create_task(
            _process_prompt(idx, prompt, provider, config, limiter, semaphore, lang)
        )
        for idx, prompt in enumerate(prompts)
    ]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda item: item.index)


def _emit_results(
    results: Iterable[PromptResult], output_format: str, include_prompts: bool
) -> None:
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


def _write_metrics(
    out_dir: Path, results: Iterable[PromptResult], include_prompts: bool, lang: str
) -> None:
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


def _coerce_exit_code(value: Optional[int]) -> int:
    if value is None:
        return EXIT_INPUT_ERROR
    try:
        code = int(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return EXIT_INPUT_ERROR
    return code


def _doctor_check_python(lang: str) -> Tuple[str, str, str]:
    required = (3, 10)
    version = sys.version_info[:3]
    if version >= required:
        detail = f"Python {platform.python_version()}"
        return "doctor_name_python", "ok", detail
    return "doctor_name_python", "fail", _msg(lang, "doctor_fix_python", required="3.10")


def _doctor_check_os(lang: str) -> Tuple[str, str, str]:
    venv_active = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    detail = _msg(
        lang,
        "doctor_info_os",
        os=platform.platform(),
        venv="venv" if venv_active else "system",
    )
    return "doctor_name_os", "ok", detail


def _doctor_check_api(lang: str) -> Tuple[str, str, str]:
    candidates = [
        name
        for name in os.environ
        if any(pattern in name for pattern in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN"))
        and os.environ.get(name)
    ]
    if candidates:
        detail = ", ".join(sorted(candidates))
        return "doctor_name_api", "ok", detail
    return "doctor_name_api", "fail", _msg(lang, "doctor_fix_api")


def _doctor_check_dns(lang: str) -> Tuple[str, str, str]:
    host = "api.openai.com"
    try:
        socket.gethostbyname(host)
        with closing(http.client.HTTPSConnection(host, timeout=3)) as conn:
            conn.request("HEAD", "/")
            conn.getresponse()
        return "doctor_name_dns", "ok", host
    except Exception:
        return "doctor_name_dns", "fail", _msg(lang, "doctor_fix_dns")


def _doctor_check_pythonioencoding(lang: str) -> Tuple[str, str, str]:
    value = os.getenv("PYTHONIOENCODING", "")
    if value.lower() == "utf-8":
        return "doctor_name_encoding", "ok", "utf-8"
    return "doctor_name_encoding", "fail", _msg(lang, "doctor_fix_encoding")


def _doctor_check_windows_encoding(lang: str) -> Tuple[str, str, str]:
    if not sys.platform.startswith("win"):
        return "doctor_name_windows", "ok", "N/A"
    stdout_enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    stdin_enc = (getattr(sys.stdin, "encoding", "") or "").lower()
    if "utf" in stdout_enc and "utf" in stdin_enc:
        return "doctor_name_windows", "ok", f"stdout={stdout_enc}, stdin={stdin_enc}"
    return "doctor_name_windows", "fail", _msg(lang, "doctor_fix_windows")


def _doctor_check_env_dependency(lang: str) -> Tuple[str, str, str]:
    env_path = Path.cwd() / ".env"
    try:
        import dotenv  # type: ignore  # pragma: no cover - optional
        has_dotenv = True
    except Exception:  # pragma: no cover - optional依存
        has_dotenv = False
    if env_path.exists() and not has_dotenv:
        return "doctor_name_env_file", "fail", _msg(lang, "doctor_fix_env_file")
    if env_path.exists():
        return "doctor_name_env_file", "ok", str(env_path)
    if has_dotenv:
        return "doctor_name_env_file", "ok", "python-dotenv"
    return "doctor_name_env_file", "warn", _msg(lang, "doctor_fix_env_file")


def _doctor_check_rpm(lang: str) -> Tuple[str, str, str]:
    value = os.getenv("LLM_ADAPTER_RPM")
    if value and value.isdigit() and int(value) > 0:
        return "doctor_name_rpm", "ok", _msg(lang, "doctor_info_rpm", rpm=value)
    return "doctor_name_rpm", "warn", _msg(lang, "doctor_fix_rpm")


def _doctor_checks(lang: str) -> List[Tuple[str, str, str]]:
    return [
        _doctor_check_python(lang),
        _doctor_check_os(lang),
        _doctor_check_api(lang),
        _doctor_check_dns(lang),
        _doctor_check_pythonioencoding(lang),
        _doctor_check_windows_encoding(lang),
        _doctor_check_env_dependency(lang),
        _doctor_check_rpm(lang),
    ]


def _run_prompts(argv: Optional[List[str]]) -> int:
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

    try:
        provider = ProviderFactory.create(config)
    except Exception as exc:  # pragma: no cover - 生成エラー
        friendly, kind = _classify_error(exc, config, lang)
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
        _write_metrics(
            Path(args.out).expanduser().resolve(), results, args.log_prompts, lang
        )
    _emit_results(results, args.format, args.log_prompts)
    has_error = any(res.error for res in results)
    if has_error:
        LOGGER.error(_sanitize_message(_msg(lang, "prompt_errors")))
    exit_code = _exit_code_for_results(results)
    return exit_code if has_error else EXIT_OK


def _run_doctor(argv: Optional[List[str]]) -> int:
    parser = argparse.ArgumentParser("llm-adapter doctor")
    parser.add_argument("--lang", choices=("ja", "en"), help="診断結果の言語")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _coerce_exit_code(getattr(exc, "code", None))

    lang = _resolve_lang(getattr(args, "lang", None))
    print(_msg(lang, "doctor_header"))
    has_failure = False
    for name_key, status, detail in _doctor_checks(lang):
        name = _msg(lang, name_key)
        if status == "ok":
            line = _msg(lang, "doctor_ok", name=name, detail=detail)
        elif status == "warn":
            line = _msg(lang, "doctor_warn", name=name, detail=detail)
        else:
            has_failure = True
            line = _msg(lang, "doctor_fail", name=name, detail=detail)
        print(line)
    summary_key = "doctor_summary_fail" if has_failure else "doctor_summary_ok"
    print(_msg(lang, summary_key))
    return EXIT_ENV_ERROR if has_failure else EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv or sys.argv[1:])
    if args and args[0] == "doctor":
        return _run_doctor(args[1:])
    return _run_prompts(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
