"""Tests for structured input formats handled by the CLI."""
from __future__ import annotations

import json
from pathlib import Path

from llm_adapter import cli
from src.llm_adapter.provider_spi import ProviderResponse, TokenUsage


def test_prepare_execution_consumes_json_payload(tmp_path: Path) -> None:
    payload = {
        "prompt": "tell me a story",
        "messages": [
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "hello"},
        ],
        "options": {"temperature": 0.2},
        "metadata": {"trace_id": "abc-123"},
    }
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    args = cli.parse_args(
        [
            "--mode",
            "sequential",
            "--providers",
            "mock:demo",
            "--input",
            str(path),
        ]
    )

    _runner, request, _metrics = cli.prepare_execution(args)

    assert request.prompt_text == "tell me a story"
    assert request.chat_messages[0] == {"role": "system", "content": "be concise"}
    assert request.chat_messages[-1]["content"] == "hello"
    assert request.options == {"temperature": 0.2}
    assert request.metadata == {"trace_id": "abc-123"}


def test_prepare_execution_consumes_first_jsonl_record(tmp_path: Path) -> None:
    path = tmp_path / "payload.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "prompt": "first record",
                        "messages": [{"role": "user", "content": "hi"}],
                        "options": {"temperature": 0.5},
                    }
                ),
                json.dumps({"prompt": "second"}),
            ]
        ),
        encoding="utf-8",
    )

    args = cli.parse_args(
        [
            "--mode",
            "sequential",
            "--providers",
            "mock:demo",
            "--input",
            str(path),
        ]
    )

    _runner, request, _metrics = cli.prepare_execution(args)

    assert request.prompt_text == "first record"
    assert request.chat_messages == [{"role": "user", "content": "hi"}]
    assert request.options == {"temperature": 0.5}
    assert request.metadata is None


def test_format_output_serializes_metadata_for_json_variants() -> None:
    response = ProviderResponse(
        text="ok",
        latency_ms=123,
        model="mock:demo",
        finish_reason="stop",
        token_usage=TokenUsage(prompt=7, completion=5),
        raw={"provider": "mock:demo"},
    )

    json_payload = json.loads(cli._format_output(response, "json"))
    jsonl_payload = json.loads(cli._format_output(response, "jsonl"))

    for payload in (json_payload, jsonl_payload):
        assert payload["status"] == "success"
        assert payload["provider"] == "mock:demo"
        assert payload["latency_ms"] == 123
        assert payload["text"] == "ok"
        assert payload["token_usage"] == {"prompt": 7, "completion": 5, "total": 12}
