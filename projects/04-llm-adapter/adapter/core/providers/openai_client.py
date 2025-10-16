"""OpenAI クライアント生成ユーティリティ。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import ProviderConfig


class OpenAIClientFactory:
    """OpenAI SDK バージョン差異を吸収したクライアント生成器。"""

    def __init__(self, openai_module: Any) -> None:
        self._openai = openai_module

    def create(
        self,
        api_key: str,
        config: ProviderConfig,
        endpoint_url: str | None,
        default_headers: Mapping[str, Any],
    ) -> Any:
        openai_module = self._openai
        organization_raw = config.raw.get("organization")
        organization = organization_raw if isinstance(organization_raw, str) else None
        if hasattr(openai_module, "OpenAI"):
            kwargs: dict[str, Any] = {"api_key": api_key}
            if endpoint_url:
                kwargs["base_url"] = endpoint_url
            if organization:
                kwargs["organization"] = organization
            if default_headers:
                kwargs["default_headers"] = dict(default_headers)
            return openai_module.OpenAI(**kwargs)
        openai_module.api_key = api_key
        if endpoint_url:
            openai_module.base_url = endpoint_url
        if organization:
            openai_module.organization = organization
        if default_headers:
            if hasattr(openai_module, "_default_headers"):
                headers_source = openai_module._default_headers
            else:
                headers_source = {}
            headers = dict(headers_source)
            headers.update(default_headers)
            openai_module._default_headers = headers
        return openai_module


__all__ = ["OpenAIClientFactory"]
