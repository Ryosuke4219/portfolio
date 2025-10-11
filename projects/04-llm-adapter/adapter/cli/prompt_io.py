from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import _msg, _sanitize_message, LOGGER

if TYPE_CHECKING:
    from .prompt_runner import PromptResult


def read_jsonl_prompts(path: Path, lang: str) -> list[str]:
    prompts: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as fp:
            for line_no, raw_line in enumerate(fp, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                obj = json.loads(line.lstrip("\ufeff"))
                if isinstance(obj, str):
                    prompts.append(obj)
                    continue
                if isinstance(obj, dict):
                    for key in ("prompt", "text", "input"):
                        value = obj.get(key)
                        if isinstance(value, str):
                            prompts.append(value)
                            break
                    else:
                        raise ValueError(
                            "jsonl_invalid_object",
                            _msg(lang, "jsonl_invalid_object", path=path, line=line_no),
                        )
                    continue
                raise ValueError(
                    "jsonl_unsupported",
                    _msg(lang, "jsonl_unsupported", path=path, line=line_no),
                )
    except FileNotFoundError as exc:
        raise SystemExit(_msg(lang, "jsonl_missing", path=path)) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            _msg(lang, "jsonl_decode_error", path=path, line=exc.lineno)
        ) from exc
    return prompts


def collect_prompts(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    lang: str,
) -> list[str]:
    prompts: list[str] = []
    if args.prompt is not None:
        prompts.append(args.prompt)
    if args.prompt_file:
        path = Path(args.prompt_file).expanduser().resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            parser.error(_msg(lang, "jsonl_missing", path=path))
            raise SystemExit from exc
        prompts.append(text.rstrip("\r\n"))
    if args.prompts:
        prompts_path = Path(args.prompts).expanduser().resolve()
        try:
            prompts.extend(read_jsonl_prompts(prompts_path, lang))
        except ValueError as exc:
            key: str | None = None
            message: str
            if exc.args:
                first = exc.args[0]
                last = exc.args[-1]
                key = first if isinstance(first, str) else None
                message = last if isinstance(last, str) else str(exc)
            else:
                message = str(exc)
            if key and key.startswith("jsonl_"):
                parser.error(f"{key}: {message}")
            else:
                parser.error(message)
            raise SystemExit from exc
    if not prompts:
        parser.error(_msg(lang, "prompt_sources_missing"))
    return prompts


def emit_results(
    results: Iterable[PromptResult],
    output_format: str,
    include_prompts: bool,
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
        return
    if output_format == "json":
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return
    for payload in metrics:
        print(json.dumps(payload, ensure_ascii=False))


def write_metrics(
    out_dir: Path,
    results: Iterable[PromptResult],
    include_prompts: bool,
    lang: str,
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


__all__ = ["collect_prompts", "emit_results", "read_jsonl_prompts", "write_metrics"]
