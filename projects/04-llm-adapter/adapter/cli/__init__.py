from __future__ import annotations

import http as _http
import socket as _socket
import sys

from adapter.core import providers as provider_module

from .app import app, main
from .doctor import run_doctor
from .prompt_runner import PromptResult as _PromptResult, RateLimiter as _RateLimiter
from .prompts import ProviderFactory as _ProviderFactory, run_prompts
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
ProviderResponse = provider_module.ProviderResponse
RateLimiter = _RateLimiter
PromptResult = _PromptResult

__all__ = [
    "EXIT_ENV_ERROR",
    "EXIT_INPUT_ERROR",
    "EXIT_NETWORK_ERROR",
    "EXIT_OK",
    "EXIT_PROVIDER_ERROR",
    "EXIT_RATE_LIMIT",
    "app",
    "ProviderFactory",
    "ProviderResponse",
    "PromptResult",
    "RateLimiter",
    "run_doctor",
    "run_prompts",
    "http",
    "socket",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
