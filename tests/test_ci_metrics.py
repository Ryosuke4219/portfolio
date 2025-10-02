from tools.ci_metrics import compute_run_history


def test_compute_run_history_excludes_other_statuses_from_pass_rate():
    runs = [
        {
            "run_id": "1",
            "status": "pass",
            "ts": "2024-01-01T00:00:00Z",
        },
        {
            "run_id": "1",
            "status": "skipped",
            "ts": "2024-01-01T00:01:00Z",
        },
    ]

    history = compute_run_history(runs)
    assert len(history) == 1
    assert history[0].pass_rate == 1.0
