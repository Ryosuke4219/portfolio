import re
from pathlib import Path

import pytest


DOC_PATH = Path("docs/tasks/runner_refactor_tasks.md")


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_runner_refactor_tasks_uses_adapter_core_sources(doc_text: str) -> None:
    shadow_refs = re.findall(r"projects/04-llm-adapter-shadow", doc_text)
    assert not shadow_refs, "ドキュメントに shadow ツリーの参照が含まれています"

    file_refs = re.findall(r"F:(projects/04-llm-adapter[^】]+)", doc_text)
    assert file_refs, "参照ファイルが検出できません"

    invalid_refs = [
        ref
        for ref in file_refs
        if "/adapter/core/" not in ref and "/tests/" not in ref
    ]
    assert not invalid_refs, f"adapter/core 以外への参照があります: {invalid_refs!r}"
