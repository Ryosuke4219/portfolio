import datetime as dt

from tools.ci_metrics import RunMetrics, compute_run_history


def _run_record(status: str, *, run_id: str = "run-1", ts: dt.datetime | None = None) -> dict:
    timestamp = ts or dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    return {
        "run_id": run_id,
        "ts": timestamp.isoformat().replace("+00:00", "Z"),
        "status": status,
    }


def test_compute_run_history_excludes_other_statuses_from_pass_rate() -> None:
    runs = [
        _run_record("pass"),
        _run_record("skipped", ts=dt.datetime(2024, 1, 1, 0, 1, tzinfo=dt.UTC)),
    ]

    history = compute_run_history(runs)

    assert history == [
        RunMetrics(
            run_id="run-1",
            timestamp=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
            total=1,
            passes=1,
            fails=0,
            errors=0,
            pass_rate=1.0,
            flaky_count=0,
        )
    ]
