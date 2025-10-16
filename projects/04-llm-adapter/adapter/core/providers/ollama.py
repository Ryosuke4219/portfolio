"""Ollama provider with automatic model management."""
from __future__ import annotations

from ..config import ProviderConfig
from ..errors import ConfigError
from ..provider_spi import ProviderRequest
from . import BaseProvider, ProviderResponse
from ._requests_compat import create_session, requests_exceptions
from .ollama_client import OllamaClient
from .ollama_connection import DEFAULT_HOST, OllamaConnectionHelper
from .ollama_runtime import OllamaRuntimeHelper

__all__ = ["OllamaProvider", "DEFAULT_HOST", "requests_exceptions"]


class OllamaProvider(BaseProvider):
    """Provider backed by the local Ollama HTTP API."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        connection = OllamaConnectionHelper.from_config(
            config,
            client_cls=OllamaClient,
            session_factory=create_session,
        )
        self._connection = connection
        self._client = connection.client
        self._host = connection.host
        self._timeout = connection.timeout
        self._pull_timeout = connection.pull_timeout
        self._offline = connection.offline
        self._auto_pull = connection.auto_pull
        self._allow_network = connection.allow_network
        self._ready_models: set[str] = set()

    def _ensure_model(self, model_name: str) -> None:
        OllamaRuntimeHelper.ensure_model(
            self._connection, self._client, self._ready_models, model_name
        )

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        OllamaRuntimeHelper.ensure_network_access(self._connection)

        model_name = request.model.strip()
        if not model_name:
            raise ConfigError("OllamaProvider requires request.model to be set")
        self._ensure_model(model_name)
        payload, stream, timeout_override = OllamaRuntimeHelper.build_chat_payload(
            model_name, request
        )
        payload_json, latency_ms = OllamaRuntimeHelper.invoke_chat(
            self._client,
            payload,
            stream=stream,
            timeout_override=timeout_override,
        )
        return OllamaRuntimeHelper.build_response(
            payload_json, model_name=model_name, latency_ms=latency_ms
        )
