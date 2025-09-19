import time
from typing import List, Optional
from .provider_spi import ProviderSPI, ProviderRequest, ProviderResponse
from .errors import TimeoutError, RateLimitError, RetriableError
from .shadow import run_with_shadow

class Runner:
    def __init__(self, providers: List[ProviderSPI]):
        self.providers = providers

    def run(self, request: ProviderRequest, shadow: Optional[ProviderSPI] = None) -> ProviderResponse:
        last_err = None
        for p in self.providers:
            try:
                return run_with_shadow(p, shadow, request)
            except RateLimitError as e:
                last_err = e
                time.sleep(0.05)  # small backoff then try next
            except (TimeoutError, RetriableError) as e:
                last_err = e
                continue
        raise last_err or RuntimeError("No providers succeeded")
