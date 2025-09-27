"""OpenAI プロバイダ用ユーティリティ。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..config import ProviderConfig

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


def extract_text_from_response(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    choices = getattr(response, "choices", None)
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
        message_attr = getattr(first, "message", None)
        if isinstance(message_attr, Mapping):
            content_attr = message_attr.get("content")
            if isinstance(content_attr, str) and content_attr.strip():
                return content_attr
        text_attr = getattr(first, "text", None)
        if isinstance(text_attr, str) and text_attr.strip():
            return text_attr
    output = getattr(response, "output", None)
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
    usage = getattr(response, "usage", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        if prompt_tokens <= 0:
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        if completion_tokens <= 0:
            completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    if prompt_tokens <= 0 or completion_tokens <= 0:
        if isinstance(usage, Mapping):
            prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or prompt_tokens)
            completion_tokens = int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or completion_tokens
            )
    if prompt_tokens <= 0 or completion_tokens <= 0:
        if hasattr(response, "model_dump"):
            try:
                payload = response.model_dump()
            except Exception:  # pragma: no cover - defensive
                payload = None
            if isinstance(payload, Mapping):
                usage_dict = payload.get("usage")
                if isinstance(usage_dict, Mapping):
                    prompt_tokens = int(
                        usage_dict.get("prompt_tokens", usage_dict.get("input_tokens", prompt_tokens))
                        or prompt_tokens
                    )
                    completion_tokens = int(
                        usage_dict.get("completion_tokens", usage_dict.get("output_tokens", completion_tokens))
                        or completion_tokens
                    )
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
        organization = (
            config.raw.get("organization") if isinstance(config.raw.get("organization"), str) else None
        )
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
            setattr(openai_module, "base_url", endpoint_url)
        if organization:
            setattr(openai_module, "organization", organization)
        if default_headers:
            headers = getattr(openai_module, "_default_headers", {})
            headers = dict(headers)
            headers.update(default_headers)
            setattr(openai_module, "_default_headers", headers)
        return openai_module

