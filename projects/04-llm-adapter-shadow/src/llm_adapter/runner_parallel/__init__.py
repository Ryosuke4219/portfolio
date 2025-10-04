"""Parallel runner consensus utilities."""
from __future__ import annotations

from ..runner_config import ConsensusConfig
from .consensus import (
    _Candidate,
    _normalize_candidate_text,
    compute_consensus,
    ConsensusObservation,
    ConsensusResult,
    invoke_consensus_judge,
    validate_consensus_schema,
)
from .observations import _normalize_observations

__all__ = [
    "ConsensusConfig",
    "_Candidate",
    "_normalize_candidate_text",
    "compute_consensus",
    "ConsensusObservation",
    "ConsensusResult",
    "invoke_consensus_judge",
    "validate_consensus_schema",
    "_normalize_observations",
]
