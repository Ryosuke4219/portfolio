"""Backward compatible wrapper for the Ollama provider package."""

from .ollama.provider import DEFAULT_HOST, OllamaProvider

__all__ = ["OllamaProvider", "DEFAULT_HOST"]
