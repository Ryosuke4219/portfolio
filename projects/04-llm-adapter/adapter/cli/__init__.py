from __future__ import annotations

import http as _http
import socket as _socket
import sys
from typing import List, Optional

from .doctor import run_doctor
from .prompts import (
    PromptResult as _PromptResult,
    ProviderFactory as _ProviderFactory,
    ProviderResponse as _ProviderResponse,
    RateLimiter as _RateLimiter,
    run_prompts,
)
from .utils import (
    EXIT_ENV_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_PROVIDER_ERROR,
    EXIT_RATE_LIMIT,
)

http = _http
socket = _socket
ProviderFactory = _ProviderFactory
ProviderResponse = _ProviderResponse
RateLimiter = _RateLimiter
PromptResult = _PromptResult

__all__ = [
    "EXIT_ENV_ERROR",
    "EXIT_INPUT_ERROR",
    "EXIT_NETWORK_ERROR",
    "EXIT_OK",
    "EXIT_PROVIDER_ERROR",
    "EXIT_RATE_LIMIT",
    "ProviderFactory",
    "ProviderResponse",
    "PromptResult",
    "RateLimiter",
    "main",
    "run_doctor",
    "run_prompts",
    "http",
    "socket",
]


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv or sys.argv[1:])
    if args and args[0] == "doctor":
        return run_doctor(args[1:], socket_module=socket)
    return run_prompts(args, provider_factory=ProviderFactory)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
