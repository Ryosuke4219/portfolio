from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, Optional

LOGGER = logging.getLogger("adapter.cli")

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

_SENSITIVE_ENV_PATTERNS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "BEARER")


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


def _coerce_exit_code(value: Optional[int]) -> int:
    if value is None:
        return EXIT_INPUT_ERROR
    try:
        code = int(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return EXIT_INPUT_ERROR
    return code


__all__ = [
    "LOGGER",
    "EXIT_OK",
    "EXIT_INPUT_ERROR",
    "EXIT_ENV_ERROR",
    "EXIT_NETWORK_ERROR",
    "EXIT_PROVIDER_ERROR",
    "EXIT_RATE_LIMIT",
    "LANG_MESSAGES",
    "JsonLogFormatter",
    "_configure_logging",
    "_coerce_exit_code",
    "_msg",
    "_resolve_lang",
    "_sanitize_message",
]
