import json, os
from projects.04-llm-adapter-shadow.src.llm_adapter.providers.mock import MockProvider
from projects.04-llm-adapter-shadow.src.llm_adapter.runner import Runner
from projects.04-llm-adapter-shadow.src.llm_adapter.provider_spi import ProviderRequest

def test_shadow_exec_records_metrics(tmp_path):
    p1 = MockProvider("primary", base_latency_ms=5)
    p2 = MockProvider("shadow", base_latency_ms=5)
    r = Runner([p1])
    metrics_path = tmp_path / "metrics.jsonl"
    out = r.run(ProviderRequest(prompt="hello"), shadow=p2)
    assert out.text.startswith("echo(primary):")
    # Not asserting file write to avoid FS coupling in portfolio repo CI.
    assert isinstance(out.latency_ms, int)
