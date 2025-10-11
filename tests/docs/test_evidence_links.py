from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EVIDENCE_PATHS = (
    PROJECT_ROOT / "docs" / "evidence" / "llm-adapter.md",
    PROJECT_ROOT / "docs" / "en" / "evidence" / "llm-adapter.md",
)

EXPECTED_REFERENCES = (
    "projects/04-llm-adapter/README.md",
    "projects/04-llm-adapter/adapter/run_compare.py",
    "projects/04-llm-adapter/adapter/core/runner_execution.py",
)

LEGACY_METRICS_REFERENCE = "projects/04-llm-adapter/adapter/core/metrics.py"
UPDATED_METRICS_REFERENCE = "projects/04-llm-adapter/adapter/core/metrics/models.py"


@pytest.mark.parametrize("evidence_path", EVIDENCE_PATHS)
def test_llm_adapter_evidence_links(evidence_path: Path) -> None:
    content = evidence_path.read_text(encoding="utf-8")
    missing = [ref for ref in EXPECTED_REFERENCES if ref not in content]
    assert not missing, (
        "Missing references in evidence file"
        f" {evidence_path.relative_to(PROJECT_ROOT)}: {missing}"
    )


def test_llm_adapter_evidence_en_metrics_reference() -> None:
    evidence_path = PROJECT_ROOT / "docs" / "en" / "evidence" / "llm-adapter.md"
    content = evidence_path.read_text(encoding="utf-8")
    assert LEGACY_METRICS_REFERENCE not in content
    assert UPDATED_METRICS_REFERENCE in content
