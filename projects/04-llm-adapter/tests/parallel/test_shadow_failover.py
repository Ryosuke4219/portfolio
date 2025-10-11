from __future__ import annotations

import pytest

pytest.importorskip("src.llm_adapter.errors")

from src.llm_adapter.errors import AllFailedError
from src.llm_adapter.parallel_exec import run_parallel_all_sync, run_parallel_any_sync
from src.llm_adapter.provider_spi import ProviderRequest, ProviderResponse, ProviderSPI
from src.llm_adapter.runner_config import RunnerConfig as SyncRunnerConfig, RunnerMode as SyncRunnerMode
from src.llm_adapter.runner_sync import Runner as SyncRunner
from src.llm_adapter.runner_sync_modes import get_sync_strategy, SyncRunContext
from src.llm_adapter.runner_sync_parallel_any import ParallelAnyStrategy
from src.llm_adapter.utils import content_hash


# シャドウ挙動
def test_get_sync_strategy_parallel_any_propagates_all_failed(
    tmp_path,
) -> None:
    class _StubProvider(ProviderSPI):
        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def capabilities(self) -> set[str]:
            return set()

        def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - not invoked
            raise AssertionError("provider should not be invoked")

    provider = _StubProvider("stub")
    metrics_path = tmp_path / "metrics.jsonl"
    config = SyncRunnerConfig(
        mode=SyncRunnerMode.PARALLEL_ANY,
        max_attempts=0,
        metrics_path=str(metrics_path),
    )
    runner = SyncRunner([provider], config=config)
    request = ProviderRequest(model="test", prompt="hello")
    request_fingerprint = content_hash(
        "runner",
        request.prompt_text,
        request.options,
        request.max_tokens,
    )
    metadata = {
        "run_id": request_fingerprint,
        "mode": config.mode.value,
        "providers": [provider.name()],
        "shadow_used": False,
        "shadow_provider_id": None,
    }
    context = SyncRunContext(
        runner=runner,
        request=request,
        event_logger=None,
        metadata=metadata,
        run_started=0.0,
        request_fingerprint=request_fingerprint,
        shadow=None,
        shadow_used=False,
        metrics_path=str(metrics_path),
        run_parallel_all=run_parallel_all_sync,
        run_parallel_any=run_parallel_any_sync,
    )

    strategy = get_sync_strategy(config.mode)
    assert isinstance(strategy, ParallelAnyStrategy)

    with pytest.raises(AllFailedError):
        strategy.execute(context)
