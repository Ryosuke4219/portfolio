from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
TEST_TARGETS: tuple[Path, ...] = (
    PROJECT_ROOT / "tests" / "test_runner_consensus.py",
)
FORBIDDEN = "src.llm_adapter"


def _collect_references(targets: Iterable[Path]) -> OrderedDict[str, int]:
    result: OrderedDict[str, int] = OrderedDict()
    for target in sorted(targets):
        if target.is_dir():
            paths = sorted(target.rglob("*.py"))
        elif target.suffix == ".py":
            paths = [target]
        else:
            paths = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            occurrences = text.count(FORBIDDEN)
            if occurrences:
                relative_path = str(path.relative_to(PROJECT_ROOT))
                result[relative_path] = occurrences
    return result


@pytest.mark.parametrize("path", sorted(SOURCE_ROOT.rglob("*.py")))
def test_no_src_llm_adapter_in_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert FORBIDDEN not in text, (
        f"{path.relative_to(PROJECT_ROOT)} contains '{FORBIDDEN}'"
    )


def test_src_llm_adapter_references_snapshot() -> None:
    assert _collect_references(TEST_TARGETS) == {}
