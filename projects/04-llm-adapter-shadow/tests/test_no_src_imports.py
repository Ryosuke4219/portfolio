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


EXPECTED_TEST_REFERENCES: OrderedDict[str, int] = OrderedDict(
    (
        ("tests/async_runner/conftest.py", 3),
        ("tests/async_runner/parallel/__init__.py", 1),
        ("tests/async_runner/parallel/test_parallel_all.py", 4),
        ("tests/async_runner/parallel/test_parallel_any_failures.py", 6),
        ("tests/async_runner/parallel/test_parallel_any_metrics.py", 3),
        ("tests/async_runner/test_basic.py", 11),
        ("tests/async_runner/test_consensus.py", 9),
        ("tests/async_runner/test_parallel.py", 4),
        ("tests/async_runner/test_shadow.py", 3),
        ("tests/conftest.py", 1),
        ("tests/consensus/conftest.py", 2),
        ("tests/consensus/test_consensus_candidates_regression.py", 1),
        ("tests/consensus/test_exception_paths.py", 4),
        ("tests/consensus/test_schema_and_judge.py", 3),
        ("tests/consensus/test_tie_breakers.py", 3),
        ("tests/consensus/test_weighted_strategies.py", 3),
        ("tests/helpers/fakes.py", 2),
        ("tests/parallel/test_parallel_all.py", 7),
        ("tests/parallel/test_parallel_any.py", 8),
        ("tests/parallel/test_parallel_consensus.py", 9),
        ("tests/parallel/test_parallel_logging.py", 3),
        ("tests/parallel_helpers.py", 3),
        ("tests/providers/gemini/invoke/conftest.py", 1),
        ("tests/providers/gemini/invoke/test_invoke_errors.py", 5),
        ("tests/providers/gemini/invoke/test_invoke_success.py", 3),
        ("tests/providers/ollama/test_error_handling.py", 3),
        ("tests/providers/ollama/test_host_resolution.py", 1),
        ("tests/providers/ollama/test_invoke_options.py", 2),
        ("tests/providers/test_ollama_client.py", 3),
        ("tests/providers/test_ollama_offline.py", 3),
        ("tests/providers/test_openai_provider.py", 4),
        ("tests/providers/test_openrouter_provider.py", 4),
        ("tests/providers/test_parse_and_factory.py", 2),
        ("tests/providers/test_provider_spi_contract.py", 1),
        ("tests/sequential/conftest.py", 4),
        ("tests/sequential/test_failures.py", 6),
        ("tests/sequential/test_fallback_events.py", 5),
        ("tests/sequential/test_metrics.py", 6),
        ("tests/shadow/_runner_test_helpers.py", 5),
        ("tests/shadow/test_provider_request_normalization.py", 2),
        ("tests/shadow/test_runner_async.py", 6),
        ("tests/shadow/test_runner_sync.py", 5),
        ("tests/sync_invocation/conftest.py", 3),
        ("tests/sync_invocation/test_cancelled_results.py", 2),
        ("tests/sync_invocation/test_invoker.py", 4),
        ("tests/sync_metrics/helpers.py", 9),
        ("tests/sync_metrics/test_errors.py", 5),
        ("tests/sync_metrics/test_happy.py", 2),
        ("tests/test_cli_input_formats.py", 2),
        ("tests/test_cli_runner_config.py", 4),
        ("tests/test_consensus_config_constraints.py", 1),
        ("tests/test_core_shim.py", 2),
        ("tests/test_err_cases.py", 4),
        ("tests/test_metrics_otlp.py", 1),
        ("tests/test_metrics_prometheus.py", 1),
        ("tests/test_metrics_threadsafe.py", 1),
        ("tests/test_no_src_imports.py", 1),
        ("tests/test_parallel_exec.py", 1),
        ("tests/test_run_metric_schema.py", 3),
        ("tests/test_runner_async_failures.py", 4),
        ("tests/test_runner_consensus.py", 9),
        ("tests/test_runner_modes.py", 8),
        ("tests/test_runner_shared.py", 4),
        ("tests/test_shadow_async.py", 3),
        ("tests/test_shadow_metrics_schema.py", 3),
        ("tests/test_version.py", 1),
    )
)


@pytest.mark.parametrize("path", sorted(SOURCE_ROOT.rglob("*.py")))
def test_no_src_llm_adapter_in_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert FORBIDDEN not in text, (
        f"{path.relative_to(PROJECT_ROOT)} contains '{FORBIDDEN}'"
    )


def test_src_llm_adapter_references_snapshot(
    src_llm_adapter_test_references: OrderedDict[str, int],
) -> None:
    assert src_llm_adapter_test_references == EXPECTED_TEST_REFERENCES
