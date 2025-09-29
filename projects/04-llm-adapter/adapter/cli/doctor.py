from __future__ import annotations

import argparse
import http.client
import os
import platform
import socket
import sys
from contextlib import closing
from pathlib import Path
from types import ModuleType

from .utils import (
    EXIT_ENV_ERROR,
    EXIT_OK,
    _coerce_exit_code,
    _msg,
    _resolve_lang,
)


def _doctor_check_python(lang: str) -> tuple[str, str, str]:
    required = (3, 10)
    version = sys.version_info[:3]
    if version >= required:
        detail = f"Python {platform.python_version()}"
        return "doctor_name_python", "ok", detail
    return "doctor_name_python", "fail", _msg(lang, "doctor_fix_python", required="3.10")


def _doctor_check_os(lang: str) -> tuple[str, str, str]:
    venv_active = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    detail = _msg(
        lang,
        "doctor_info_os",
        os=platform.platform(),
        venv="venv" if venv_active else "system",
    )
    return "doctor_name_os", "ok", detail


def _doctor_check_api(lang: str) -> tuple[str, str, str]:
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


def _doctor_check_dns(lang: str, socket_module: ModuleType, http_module: ModuleType) -> tuple[str, str, str]:
    host = "api.openai.com"
    try:
        socket_module.gethostbyname(host)
        with closing(http_module.HTTPSConnection(host, timeout=3)) as conn:
            conn.request("HEAD", "/")
            conn.getresponse()
        return "doctor_name_dns", "ok", host
    except Exception:
        return "doctor_name_dns", "fail", _msg(lang, "doctor_fix_dns")


def _doctor_check_pythonioencoding(lang: str) -> tuple[str, str, str]:
    value = os.getenv("PYTHONIOENCODING", "")
    if value.lower() == "utf-8":
        return "doctor_name_encoding", "ok", "utf-8"
    return "doctor_name_encoding", "fail", _msg(lang, "doctor_fix_encoding")


def _doctor_check_windows_encoding(lang: str) -> tuple[str, str, str]:
    if not sys.platform.startswith("win"):
        return "doctor_name_windows", "ok", "N/A"
    stdout_enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    stdin_enc = (getattr(sys.stdin, "encoding", "") or "").lower()
    if "utf" in stdout_enc and "utf" in stdin_enc:
        return "doctor_name_windows", "ok", f"stdout={stdout_enc}, stdin={stdin_enc}"
    return "doctor_name_windows", "fail", _msg(lang, "doctor_fix_windows")


def _doctor_check_env_dependency(lang: str) -> tuple[str, str, str]:
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


def _doctor_check_rpm(lang: str) -> tuple[str, str, str]:
    value = os.getenv("LLM_ADAPTER_RPM")
    if value and value.isdigit() and int(value) > 0:
        return "doctor_name_rpm", "ok", _msg(lang, "doctor_info_rpm", rpm=value)
    return "doctor_name_rpm", "warn", _msg(lang, "doctor_fix_rpm")


def _doctor_checks(
    lang: str, socket_module: ModuleType, http_module: ModuleType
) -> list[tuple[str, str, str]]:
    return [
        _doctor_check_python(lang),
        _doctor_check_os(lang),
        _doctor_check_api(lang),
        _doctor_check_dns(lang, socket_module, http_module),
        _doctor_check_pythonioencoding(lang),
        _doctor_check_windows_encoding(lang),
        _doctor_check_env_dependency(lang),
        _doctor_check_rpm(lang),
    ]


def run_doctor(
    argv: list[str] | None,
    socket_module: ModuleType | None = None,
    http_module: ModuleType | None = None,
) -> int:
    parser = argparse.ArgumentParser("llm-adapter doctor")
    parser.add_argument("--lang", choices=("ja", "en"), help="診断結果の言語")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _coerce_exit_code(getattr(exc, "code", None))

    lang = _resolve_lang(getattr(args, "lang", None))
    socket_mod = socket_module or socket
    http_mod = http_module or http.client
    print(_msg(lang, "doctor_header"))
    has_failure = False
    for name_key, status, detail in _doctor_checks(lang, socket_mod, http_mod):
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


__all__ = ["run_doctor"]
