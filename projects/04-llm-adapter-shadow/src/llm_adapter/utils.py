import hashlib
from typing import Dict, Any


def content_hash(
    provider: str,
    prompt: str,
    options: Dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> str:
    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(prompt.encode())
    h.update(repr(max_tokens).encode())
    if options:
        h.update(repr(sorted(options.items())).encode())
    return h.hexdigest()[:16]
