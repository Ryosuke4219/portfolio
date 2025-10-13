from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path

from .utils import _coerce_exit_code

ProviderOption = tuple[str, object]


def _coerce_provider_option_value(raw_value: str) -> object:
    text = raw_value.strip()
    if not text:
        return raw_value
    try:
        return json.loads(text)
    except ValueError:
        return raw_value


def _parse_provider_option(value: str) -> ProviderOption:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--provider-option は KEY=VALUE 形式で指定してください")
    key, raw_value = value.split("=", 1)
    key = key.strip()
    if not key or raw_value == "":
        raise argparse.ArgumentTypeError("--provider-option は KEY=VALUE 形式で指定してください")
    coerced = _coerce_provider_option_value(raw_value)
    return key, coerced


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("llm-adapter")
    parser.add_argument(
        "--provider",
        required=True,
        help="プロバイダ設定 YAML のパス",
    )
    parser.add_argument("--model", help="プロバイダ設定の model を上書き")
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
    parser.add_argument(
        "--provider-option",
        action="append",
        type=_parse_provider_option,
        metavar="KEY=VALUE",
        help="プロバイダ設定の options.* を上書き (繰り返し指定可)",
    )
    return parser


def parse_cli_arguments(
    argv: Sequence[str] | None,
) -> tuple[argparse.Namespace | None, argparse.ArgumentParser, int | None]:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse は内部で exit(2) を呼ぶ
        raw_code = exc.code
        normalized = raw_code if isinstance(raw_code, int) or raw_code is None else None
        return None, parser, _coerce_exit_code(normalized)
    return args, parser, None


__all__ = [
    "ProviderOption",
    "build_parser",
    "parse_cli_arguments",
]
