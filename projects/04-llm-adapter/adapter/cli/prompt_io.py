from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, TYPE_CHECKING

from .utils import LOGGER, _msg, _sanitize_message

if TYPE_CHECKING:
    from .prompt_runner import PromptResult


def read_jsonl_prompts(path: Path, lang: str) -> List[str]:
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
                    continue
                if isinstance(obj, dict):
                    for key in ("prompt", "text", "input"):
                        value = obj.get(key)
                        if isinstance(value, str):
                            prompts.append(value)
                            break
                    else:
                        raise ValueError(
                            _msg(lang, "jsonl_invalid_object", path=path, line=line_no)
                        )
                    continue
                raise ValueError(_msg(lang, "jsonl_unsupported", path=path, line=line_no))
    except FileNotFoundError as exc:
        raise SystemExit(_msg(lang, "jsonl_missing", path=path)) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(_msg(lang, "jsonl_decode_error", path=path, line=exc.lineno)) from exc
    return prompts


def collect_prompts(args: argparse.Namespace, parser: argparse.ArgumentParser, lang: str) -> List[str]:
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
        prompts.extend(read_jsonl_prompts(Path(args.prompts).expanduser().resolve(), lang))
    if not prompts:
        parser.error(_msg(lang, "prompt_sources_missing"))
    return prompts


def emit_results(results: Iterable["PromptResult"], output_format: str, include_prompts: bool) -> None:
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
    results: Iterable["PromptResult"],
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
