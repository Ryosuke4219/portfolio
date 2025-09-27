"""共通プロバイダ基底クラス。"""

from __future__ import annotations

from abc import ABC

from ..provider_spi import ProviderSPI

__all__ = ["BaseProvider"]


class BaseProvider(ProviderSPI, ABC):
    """ProviderSPI 実装向けの共通ユーティリティ。"""

    _name: str
    _model: str | None

    def __init__(self, *, name: str, model: str | None = None) -> None:
        name_text = name.strip()
        if not name_text:
            raise ValueError("provider name must be a non-empty string")
        self._name = name_text

        if model is None:
            self._model = None
        else:
            model_text = model.strip()
            if not model_text:
                raise ValueError("provider model must be a non-empty string")
            self._model = model_text

    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    @property
    def model(self) -> str | None:
        return self._model

