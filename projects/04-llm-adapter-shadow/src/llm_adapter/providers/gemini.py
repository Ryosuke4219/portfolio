"""Compatibility facade for the Gemini provider package."""

from __future__ import annotations

from .gemini import GeminiProvider, parse_gemini_messages
from .gemini._sdk import genai

__all__ = ["GeminiProvider", "parse_gemini_messages", "genai"]
