"""Parallel runner consensus utilities."""
from __future__ import annotations

from ..runner_config import ConsensusConfig
from .consensus import (
    ConsensusObservation,
    ConsensusResult,
    compute_consensus,
    invoke_consensus_judge,
    _Candidate,
    _normalize_candidate_text,
    validate_consensus_schema,
)
from .observations import _normalize_observations

__all__ = [
    "ConsensusObservation",
    "ConsensusResult",
    "ConsensusConfig",
    "compute_consensus",
    "invoke_consensus_judge",
    "_Candidate",
    "_normalize_candidate_text",
    "validate_consensus_schema",
    "_normalize_observations",
]
