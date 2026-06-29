"""AMEP — Abstracted Multimodal Experience Pool (text-only, Phase 1).

Stores past task trajectories with structured outcome metadata, retrieves
context-similar past runs as few-shot examples for the planner, and surfaces
labeled past failures as "avoid this approach" hints.

Modules:
  store     — read/write past trajectories in plan/success/, plan/failed/
  scorer    — similarity scorer (rule-based; embedding swap in later)
  retriever — top-K retrieval over the store using a scorer
"""
from .store import (
    TrajectoryRecord,
    FailureMetadata,
    AmepStore,
    load_store,
)

__all__ = [
    "TrajectoryRecord",
    "FailureMetadata",
    "AmepStore",
    "load_store",
]
from .scorer import (
    RetrievalQuery,
    Scorer,
    RuleScorer,
    make_scorer,
)

__all__.extend([
    "RetrievalQuery",
    "Scorer",
    "RuleScorer",
    "make_scorer",
])

from .retriever import (
    Retriever,
    RetrievalResult,
    ScoredTrajectory,
    retrieve_for_task,
    render_success_examples,
    render_failure_warning,
)

__all__.extend([
    "Retriever",
    "RetrievalResult",
    "ScoredTrajectory",
    "retrieve_for_task",
    "render_success_examples",
    "render_failure_warning",
])
