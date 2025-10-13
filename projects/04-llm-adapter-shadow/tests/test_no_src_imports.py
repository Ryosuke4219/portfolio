from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
FORBIDDEN = "src.llm_adapter"


@pytest.mark.parametrize("path", sorted(SOURCE_ROOT.rglob("*.py")))
def test_no_src_llm_adapter_in_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert FORBIDDEN not in text, (
        f"{path.relative_to(PROJECT_ROOT)} contains '{FORBIDDEN}'"
    )
