from __future__ import annotations

import pytest
from llm_adapter.errors import (
    RateLimitError,
    RetriableError,
    TimeoutError,
)
from llm_adapter.providers._requests_compat import requests_exceptions
from llm_adapter.providers.ollama_client import OllamaClient

# isort: split
from tests.helpers.fakes import FakeResponse, FakeSession


def test_ollama_client_success_paths() -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.timeouts: list[float | None] = []

        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            self.calls.append((url, json, stream))
            self.timeouts.append(timeout)
            if url.endswith("/api/show"):
                return FakeResponse(status_code=200, payload={"result": "ok"})
            if url.endswith("/api/pull"):
                return FakeResponse(status_code=200, payload={"done": True})
            if url.endswith("/api/chat"):
                return FakeResponse(status_code=200, payload={"message": {"content": "hi"}})
            raise AssertionError(url)

    session = Session()
    client = OllamaClient(
        host="http://localhost/",
        session=session,
        timeout=12.5,
        pull_timeout=45.0,
    )

    assert client.show({"model": "m"}).json()["result"] == "ok"
    assert client.pull({"model": "m"}).json()["done"] is True
    assert (
        client.chat({"messages": []}, timeout=2.5).json()["message"]["content"] == "hi"
    )

    assert [url for url, *_ in session.calls] == [
        "http://localhost/api/show",
        "http://localhost/api/pull",
        "http://localhost/api/chat",
    ]
    assert session.timeouts == [12.5, 45.0, 2.5]


def test_ollama_client_normalizes_payload_stream_flag() -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, dict[str, object] | None, bool]] = []

        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            self.calls.append((url, json, stream))
            return FakeResponse(status_code=200, payload={"message": {"content": "ok"}})

    session = Session()
    client = OllamaClient(host="http://h", session=session, timeout=10.0, pull_timeout=5.0)

    client.chat({"messages": [], "stream": "yes"})

    chat_call = next((call for call in session.calls if call[0].endswith("/api/chat")), None)
    assert chat_call is not None
    assert chat_call[2] is True


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (requests_exceptions.ConnectionError, RetriableError),
        (requests_exceptions.Timeout, TimeoutError),
    ],
)
def test_ollama_client_normalizes_session_errors(
    factory: type[BaseException],
    expected: type[Exception],
) -> None:
    class Session(FakeSession):
        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            raise factory()

    client = OllamaClient(host="http://h", session=Session(), timeout=10.0, pull_timeout=10.0)

    with pytest.raises(expected):
        client.chat({"messages": []})


@pytest.mark.parametrize(
    ("method_name", "path", "status", "payload", "kwargs", "expected"),
    [
        ("chat", "/api/chat", 429, {"messages": []}, {}, RateLimitError),
        ("pull", "/api/pull", 500, {"model": "m"}, {}, RetriableError),
    ],
)
def test_ollama_client_closes_responses_on_http_error(
    method_name: str,
    path: str,
    status: int,
    payload: dict[str, object],
    kwargs: dict[str, object],
    expected: type[Exception],
) -> None:
    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.last_response: FakeResponse | None = None

        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            if url.endswith(path):
                response = FakeResponse(status_code=status, payload={})
                self.last_response = response
                return response
            return FakeResponse(status_code=200, payload={})

    session = Session()
    client = OllamaClient(host="http://h", session=session, timeout=10.0, pull_timeout=5.0)

    with pytest.raises(expected):
        getattr(client, method_name)(payload, **kwargs)

    assert session.last_response is not None
    assert session.last_response.closed is True


def test_ollama_client_closes_responses_on_stream_error() -> None:
    if hasattr(requests_exceptions, "ChunkedEncodingError"):
        stream_error_cls = requests_exceptions.ChunkedEncodingError
    elif hasattr(requests_exceptions, "ProtocolError"):
        stream_error_cls = requests_exceptions.ProtocolError
    else:
        stream_error_cls = requests_exceptions.RequestException

    class Session(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.last_response: FakeResponse | None = None

        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            stream: bool = False,
            timeout: float | None = None,
        ) -> FakeResponse:
            response = FakeResponse(
                status_code=200,
                payload={},
                iter_lines_exception=stream_error_cls("boom"),
            )
            self.last_response = response
            return response

    session = Session()
    client = OllamaClient(host="http://h", session=session, timeout=10.0, pull_timeout=5.0)

    with pytest.raises(RetriableError):
        with client.pull({"model": "m"}) as response:
            for _ in response.iter_lines():
                pass

    assert session.last_response is not None
    assert session.last_response.closed is True
