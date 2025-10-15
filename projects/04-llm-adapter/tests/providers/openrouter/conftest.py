from __future__ import annotations

from collections.abc import Iterator
import importlib
from pathlib import Path
from typing import Any, Protocol

import pytest

from adapter.core.config import (
    PricingConfig,
    ProviderConfig,
    QualityGatesConfig,
    RateLimitConfig,
    RetryConfig,
)


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status_code: int = 200,
        lines: list[bytes] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.closed = False
        self._lines = list(lines or [])

    def json(self) -> dict[str, Any]:
        return self._payload

    def iter_lines(self) -> Iterator[bytes]:
        yield from self._lines

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Responder(Protocol):
    def __call__(
        self,
        url: str,
        payload: dict[str, Any] | None,
        stream: bool,
        timeout: float | None,
    ) -> FakeResponse:
        """Return a fake response for the given request."""


def load_openrouter_module() -> Any:
    try:
        return importlib.import_module("adapter.core.providers.openrouter")
    except ModuleNotFoundError as exc:  # pragma: no cover - RED 期待
        pytest.fail(f"openrouter provider module is missing: {exc}")


def provider_config(tmp_path: Path) -> ProviderConfig:
    config_path = tmp_path / "openrouter.yaml"
    config_path.write_text("{}", encoding="utf-8")
    return ProviderConfig(
        path=config_path,
        schema_version=1,
        provider="openrouter",
        endpoint="https://mock.openrouter.test/api/v1",
        model="meta-llama/llama-3-8b-instruct:free",
        auth_env="OPENROUTER_API_KEY",
        seed=0,
        temperature=0.2,
        top_p=0.9,
        max_tokens=256,
        timeout_s=15,
        retries=RetryConfig(max=0, backoff_s=0.0),
        persist_output=False,
        pricing=PricingConfig(),
        rate_limit=RateLimitConfig(),
        quality_gates=QualityGatesConfig(),
        raw={},
    )


def install_fake_session(module: Any, responder: Responder) -> pytest.MonkeyPatch:
    class _Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any] | None, bool, float | None]] = []
            self._headers: dict[str, str] = {}

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            *,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            self.calls.append((url, json, stream, timeout))
            return responder(url, json, stream, timeout)

        @property
        def headers(self) -> dict[str, str]:  # pragma: no cover - mutated by provider
            return self._headers

    monkeypatch = pytest.MonkeyPatch()
    session = _Session()
    monkeypatch.setattr(module, "create_session", lambda: session, raising=False)
    return monkeypatch


__all__ = [
    "FakeResponse",
    "Responder",
    "install_fake_session",
    "load_openrouter_module",
    "provider_config",
]
