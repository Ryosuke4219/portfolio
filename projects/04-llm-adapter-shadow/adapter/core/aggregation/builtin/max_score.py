from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


class MaxScoreStrategy:
    name = "max_score"

    def aggregate(self, entries: Iterable[tuple[T, float]]) -> T:
        best_candidate: T | None = None
        best_score = float("-inf")
        order: dict[T, int] = {}
        for index, (candidate, score) in enumerate(entries):
            order.setdefault(candidate, index)
            if best_candidate is None or score > best_score:
                best_candidate = candidate
                best_score = score
                continue
            if score == best_score and order[candidate] < order[best_candidate]:
                best_candidate = candidate
        if best_candidate is None:
            raise ValueError("entries must be non-empty")
        return best_candidate
