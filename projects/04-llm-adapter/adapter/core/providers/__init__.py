"""プロバイダとのインタフェース。"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Type

from ..config import ProviderConfig

LOGGER = logging.getLogger(__name__)


@dataclass
class ProviderResponse:
    """LLM 呼び出しの結果。"""

    output_text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_output: Optional[dict] = None


class BaseProvider:
    """LLM プロバイダの共通インタフェース。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def generate(self, prompt: str) -> ProviderResponse:  # pragma: no cover - インタフェース
        raise NotImplementedError


class SimulatedProvider(BaseProvider):
    """実際の API 呼び出しを伴わない簡易シミュレータ。"""

    def generate(self, prompt: str) -> ProviderResponse:
        # 擬似レイテンシ（文字数に比例）
        latency_ms = min(len(prompt) * 5, 1500)
        time.sleep(latency_ms / 1000.0 / 100.0)
        seed_material = f"{self.config.seed}:{self.config.model}:{prompt}".encode("utf-8")
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
        return ProviderResponse(
            output_text=output,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_output={"simulated": True, "digest": digest},
        )


class ProviderFactory:
    """プロバイダ生成のためのファクトリ。"""

    _registry: Dict[str, Type[BaseProvider]] = {"simulated": SimulatedProvider}

    @classmethod
    def register(cls, provider_name: str, provider_cls: Type[BaseProvider]) -> None:
        cls._registry[provider_name] = provider_cls

    @classmethod
    def create(cls, config: ProviderConfig) -> BaseProvider:
        provider_cls = cls._registry.get(config.provider)
        if provider_cls is None:
            LOGGER.warning(
                "未知のプロバイダ '%s' が指定されたため simulated にフォールバックします", config.provider
            )
            provider_cls = SimulatedProvider
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
