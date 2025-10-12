from __future__ import annotations

from collections import Counter
from typing import Iterable, TypeVar

T = TypeVar("T")


class MajorityVoteStrategy:
    name = "majority_vote"

    def aggregate(self, votes: Iterable[T]) -> T:
        counts: Counter[T] = Counter()
        order: dict[T, int] = {}
        for index, value in enumerate(votes):
            counts[value] += 1
            order.setdefault(value, index)
        if not counts:
            raise ValueError("votes must be non-empty")
        return max(counts.items(), key=lambda item: (item[1], -order[item[0]]))[0]
