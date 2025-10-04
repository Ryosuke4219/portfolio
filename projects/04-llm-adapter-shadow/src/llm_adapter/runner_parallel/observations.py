"""Observation normalization utilities for consensus runner."""
from __future__ import annotations

from collections.abc import Sequence

from ..provider_spi import ProviderResponse
from .models import ConsensusObservation


def _normalize_observations(
    responses: Sequence[ProviderResponse | ConsensusObservation],
) -> list[ConsensusObservation]:
    observations: list[ConsensusObservation] = []
    for index, entry in enumerate(responses):
        if isinstance(entry, ConsensusObservation):
            observations.append(entry)
            continue
        if isinstance(entry, ProviderResponse):
            observations.append(
                ConsensusObservation(
                    provider_id=f"provider-{index}",
                    response=entry,
                    latency_ms=int(entry.latency_ms),
                    tokens=entry.token_usage,
                )
            )
            continue
        raise TypeError("responses must be ProviderResponse or ConsensusObservation")
    return observations


__all__ = ["_normalize_observations", "ConsensusObservation"]
