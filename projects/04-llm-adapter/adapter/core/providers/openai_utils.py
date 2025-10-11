# mypy: ignore-errors
"""OpenAI プロバイダ用ユーティリティ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..config import ProviderConfig


def _read_attr(obj: Any, name: str) -> Any:
    """属性アクセス時の例外を抑制しつつ値を取得する。"""

    if obj is None:
        return None
    if hasattr(obj, name):
        try:
            return getattr(obj, name)
        except AttributeError:
            return None
    return None

_API_ORDER = ("responses", "chat_completions", "completions")


def build_system_user_contents(
    system_prompt: str | None, user_prompt: str
) -> list[Mapping[str, Any]]:
    contents: list[Mapping[str, Any]] = []
    if system_prompt:
        contents.append(
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}],
            }
        )
    contents.append({"role": "user", "content": [{"type": "text", "text": user_prompt}]})
    return contents


def build_chat_messages(system_prompt: str | None, user_prompt: str) -> list[Mapping[str, Any]]:
    messages: list[Mapping[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _as_responses_content(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        normalized: list[Mapping[str, Any]] = []
        for entry in value:
            if isinstance(entry, Mapping):
                normalized.append(dict(entry))
        if normalized:
            return normalized
    return [{"type": "text", "text": str(value)}]


def build_responses_input(
    system_prompt: str | None,
    messages: Sequence[Mapping[str, Any]] | None,
    user_prompt: str,
) -> list[Mapping[str, Any]]:
    contents: list[Mapping[str, Any]] = []
    if system_prompt:
        contents.append({"role": "system", "content": _as_responses_content(system_prompt)})
    if messages:
        for entry in messages:
            if not isinstance(entry, Mapping):
                continue
            role = str(entry.get("role", "")).strip() or "user"
            contents.append({"role": role, "content": _as_responses_content(entry.get("content"))})
    elif user_prompt:
        contents.append({"role": "user", "content": _as_responses_content(user_prompt)})
    return contents


def extract_text_from_response(response: Any) -> str:
    text: Any = _read_attr(response, "output_text")
    if isinstance(text, str) and text.strip():
        return text
    text = _read_attr(response, "text")
    if isinstance(text, str) and text.strip():
        return text
    choices = _read_attr(response, "choices")
    if isinstance(choices, Sequence) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, Sequence):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, Mapping):
                            text_part = item.get("text")
                            if isinstance(text_part, str):
                                parts.append(text_part)
                    if parts:
                        return "".join(parts)
            text_value = first.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value
        message_attr = _read_attr(first, "message")
        if isinstance(message_attr, Mapping):
            content_attr = message_attr.get("content")
            if isinstance(content_attr, str) and content_attr.strip():
                return content_attr
        text_attr = _read_attr(first, "text")
        if isinstance(text_attr, str) and text_attr.strip():
            return text_attr
    output = _read_attr(response, "output")
    if isinstance(output, Sequence):
        parts: list[str] = []
        for item in output:
            if isinstance(item, Mapping):
                content = item.get("content")
                if isinstance(content, Sequence):
                    for fragment in content:
                        if isinstance(fragment, Mapping):
                            text_part = fragment.get("text")
                            if isinstance(text_part, str):
                                parts.append(text_part)
                elif isinstance(content, str):
                    parts.append(content)
        if parts:
            return "".join(parts)
    if hasattr(response, "model_dump"):
        try:
            dumped = response.model_dump()
        except Exception:  # pragma: no cover - defensive
            dumped = None
        if isinstance(dumped, Mapping):
            for key in ("output_text", "text"):
                value = dumped.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            choices = dumped.get("choices")
            if isinstance(choices, Sequence) and choices:
                first = choices[0]
                if isinstance(first, Mapping):
                    for path in (("message", "content"), ("text",)):
                        cursor: Any = first
                        for segment in path:
                            if isinstance(cursor, Mapping):
                                cursor = cursor.get(segment)
                            else:
                                cursor = None
                                break
                        if isinstance(cursor, str) and cursor.strip():
                            return cursor
    return ""


def extract_usage_tokens(response: Any, prompt: str, output_text: str) -> tuple[int, int]:
    prompt_tokens = 0
    completion_tokens = 0
    usage = _read_attr(response, "usage")
    if usage is not None:
        prompt_attr = _read_attr(usage, "prompt_tokens")
        if prompt_attr is not None:
            prompt_tokens = int(prompt_attr or 0)
        elif isinstance(usage, Mapping):
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        if prompt_tokens <= 0:
            input_attr = _read_attr(usage, "input_tokens")
            if input_attr is not None:
                prompt_tokens = int(input_attr or 0)
            elif isinstance(usage, Mapping):
                prompt_tokens = int(usage.get("input_tokens", 0) or 0)
        completion_attr = _read_attr(usage, "completion_tokens")
        if completion_attr is not None:
            completion_tokens = int(completion_attr or 0)
        elif isinstance(usage, Mapping):
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        if completion_tokens <= 0:
            output_attr = _read_attr(usage, "output_tokens")
            if output_attr is not None:
                completion_tokens = int(output_attr or 0)
            elif isinstance(usage, Mapping):
                completion_tokens = int(usage.get("output_tokens", 0) or 0)
    if prompt_tokens <= 0 or completion_tokens <= 0:
        if isinstance(usage, Mapping):
            prompt_value = usage.get("prompt_tokens")
            if prompt_value is None:
                prompt_value = usage.get("input_tokens", 0)
            prompt_tokens = int(prompt_value or prompt_tokens)

            completion_value = usage.get("completion_tokens")
            if completion_value is None:
                completion_value = usage.get("output_tokens", 0)
            completion_tokens = int(completion_value or completion_tokens)
    if prompt_tokens <= 0 or completion_tokens <= 0:
        if hasattr(response, "model_dump"):
            try:
                payload = response.model_dump()
            except Exception:  # pragma: no cover - defensive
                payload = None
            if isinstance(payload, Mapping):
                usage_dict = payload.get("usage")
                if isinstance(usage_dict, Mapping):
                    prompt_value = usage_dict.get("prompt_tokens")
                    if prompt_value is None:
                        prompt_value = usage_dict.get("input_tokens", prompt_tokens)
                    prompt_tokens = int(prompt_value or prompt_tokens)

                    completion_value = usage_dict.get("completion_tokens")
                    if completion_value is None:
                        completion_value = usage_dict.get("output_tokens", completion_tokens)
                    completion_tokens = int(completion_value or completion_tokens)
    if prompt_tokens <= 0:
        prompt_tokens = max(1, len(prompt.split()))
    if completion_tokens <= 0:
        tokens = len(output_text.split())
        completion_tokens = max(1, tokens) if tokens else 0
    return prompt_tokens, completion_tokens


def coerce_raw_output(response: Any) -> Mapping[str, Any] | None:
    if hasattr(response, "model_dump"):
        try:
            payload = response.model_dump()
        except Exception:  # pragma: no cover - defensive
            payload = None
        else:
            if isinstance(payload, Mapping):
                return dict(payload)
    if hasattr(response, "to_dict"):
        try:
            payload = response.to_dict()
        except Exception:  # pragma: no cover - defensive
            payload = None
        else:
            if isinstance(payload, Mapping):
                return dict(payload)
    if isinstance(response, Mapping):
        return dict(response)
    return {"repr": repr(response)}


def determine_modes(config: ProviderConfig, endpoint_mode: str | None) -> tuple[str, ...]:
    preferred = config.raw.get("api")
    modes: list[str] = []
    if isinstance(preferred, str) and preferred.strip():
        modes.append(preferred.strip().lower())
    if endpoint_mode:
        modes.append(endpoint_mode)
    modes.extend(_API_ORDER)
    seen: set[str] = set()
    ordered: list[str] = []
    for mode in modes:
        if mode not in _API_ORDER:
            continue
        if mode in seen:
            continue
        seen.add(mode)
        ordered.append(mode)
    return tuple(ordered)


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
        openai_module.api_key = api_key  # type: ignore[attr-defined]
        if endpoint_url:
            openai_module.base_url = endpoint_url  # type: ignore[attr-defined]
        if organization:
            openai_module.organization = organization  # type: ignore[attr-defined]
        if default_headers:
            if hasattr(openai_module, "_default_headers"):
                headers_source = openai_module._default_headers  # type: ignore[attr-defined]
            else:
                headers_source = {}
            headers = dict(headers_source)
            headers.update(default_headers)
            openai_module._default_headers = headers  # type: ignore[attr-defined]
        return openai_module
