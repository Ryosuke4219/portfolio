from __future__ import annotations

from typing import Any

from tests.helpers.fakes import FakeResponse, FakeSession


class BaseChatSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.last_timeout: float | None = None
        self.last_payload: dict[str, Any] | None = None

    def handle_show(self) -> FakeResponse:
        return FakeResponse(status_code=200, payload={})

    def handle_pull(self, *, stream: bool) -> FakeResponse:
        raise AssertionError("unexpected pull request")

    def handle_chat(
        self,
        *,
        json: dict[str, Any] | None,
        timeout: float | None,
        stream: bool,
    ) -> FakeResponse:
        raise NotImplementedError

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.calls.append((url, json, stream))
        if url.endswith("/api/show"):
            return self.handle_show()
        if url.endswith("/api/pull"):
            return self.handle_pull(stream=stream)
        if url.endswith("/api/chat"):
            self.last_timeout = timeout
            self.last_payload = json
            return self.handle_chat(json=json, timeout=timeout, stream=stream)
        raise AssertionError(f"unexpected url: {url}")
