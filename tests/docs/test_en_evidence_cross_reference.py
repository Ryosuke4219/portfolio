from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EVIDENCE_README = PROJECT_ROOT / "docs" / "en" / "evidence" / "README.md"

EXPECTED_RELATIVE_URLS = (
    "{{ '/test-plan.html' | relative_url }}",
    "{{ '/defect-report-sample.html' | relative_url }}",
    "{{ '/weekly-summary.html' | relative_url }}",
)

UNEXPECTED_MARKDOWN_TARGETS = (
    "../test-plan.md",
    "../defect-report-sample.md",
    "../weekly-summary.md",
)


def test_en_evidence_cross_reference_links() -> None:
    content = EVIDENCE_README.read_text(encoding="utf-8")

    missing_urls = [target for target in EXPECTED_RELATIVE_URLS if target not in content]
    assert not missing_urls, (
        "Missing published relative_url targets in en evidence README: "
        f"{missing_urls}"
    )

    unexpected_targets = [target for target in UNEXPECTED_MARKDOWN_TARGETS if target in content]
    assert not unexpected_targets, (
        "Found stale Markdown cross references in en evidence README: "
        f"{unexpected_targets}"
    )
