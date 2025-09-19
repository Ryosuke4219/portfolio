import time, random
from ..provider_spi import ProviderSPI, ProviderRequest, ProviderResponse, TokenUsage
from ..errors import TimeoutError, RateLimitError, RetriableError

class MockProvider(ProviderSPI):
    def __init__(self, name: str, base_latency_ms: int = 50):
        self._name = name
        self.base_latency_ms = base_latency_ms

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        text = request.prompt
        # Trigger errors by markers in prompt
        if "[TIMEOUT]" in text:
            time.sleep(self.base_latency_ms / 1000.0)
            raise TimeoutError("simulated timeout")
        if "[RATELIMIT]" in text:
            raise RateLimitError("simulated rate limit")
        if "[INVALID_JSON]" in text:
            raise RetriableError("simulated invalid JSON")

        latency = self.base_latency_ms + int(random.random()*20)
        time.sleep(latency / 1000.0)
        prompt_tokens = max(1, len(text)//4)
        completion = 16
        return ProviderResponse(
            text=f"echo({self._name}): {text}",
            token_usage=TokenUsage(prompt=prompt_tokens, completion=completion),
            latency_ms=latency,
        )
