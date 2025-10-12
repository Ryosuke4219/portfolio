"""stream_probe ツールのストリーミング挙動を検証するテスト。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from tools.openrouter import stream_probe as stream_probe_module
from tools.openrouter.stream_probe import run_probe


class _DummyResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self.closed = False

    def iter_lines(self) -> list[bytes]:
        return list(self._lines)

    def raise_for_status(self) -> None:  # pragma: no cover - interface準拠
        return None

    def close(self) -> None:
        self.closed = True


class _DummySession:
    def __init__(self, response: _DummyResponse) -> None:
        self._response = response
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: dict[str, Any], stream: bool, timeout: float) -> _DummyResponse:
        self.calls.append({"url": url, "json": json, "stream": stream, "timeout": timeout})
        return self._response


@pytest.fixture
def provider_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "adapter" / "config" / "providers" / "openrouter.yaml"


def test_run_probe_logs_streaming_chunks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider_config_path: Path,
) -> None:
    lines = [
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        b'data: {"choices":[{"delta":{"content":" World"},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":7}}',
    ]
    response = _DummyResponse(lines)
    session = _DummySession(response)
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-token")
    caplog.set_level(logging.INFO, logger="tools.openrouter.stream_probe")

    status = run_probe(
        provider_path=provider_config_path,
        prompt="Ping",
        session=session,
    )

    assert status == 0
    assert response.closed is True
    assert session.calls and session.calls[0]["stream"] is True
    chunk_logs = [record.message for record in caplog.records if "chunk:" in record.message]
    assert any("Hello" in message for message in chunk_logs)
    assert any("World" in message for message in chunk_logs)
    assert all("T" in message.split()[0] for message in chunk_logs)


def test_run_probe_skips_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider_config_path: Path,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    caplog.set_level(logging.INFO, logger="tools.openrouter.stream_probe")

    status = run_probe(
        provider_path=provider_config_path,
        prompt="Ping",
    )

    assert status == 0
    messages = [record.message for record in caplog.records]
    assert any("OPENROUTER_API_KEY" in message for message in messages)
    assert all("chunk:" not in message for message in messages)


def test_cli_dry_run_skips_invocation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _unexpected_run_probe(*_: Any, **__: Any) -> int:
        raise AssertionError("run_probe should not be called during dry-run")

    monkeypatch.setattr(stream_probe_module, "run_probe", _unexpected_run_probe)
    caplog.set_level(logging.INFO, logger="tools.openrouter.stream_probe")

    status = stream_probe_module.main(["--dry-run"])

    assert status == 0
    messages = [record.message for record in caplog.records if record.name == "tools.openrouter.stream_probe"]
    assert messages == ["Dry-run: set OPENROUTER_API_KEY and re-run to invoke OpenRouter probe."]
