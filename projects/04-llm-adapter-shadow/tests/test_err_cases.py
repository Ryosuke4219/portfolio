from projects.04-llm-adapter-shadow.src.llm_adapter.providers.mock import MockProvider
from projects.04-llm-adapter-shadow.src.llm_adapter.runner import Runner
from projects.04-llm-adapter-shadow.src.llm_adapter.provider_spi import ProviderRequest

def test_timeout_fallback():
    p1 = MockProvider("p1", base_latency_ms=10)
    p2 = MockProvider("p2", base_latency_ms=10)
    r = Runner([p1, p2])
    out = r.run(ProviderRequest(prompt="[TIMEOUT] hello"))
    assert out.text.startswith("echo(p2):")

def test_ratelimit_retry_fallback():
    p1 = MockProvider("p1", base_latency_ms=5)
    p2 = MockProvider("p2", base_latency_ms=5)
    r = Runner([p1, p2])
    out = r.run(ProviderRequest(prompt="[RATELIMIT] test"))
    assert out.text.startswith("echo(p2):")

def test_invalid_json_fallback():
    p1 = MockProvider("p1", base_latency_ms=5)
    p2 = MockProvider("p2", base_latency_ms=5)
    r = Runner([p1, p2])
    out = r.run(ProviderRequest(prompt="[INVALID_JSON] test"))
    assert out.text.startswith("echo(p2):")
