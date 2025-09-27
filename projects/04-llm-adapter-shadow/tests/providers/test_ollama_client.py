from __future__ import annotations

import pytest

from src.llm_adapter.errors import AuthError
from src.llm_adapter.providers.ollama_client import (
    OllamaClient,
    _combine_host,
    _token_usage_from_payload,
)
from tests.helpers.fakes import FakeResponse, FakeSession


def test_combine_host_trims_trailing_slash():
    assert _combine_host("http://localhost/", "/api") == "http://localhost/api"


def test_token_usage_from_payload_extracts_counts():
    usage = _token_usage_from_payload({"prompt_eval_count": 4, "eval_count": 6})
    assert usage.prompt == 4
    assert usage.completion == 6


def test_ollama_client_chat_maps_auth_error():
    class Session(FakeSession):
        def post(self, url, json=None, stream=False, timeout=None):
            if url.endswith("/api/show"):
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                return FakeResponse(status_code=401, payload={})
            raise AssertionError(f"unexpected url: {url}")

    client = OllamaClient("http://localhost", session=Session())

    with pytest.raises(AuthError):
        client.chat({"model": "foo", "messages": []})


def test_ollama_client_chat_success():
    class Session(FakeSession):
        def post(self, url, json=None, stream=False, timeout=None):
            if url.endswith("/api/show"):
                return FakeResponse(status_code=200, payload={})
            if url.endswith("/api/chat"):
                return FakeResponse(
                    status_code=200,
                    payload={
                        "message": {"content": "hi"},
                        "prompt_eval_count": 2,
                        "eval_count": 3,
                    },
                )
            raise AssertionError(f"unexpected url: {url}")

    client = OllamaClient("http://localhost", session=Session())

    payload, latency_ms = client.chat({"model": "foo", "messages": []})
    assert payload["message"]["content"] == "hi"
    assert latency_ms >= 0
    usage = client.token_usage_from_payload(payload)
    assert usage.prompt == 2
    assert usage.completion == 3
