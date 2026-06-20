#!/bin/bash
# install_amep_step3.sh
# Step 3: retriever.py — top-K retrieval using store + scorer.
# Returns separate success/failure result sets with structured render output.
#
# Run from ~/Optimus-1.

set -e
cd ~/Optimus-1

AMEP_DIR="src/optimus1/amep"

if [ ! -f "$AMEP_DIR/scorer.py" ]; then
  echo "ERROR: $AMEP_DIR/scorer.py not found. Run Step 2 first."
  exit 1
fi

if [ -f "$AMEP_DIR/retriever.py" ]; then
  echo "ERROR: $AMEP_DIR/retriever.py already exists. Remove before re-running."
  exit 1
fi

# ----- retriever.py -----
cat > "$AMEP_DIR/retriever.py" << 'PYEOF'
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
PYEOF

echo "Created $AMEP_DIR/retriever.py"

# ----- Update __init__.py -----
python3 << 'PYEOF'
path = "src/optimus1/amep/__init__.py"
with open(path, "r") as f:
    src = f.read()

if "retrieve_for_task" in src:
    print("__init__.py already exports retriever, skipping")
else:
    src = src.rstrip() + '''

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
'''
    with open(path, "w") as f:
        f.write(src)
    print(f"Updated {path} to export retriever")
PYEOF

python -m py_compile "$AMEP_DIR"/retriever.py "$AMEP_DIR"/__init__.py && echo "Compile: OK"

# ----- Smoke test -----
echo ""
echo "=== Smoke test: end-to-end retrieval ==="
python3 << 'PYEOF'
from optimus1.amep import retrieve_for_task, render_success_examples, render_failure_warning

# Test 1: crafting table in forest — should return top-3 forest entries
print("--- Test 1: Craft a crafting table, env=forest ---")
result = retrieve_for_task(
    task="Craft a crafting table",
    environment="forest",
    initial_inventory={},
)
print(f"Successes: {len(result.successes)}")
for i, s in enumerate(result.successes):
    print(f"  [{i+1}] {s.short_summary()}")
print(f"Failure: {result.failure}")
print()

# Test 2: stone sword in plains — biome mismatch with the only entry
print("--- Test 2: Craft a stone sword, env=plains with grass ---")
result = retrieve_for_task(
    task="Craft a stone sword",
    environment="plains with grass",
    initial_inventory={},
)
print(f"Successes: {len(result.successes)}")
for s in result.successes:
    print(f"  {s.short_summary()}")
print()

# Test 3: task with no past data
print("--- Test 3: Craft a diamond pickaxe (no past data) ---")
result = retrieve_for_task(task="Craft a diamond pickaxe")
print(f"Has any: {result.has_any()}, successes: {len(result.successes)}")
print()

# Test 4: render the top result for the planner prompt
print("--- Test 4: rendered planner prompt for Craft a crafting table ---")
result = retrieve_for_task("Craft a crafting table", environment="forest")
print(render_success_examples(result.successes, limit=2))
PYEOF

echo ""
echo "Step 3 complete."
echo ""
echo "Next: review the smoke test output. We should see top-3 successes for"
echo "crafting table, biome-aware ranking for stone sword, and the rendered"
echo "prompt block ready for injection into the planner LLM."
