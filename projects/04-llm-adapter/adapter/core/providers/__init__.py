"""プロバイダとのインタフェース。"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
import warnings

from ..config import ProviderConfig
from ..provider_spi import ProviderRequest, ProviderResponse as _ProviderResponse, TokenUsage

LOGGER = logging.getLogger(__name__)


class ProviderResponse(_ProviderResponse):
    """LLM 呼び出しの結果（後方互換ラッパー）。"""

    def __init__(
        self,
        *,
        text: str | None = None,
        latency_ms: int = 0,
        token_usage: TokenUsage | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        raw: Any | None = None,
        output_text: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        raw_output: Any | None = None,
    ) -> None:
        selected_text = text if text is not None else (output_text or "")
        if token_usage is None and (input_tokens is not None or output_tokens is not None):
            token_usage = TokenUsage(
                prompt=int(input_tokens or 0),
                completion=int(output_tokens or 0),
            )
        raw_value = raw if raw is not None else raw_output
        super().__init__(
            text=selected_text,
            latency_ms=latency_ms,
            token_usage=token_usage,
            model=model,
            finish_reason=finish_reason,
            raw=raw_value,
        )

    # --- compatibility aliases (shadow 互換) ---
    @property
    def output_text(self) -> str:
        return self.text

    @property
    def input_tokens(self) -> int:
        return self.token_usage.prompt

    @property
    def output_tokens(self) -> int:
        return self.token_usage.completion

    @property
    def raw_output(self) -> Any | None:
        return self.raw


class BaseProvider:
    """LLM プロバイダの共通インタフェース。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def name(self) -> str:
        return self.config.provider

    def capabilities(self) -> set[str]:
        return {"chat"}

    def invoke(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover - インタフェース
        raise NotImplementedError

    def generate(self, prompt: str) -> ProviderResponse:
        warnings.warn(
            "BaseProvider.generate() は非推奨です。ProviderRequest を受け取る invoke() を利用してください。",
            DeprecationWarning,
            stacklevel=2,
        )
        model = (self.config.model or self.config.provider).strip()
        request = ProviderRequest(model=model, prompt=prompt)
        return self.invoke(request)


class SimulatedProvider(BaseProvider):
    """実際の API 呼び出しを伴わない簡易シミュレータ。"""

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        prompt = request.prompt
        # 擬似レイテンシ（文字数に比例）
        latency_ms = min(len(prompt) * 5, 1500)
        time.sleep(latency_ms / 1000.0 / 100.0)
        seed_material = f"{self.config.seed}:{request.model}:{prompt}".encode()
        digest = hashlib.sha256(seed_material).hexdigest()
        normalized = prompt.lower()
        if "return success" in normalized:
            output = "SUCCESS"
        elif "respond with reset_ok" in normalized:
            output = "RESET_OK"
        else:
            output = "SIMULATED:" + digest[:24]
        prompt_tokens = max(1, len(prompt.split()))
        output_tokens = max(1, len(output.split()))
        token_usage = TokenUsage(prompt=prompt_tokens, completion=output_tokens)
        return ProviderResponse(
            text=output,
            latency_ms=latency_ms,
            token_usage=token_usage,
            model=request.model,
            raw={"simulated": True, "digest": digest},
        )


class ProviderFactory:
    """プロバイダ生成のためのファクトリ。"""

    _registry: dict[str, type[BaseProvider]] = {"simulated": SimulatedProvider}

    @classmethod
    def register(cls, provider_name: str, provider_cls: type[BaseProvider]) -> None:
        cls._registry[provider_name] = provider_cls

    @classmethod
    def available(cls) -> tuple[str, ...]:
        return tuple(sorted(cls._registry))

    @classmethod
    def create(cls, config: ProviderConfig) -> BaseProvider:
        provider_cls = cls._registry.get(config.provider)
        if provider_cls is None:
            supported = ", ".join(cls.available())
            raise ValueError(
                "unsupported provider prefix: "
                f"{config.provider}. supported: {supported}. "
                "OpenAI は無印、Gemini は google-genai を導入してください。"
            )
        return provider_cls(config)


try:  # pragma: no cover - optional依存の存在に応じて処理
    from .gemini import GeminiProvider
except Exception:  # pragma: no cover - 依存不足時は gemini を登録しない
    GeminiProvider = None  # type: ignore[assignment]
else:  # pragma: no cover - 実行時に gemini プロバイダを登録
    ProviderFactory.register("gemini", GeminiProvider)

try:  # pragma: no cover - optional依存の存在に応じて処理
    from .openai import OpenAIProvider
except Exception:  # pragma: no cover - 依存不足時は openai を登録しない
    OpenAIProvider = None  # type: ignore[assignment]
else:  # pragma: no cover - 実行時に openai プロバイダを登録
    ProviderFactory.register("openai", OpenAIProvider)
