from __future__ import annotations

from typing import Iterable, Tuple, TypeVar

T = TypeVar("T")


class WeightedVoteStrategy:
    name = "weighted_vote"

    def aggregate(self, votes: Iterable[Tuple[T, float]]) -> T:
        totals: dict[T, float] = {}
        order: dict[T, int] = {}
        for index, (candidate, weight) in enumerate(votes):
            totals[candidate] = totals.get(candidate, 0.0) + weight
            order.setdefault(candidate, index)
        if not totals:
            raise ValueError("votes must be non-empty")
        return max(totals.items(), key=lambda item: (item[1], -order[item[0]]))[0]
