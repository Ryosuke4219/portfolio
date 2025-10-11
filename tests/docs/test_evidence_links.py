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

DISALLOWED_REFERENCES = (
    "adapter/core/metrics.py",
)

CLI_EXPECTATIONS = (
    "prompt_runner",
    "--out",
)


@pytest.mark.parametrize("evidence_path", EVIDENCE_PATHS)
def test_llm_adapter_evidence_links(evidence_path: Path) -> None:
    content = evidence_path.read_text(encoding="utf-8")
    missing = [ref for ref in EXPECTED_REFERENCES if ref not in content]
    assert not missing, (
        "Missing references in evidence file"
        f" {evidence_path.relative_to(PROJECT_ROOT)}: {missing}"
    )
    unexpected = [ref for ref in DISALLOWED_REFERENCES if ref in content]
    assert not unexpected, (
        "Unexpected references in evidence file"
        f" {evidence_path.relative_to(PROJECT_ROOT)}: {unexpected}"
    )
    missing_cli = [ref for ref in CLI_EXPECTATIONS if ref not in content]
    assert not missing_cli, (
        "Missing CLI usage details in evidence file"
        f" {evidence_path.relative_to(PROJECT_ROOT)}: {missing_cli}"
    )
