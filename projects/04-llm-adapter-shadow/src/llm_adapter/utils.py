import hashlib
from typing import Dict, Any

def content_hash(provider: str, prompt: str, options: Dict[str, Any] | None = None) -> str:
    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(prompt.encode())
    if options:
        h.update(repr(sorted(options.items())).encode())
    return h.hexdigest()[:16]
