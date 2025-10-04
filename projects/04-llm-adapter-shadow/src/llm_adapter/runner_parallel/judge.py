"""Judge loading and invocation helpers for consensus evaluation."""
from __future__ import annotations

import importlib
from typing import Any, Callable, cast, Mapping, Sequence

# Local imports (alphabetical)
from ..consensus_candidates import _Candidate
from ..provider_spi import ProviderResponse


def _load_judge(path: str) -> Callable[[Sequence[ProviderResponse]], Any]:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError("judge must be defined as 'module:callable'")
    module = importlib.import_module(module_name)
    judge = getattr(module, attr, None)
    if not callable(judge):
        raise ValueError(f"judge callable {path!r} is not callable")
    return cast(Callable[[Sequence[ProviderResponse]], Any], judge)


def _invoke_judge(
    judge: Callable[[Sequence[ProviderResponse]], Any],
    candidates: Sequence[_Candidate],
) -> tuple[str, float | None]:
    payload = judge([candidate.primary for candidate in candidates])
    if isinstance(payload, Mapping):
        choice, score = max(payload.items(), key=lambda item: float(item[1]))
        return str(choice).strip(), float(score)
    if isinstance(payload, tuple) and len(payload) == 2:
        choice, score = payload
        return str(choice).strip(), float(score)
    if isinstance(payload, str):
        return payload.strip(), None
    raise TypeError("judge must return str, (choice, score) or mapping of scores")


def invoke_consensus_judge(judge: str, candidates: Sequence[_Candidate]) -> tuple[str, float | None]:
    return _invoke_judge(_load_judge(judge), candidates)


__all__ = ["invoke_consensus_judge"]
