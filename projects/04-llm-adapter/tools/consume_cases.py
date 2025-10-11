"""Utility script to aggregate Node pipeline outputs for the adapter demo."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping, MutableMapping
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        raise SystemExit(f"cases file not found: {path}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc


def _load_jsonl(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        raise SystemExit(f"attempts file not found: {path}")

    attempts: list[Mapping[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            trimmed = raw.strip()
            if not trimmed:
                continue
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
                raise SystemExit(f"invalid JSON on line {line_no} in {path}: {exc}") from exc
            if isinstance(parsed, Mapping):
                attempts.append(parsed)
    return attempts


def _extract_case_ids(cases: Iterable[Mapping[str, Any]]) -> list[str]:
    ids: list[str] = []
    for entry in cases:
        if isinstance(entry, Mapping):
            value = str(entry.get("id", "")).strip()
            if value:
                ids.append(value)
    return ids


def _attempt_case_id(attempt: Mapping[str, Any]) -> str | None:
    name = attempt.get("name")
    if not isinstance(name, str):
        return None
    prefix = name.split(maxsplit=1)[0]
    return prefix.strip() or None


_STATUS_ALIASES: dict[str, str] = {
    "errored": "error",
    "failed": "fail",
    "failure": "fail",
}


def _normalize_status(raw_status: str) -> str:
    normalized = raw_status.strip().lower()
    return _STATUS_ALIASES.get(normalized, normalized)


def _build_metrics(
    cases: Mapping[str, Any], attempts: list[Mapping[str, Any]]
) -> MutableMapping[str, Any]:
    suite = str(cases.get("suite", "")).strip() if isinstance(cases, Mapping) else ""
    case_entries = cases.get("cases") if isinstance(cases, Mapping) else None
    if not isinstance(case_entries, Iterable):
        case_entries = []

    case_ids = _extract_case_ids(case_entries) if case_entries else []
    statuses: Counter[str] = Counter()
    seen: dict[str, Mapping[str, Any]] = {}
    failed_ids: list[str] = []

    for attempt in attempts:
        raw_status = str(attempt.get("status", "unknown"))
        status = _normalize_status(raw_status)
        statuses[status] += 1
        case_id = _attempt_case_id(attempt)
        if case_id:
            seen.setdefault(case_id, attempt)
            if status not in {"pass", "skipped"}:
                failed_ids.append(case_id)

    missing_ids = sorted(set(case_ids) - set(seen))
    failed_unique = sorted(set(failed_ids))

    pass_count = statuses.get("pass", 0)
    total_attempts = sum(statuses.values())
    pass_rate = float(pass_count) / float(total_attempts) if total_attempts else 0.0

    metrics: MutableMapping[str, Any] = {
        "suite": suite or None,
        "case_count": len(case_ids),
        "attempt_count": total_attempts,
        "status_breakdown": dict(statuses),
        "covered_case_ids": sorted(seen),
        "missing_case_ids": missing_ids,
        "failed_case_ids": failed_unique,
        "pass_rate": round(pass_rate, 4),
        "all_green": total_attempts > 0 and not failed_unique,
    }
    return metrics


def _format_text(metrics: Mapping[str, Any]) -> str:
    lines = []
    suite = metrics.get("suite") or "<unknown suite>"
    lines.append(f"Suite: {suite}")
    lines.append(f"Cases: {metrics.get('case_count', 0)}")
    lines.append(
        (
            "Attempts: {attempts} (pass: {passed}, fail: {failed}, "
            "error: {error}, skipped: {skipped})"
        ).format(
            attempts=metrics.get("attempt_count", 0),
            passed=metrics.get("status_breakdown", {}).get("pass", 0),
            failed=metrics.get("status_breakdown", {}).get("fail", 0),
            error=metrics.get("status_breakdown", {}).get("error", 0),
            skipped=metrics.get("status_breakdown", {}).get("skipped", 0),
        )
    )
    if metrics.get("missing_case_ids"):
        lines.append(f"Missing IDs: {', '.join(metrics['missing_case_ids'])}")
    if metrics.get("failed_case_ids"):
        lines.append(f"Failed IDs: {', '.join(metrics['failed_case_ids'])}")
    lines.append(f"Pass rate: {metrics.get('pass_rate', 0.0):.2%}")
    lines.append(f"All green: {'yes' if metrics.get('all_green') else 'no'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Path to spec2cases JSON output")
    parser.add_argument("--attempts", required=True, help="Path to analyze-junit JSONL output")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )

    args = parser.parse_args(argv)

    cases_path = Path(args.cases).expanduser().resolve()
    attempts_path = Path(args.attempts).expanduser().resolve()

    cases_data = _load_json(cases_path)
    attempts = _load_jsonl(attempts_path)
    metrics = _build_metrics(cases_data, attempts)

    if args.format == "json":
        indent = 2 if args.pretty else None
        separators = (",", ": ") if args.pretty else (",", ":")
        text = json.dumps(
            metrics,
            ensure_ascii=False,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )
    else:
        text = _format_text(metrics)

    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
