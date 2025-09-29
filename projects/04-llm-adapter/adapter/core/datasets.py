"""データセット読み込みとプロンプト整形。"""
from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass
import json
from pathlib import Path
import re

_PROMPT_PATTERN = re.compile(r"{{\s*(?P<key>[a-zA-Z0-9_\.]+)\s*}}")


@dataclass
class GoldenTask:
    """ゴールデン小データの 1 エントリ。"""

    task_id: str
    name: str
    input: Mapping[str, object]
    prompt_template: str
    expected: Mapping[str, object]

    def render_prompt(self) -> str:
        """テンプレートからプロンプトを生成する。"""

        def replace(match: re.Match[str]) -> str:
            key = match.group("key")
            value = _lookup_nested(self.input, key)
            return str(value) if value is not None else ""

        return _PROMPT_PATTERN.sub(replace, self.prompt_template)


def _lookup_nested(payload: Mapping[str, object], dotted_key: str) -> object | None:
    parts = dotted_key.split(".")
    current: object = payload
    for part in parts:
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


def load_golden_tasks(path: Path) -> list[GoldenTask]:
    """JSONL 形式のゴールデンタスクを読み込む。"""

    tasks: list[GoldenTask] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            tasks.append(
                GoldenTask(
                    task_id=str(data["id"]),
                    name=str(data.get("name", data["id"])),
                    input=dict(data.get("input", {})),
                    prompt_template=str(data.get("prompt_template", "")),
                    expected=dict(data.get("expected", {})),
                )
            )
    return tasks


def iter_jsonl(path: Path) -> Iterator[MutableMapping[str, object]]:
    """JSONL を逐次的に読み込むユーティリティ。"""

    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, MutableMapping):
                yield payload
