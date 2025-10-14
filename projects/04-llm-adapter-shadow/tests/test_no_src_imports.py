from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
FORBIDDEN = "src.llm_adapter"


def _collect_references(root: Path) -> OrderedDict[str, int]:
    result: OrderedDict[str, int] = OrderedDict()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        occurrences = text.count(FORBIDDEN)
        if occurrences:
            relative_path = str(path.relative_to(PROJECT_ROOT))
            result[relative_path] = occurrences
    return result


@pytest.fixture(scope="session")
def src_llm_adapter_test_references() -> OrderedDict[str, int]:
    return _collect_references(TESTS_ROOT)


@pytest.mark.parametrize("path", sorted(SOURCE_ROOT.rglob("*.py")))
def test_no_src_llm_adapter_in_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert FORBIDDEN not in text, (
        f"{path.relative_to(PROJECT_ROOT)} contains '{FORBIDDEN}'"
    )


def test_src_llm_adapter_references_snapshot(
    src_llm_adapter_test_references: OrderedDict[str, int],
) -> None:
    assert src_llm_adapter_test_references == OrderedDict()
