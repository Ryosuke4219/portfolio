"""多数決集約ストラテジ。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from typing import Any

from .. import AggregationCandidate, AggregationResult, TieBreaker
from .tie_breakers import FirstTieBreaker

__all__ = ["MajorityVoteStrategy"]

_WHITESPACE_RE = re.compile(r"\s+")


class MajorityVoteStrategy:
    name = "majority_vote"

    def __init__(self, *, schema: Mapping[str, Any] | None = None) -> None:
        self._schema = schema
        self._required_keys = self._extract_required_keys(schema)

    def _extract_required_keys(self, schema: Mapping[str, Any] | None) -> frozenset[str]:
        if not isinstance(schema, Mapping):
            return frozenset()
        required = schema.get("required")
        if isinstance(required, Sequence) and not isinstance(required, str | bytes):
            keys = [key for key in required if isinstance(key, str)]
            return frozenset(keys)
        return frozenset()

    def _normalize_text(self, value: str | None) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return ""
        normalized = _WHITESPACE_RE.sub(" ", normalized)
        return normalized.lower()

    def _json_bucket_key(self, value: str) -> str | None:
        if not self._schema:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return f"json:{canonical}"

    def _bucket_key(self, candidate: AggregationCandidate) -> str:
        raw = candidate.text if candidate.text is not None else candidate.response.text
        json_key = self._json_bucket_key(raw)
        if json_key is not None:
            return json_key
        return self._normalize_text(raw)

    def _bucket_is_complete(self, key: str, candidate: AggregationCandidate) -> bool:
        if not self._required_keys or not key.startswith("json:"):
            return False
        raw = (candidate.text if candidate.text is not None else candidate.response.text) or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        return all(required_key in payload for required_key in self._required_keys)

    def aggregate(
        self, candidates: Sequence[AggregationCandidate], *, tiebreaker: TieBreaker | None = None
    ) -> AggregationResult:
        if not candidates:
            raise ValueError("majority_vote: candidates must be non-empty")

        buckets: dict[str, list[AggregationCandidate]] = {}
        completeness: dict[str, bool] = {}
        for candidate in candidates:
            key = self._bucket_key(candidate)
            buckets.setdefault(key, []).append(candidate)
            if key not in completeness:
                completeness[key] = self._bucket_is_complete(key, candidate)

        max_bucket: list[AggregationCandidate] = []
        max_count = -1
        max_complete = False
        for key, bucket in buckets.items():
            count = len(bucket)
            bucket_complete = completeness.get(key, False)
            if count > max_count:
                max_bucket = bucket
                max_count = count
                max_complete = bucket_complete
            elif count == max_count and bucket_complete and not max_complete:
                max_bucket = bucket
                max_complete = True

        breaker = tiebreaker or FirstTieBreaker()
        chosen = max_bucket[0] if len(max_bucket) == 1 else breaker.break_tie(max_bucket)
        reason = f"majority_vote({max_count})"
        tie_used = None if len(max_bucket) == 1 else breaker.name

        return AggregationResult(
            chosen=chosen,
            candidates=list(candidates),
            strategy=self.name,
            reason=reason,
            tie_breaker_used=tie_used,
            metadata={"bucket_size": max_count},
        )
