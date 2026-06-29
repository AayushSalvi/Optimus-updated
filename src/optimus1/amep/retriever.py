"""AMEP retriever — combines store + scorer for top-K retrieval.

Public entry points:
  retrieve(query) -> RetrievalResult
    Returns scored top-K successes and top-1 failure (if available).

The retriever is intentionally stateless — it constructs fresh on each call
to pick up any new past trajectories written between calls.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .store import AmepStore, TrajectoryRecord, load_store
from .scorer import RetrievalQuery, Scorer, RuleScorer, make_scorer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class ScoredTrajectory:
    """A past trajectory paired with its similarity score for the current query."""
    record: TrajectoryRecord
    score: float

    def short_summary(self) -> str:
        return (
            f"score={self.score:.3f} steps={self.record.steps} "
            f"env={self.record.environment[:40]!r}"
        )


@dataclass
class RetrievalResult:
    """Top-K successes + optional best-matching failure for a query."""
    query: RetrievalQuery
    successes: List[ScoredTrajectory] = field(default_factory=list)
    failure: Optional[ScoredTrajectory] = None
    scorer_name: str = ""

    def has_any(self) -> bool:
        return bool(self.successes) or self.failure is not None

    def best_success(self) -> Optional[ScoredTrajectory]:
        return self.successes[0] if self.successes else None


# ---------------------------------------------------------------------------
# Render helpers — turn retrieved records into planner-prompt-ready text
# ---------------------------------------------------------------------------
def render_plan_as_steps(planning: List[dict]) -> dict:
    """Convert a planning list into the {step N: ...} dict the planner prompt expects.

    Format mirrors what Optimus-1's PLAN_EXAMPLE_FORMAT consumes.
    """
    out = {}
    for idx, p in enumerate(planning):
        out[f"step {idx+1}"] = p
    return out


def render_success_examples(scored: List[ScoredTrajectory], limit: int = 3) -> str:
    """Render top-K success trajectories as a multi-example block.

    Used as a few-shot context section for the planner LLM.
    """
    if not scored:
        return ""
    parts = ["[AMEP] Past successful runs of this or similar tasks:"]
    for i, st in enumerate(scored[:limit]):
        r = st.record
        plan_dict = render_plan_as_steps(r.planning)
        parts.append(
            f"\n  Example {i+1} (env={r.environment!r}, steps={r.steps}, score={st.score:.2f}):\n"
            f"  {json.dumps(plan_dict)}"
        )
    return "\n".join(parts)


def render_failure_warning(scored: ScoredTrajectory) -> str:
    """Render a single past failure as a 'don't do this' warning for the planner.

    Only rendered if the failure has populated failure_metadata.
    """
    r = scored.record
    if r.failure_metadata is None:
        return ""
    fm = r.failure_metadata
    plan_dict = render_plan_as_steps(r.planning)
    parts = [
        "[AMEP] A past attempt at this task FAILED with the plan below. Avoid repeating its mistakes:",
        f"  Failed plan: {json.dumps(plan_dict)}",
    ]
    if fm.failed_subtask:
        parts.append(f"  Got stuck at sub-task: {fm.failed_subtask!r} (after {fm.failed_at_step} steps)")
    if fm.pending_outcomes:
        parts.append(f"  Outcomes still pending at failure: {fm.pending_outcomes}")
    if fm.last_error:
        parts.append(f"  Last error: {fm.last_error}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------
class Retriever:
    """Top-K retrieval over the past trajectory store using a pluggable scorer."""

    def __init__(self, store: Optional[AmepStore] = None, scorer: Optional[Scorer] = None):
        self.store = store or load_store()
        self.scorer = scorer or RuleScorer()

    def retrieve(self, query: RetrievalQuery, k_success: int = 3, min_success_score: float = 0.3) -> RetrievalResult:
        """Return top-K successes and best matching failure for a query.

        Args:
            query: current task context
            k_success: how many top successes to return (planner gets top-1 as primary,
                       others shown as alternatives)
            min_success_score: candidates below this are filtered out
        """
        result = RetrievalResult(query=query, scorer_name=self.scorer.name())

        # Successes — filtered by exact-task match in the store (case-insensitive)
        success_records = self.store.read_successes(query.task)
        scored_successes = [
            ScoredTrajectory(record=r, score=self.scorer.score(query, r))
            for r in success_records
        ]
        scored_successes.sort(key=lambda x: x.score, reverse=True)
        result.successes = [s for s in scored_successes if s.score >= min_success_score][:k_success]

        # Failure — top-1 with failure_metadata only
        failure_records = self.store.read_failures(query.task)
        scored_failures = [
            ScoredTrajectory(record=r, score=self.scorer.score(query, r))
            for r in failure_records
            if r.failure_metadata is not None  # need a real explanation to be useful
        ]
        scored_failures.sort(key=lambda x: x.score, reverse=True)
        if scored_failures and scored_failures[0].score >= min_success_score:
            result.failure = scored_failures[0]

        logger.info(
            f"[AMEP.retriever] task={query.task!r} env={query.environment[:30]!r}: "
            f"{len(result.successes)} successes, {'1 failure' if result.failure else '0 failures'} "
            f"(scorer={self.scorer.name()})"
        )
        return result


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------
def retrieve_for_task(
    task: str,
    environment: str = "",
    initial_inventory: Optional[dict] = None,
    dimension: str = "overworld",
    scorer_kind: str = "rule",
    k_success: int = 3,
) -> RetrievalResult:
    """One-shot retrieval — build query, retriever, scorer, fetch.

    Used by the integration patch in memory.py::retrieve_plan to avoid forcing
    callers to instantiate the full pipeline.
    """
    query = RetrievalQuery(
        task=task,
        environment=environment or "",
        initial_inventory=initial_inventory or {},
        dimension=dimension,
    )
    retriever = Retriever(scorer=make_scorer(scorer_kind))
    return retriever.retrieve(query, k_success=k_success)
