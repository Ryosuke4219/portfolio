from src.llm_adapter.providers.mock import MockProvider
from src.llm_adapter.provider_spi import ProviderRequest
from src.llm_adapter.runner import Runner

if __name__ == "__main__":
    primary = MockProvider("openai-like", base_latency_ms=20)
    shadow = MockProvider("anthropic-like", base_latency_ms=15)
    runner = Runner([primary])
    res = runner.run(ProviderRequest(prompt="こんにちは、世界"), shadow=shadow)
    print(res.text, res.latency_ms, "ms")
    print("Shadow metrics would be written to artifacts/runs-metrics.jsonl")
