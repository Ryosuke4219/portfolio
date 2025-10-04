"""Legacy shim for refactored parallel consensus helpers.

TODO checklist before removing this shim:
- [ ] Update imports to use ``llm_adapter.runner_parallel`` package directly.
- [ ] Confirm no external references rely on this module path.
- [ ] Remove this shim once downstream dependencies are migrated.
"""
from __future__ import annotations

from .parallel_exec import ParallelExecutionError
from .runner_config import ConsensusConfig
from .runner_parallel.consensus import (
    _normalize_candidate_text,
    compute_consensus,
    ConsensusObservation,
    ConsensusResult,
    invoke_consensus_judge,
    validate_consensus_schema,
)
from .runner_parallel.observations import _normalize_observations

__all__ = [
    "ParallelExecutionError",
    "ConsensusResult",
    "ConsensusObservation",
    "ConsensusConfig",
    "invoke_consensus_judge",
    "_normalize_candidate_text",
    "validate_consensus_schema",
    "compute_consensus",
    "_normalize_observations",
]
