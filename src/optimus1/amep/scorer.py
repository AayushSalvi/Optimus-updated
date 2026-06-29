"""AMEP scorer — pluggable similarity scoring.

Given a query context (current task's biome, inventory, etc.) and a past
TrajectoryRecord, returns a similarity score in [0.0, 1.0].

Two implementations share one interface:
  RuleScorer       — deterministic, no LLM, no dependencies
  EmbeddingScorer  — vector-similarity over text embeddings (Step 6)

The retriever calls score(query, record) for each candidate and ranks.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .store import TrajectoryRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query: what the retriever knows about the current run
# ---------------------------------------------------------------------------
@dataclass
class RetrievalQuery:
    """Context about the current task being planned.

    All fields optional — scorer must gracefully handle missing data, since
    early in a run we may not yet have a populated inventory or biome.
    """
    task: str = ""                                 # human-readable task instruction
    environment: str = ""                          # biome / visual description from initial obs
    initial_inventory: Dict[str, int] = field(default_factory=dict)
    dimension: str = "overworld"

    def normalized_task(self) -> str:
        return re.sub(r"[^a-z0-9_]", "_", self.task.lower().replace(" ", "_"))


# ---------------------------------------------------------------------------
# Scorer interface
# ---------------------------------------------------------------------------
class Scorer(ABC):
    """Abstract scorer interface.

    Implementations score a single (query, candidate) pair. Retriever loops
    over candidates and sorts by score.
    """

    @abstractmethod
    def score(self, query: RetrievalQuery, record: TrajectoryRecord) -> float:
        """Return a similarity score in [0.0, 1.0]. Higher = more similar."""
        ...

    def name(self) -> str:
        return self.__class__.__name__


# ---------------------------------------------------------------------------
# Rule-based scorer
# ---------------------------------------------------------------------------
class RuleScorer(Scorer):
    """Deterministic similarity using simple rules.

    Components (weighted):
      - Task exact-match: 0.50  (already filtered by store, here we just confirm)
      - Environment overlap: 0.20  (substring match on biome words)
      - Initial inventory similarity: 0.15  (Jaccard over item-name sets)
      - Step-count preference: 0.15  (lower steps = better, monotonic)

    Step count is part of the score (not a hard tiebreaker) so a slightly-worse
    biome match with much faster steps still wins.
    """

    # Tunable weights — sum to 1.0
    W_TASK = 0.50
    W_ENV = 0.20
    W_INV = 0.15
    W_STEPS = 0.15

    # Step normalization — past runs over this many steps score 0 on the steps axis
    STEPS_NORM = 5000

    def __init__(self):
        pass

    # ----- task -----
    def _task_score(self, query: RetrievalQuery, record: TrajectoryRecord) -> float:
        q = query.normalized_task()
        r = record.task_key.replace(" ", "_").lower()
        if not q or not r:
            return 0.0
        if q == r:
            return 1.0
        # Loose containment fallback (handles "craft_a_stone_sword" vs "stone_sword")
        if q in r or r in q:
            return 0.7
        return 0.0

    # ----- environment -----
    @staticmethod
    def _tokenize_env(env: str) -> Set[str]:
        """Extract meaningful biome words from an env string.

        Examples:
            'forest'                       -> {'forest'}
            'forest with hills and ocean'  -> {'forest', 'hills', 'ocean'}
            'plains with grass'            -> {'plains', 'grass'}
        """
        if not env:
            return set()
        # Strip filler words; keep biome / terrain nouns
        STOPWORDS = {"with", "and", "or", "a", "the", "of", "in", "on", "by", "near", "nearby"}
        words = re.findall(r"[a-z]+", env.lower())
        return {w for w in words if w and w not in STOPWORDS}

    def _env_score(self, query: RetrievalQuery, record: TrajectoryRecord) -> float:
        q_words = self._tokenize_env(query.environment)
        r_words = self._tokenize_env(record.environment)
        if not q_words and not r_words:
            return 0.5  # both unknown — neutral
        if not q_words or not r_words:
            return 0.3  # one side unknown — modest similarity
        # Jaccard
        intersect = q_words & r_words
        union = q_words | r_words
        if not union:
            return 0.0
        return len(intersect) / len(union)

    # ----- inventory -----
    @staticmethod
    def _inv_items(inv: Dict[str, int]) -> Set[str]:
        """Set of item names with positive quantities."""
        if not inv:
            return set()
        return {k for k, v in inv.items() if isinstance(v, int) and v > 0}

    def _inv_score(self, query: RetrievalQuery, record: TrajectoryRecord) -> float:
        q_items = self._inv_items(query.initial_inventory)
        # Try to pull initial inventory from the record's initial_context, else empty
        r_inv = (record.initial_context or {}).get("initial_inventory", {}) or {}
        r_items = self._inv_items(r_inv if isinstance(r_inv, dict) else {})
        if not q_items and not r_items:
            return 1.0  # both empty — perfect match for fresh-spawn tasks
        if not q_items or not r_items:
            return 0.5  # one side unknown — neutral
        intersect = q_items & r_items
        union = q_items | r_items
        return len(intersect) / len(union)

    # ----- steps -----
    def _steps_score(self, record: TrajectoryRecord) -> float:
        """Fewer steps = higher score, normalized to [0,1].

        Records with no step count fall back to 0 (no preference).
        """
        if not isinstance(record.steps, int) or record.steps <= 0:
            return 0.0
        # Linear decay: 0 steps -> 1.0; STEPS_NORM steps -> 0.0
        s = max(0.0, 1.0 - (record.steps / float(self.STEPS_NORM)))
        return s

    # ----- combine -----
    def score(self, query: RetrievalQuery, record: TrajectoryRecord) -> float:
        s_task = self._task_score(query, record)
        s_env = self._env_score(query, record)
        s_inv = self._inv_score(query, record)
        s_steps = self._steps_score(record)
        total = (
            self.W_TASK * s_task
            + self.W_ENV * s_env
            + self.W_INV * s_inv
            + self.W_STEPS * s_steps
        )
        return total


# ---------------------------------------------------------------------------
# Embedding scorer (stub — real implementation in Step 6)
# ---------------------------------------------------------------------------
class EmbeddingScorer(Scorer):
    """Embedding-based scorer. Not implemented yet.

    Will use an OpenAI-compatible embedding endpoint (via the same llm_config
    provider as the planner) to embed (task + env + inventory) at retrieval
    time, compare against cached embeddings of past records by cosine similarity.

    Stubbed for now so the retriever can be wired against this interface.
    """

    def __init__(self):
        raise NotImplementedError(
            "EmbeddingScorer is a Phase-2 component. Implementation comes in Step 6."
        )

    def score(self, query: RetrievalQuery, record: TrajectoryRecord) -> float:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_SCORER_REGISTRY = {
    "rule": RuleScorer,
    "embedding": EmbeddingScorer,
}


def make_scorer(kind: str = "rule") -> Scorer:
    """Return a scorer by name.

    Args:
        kind: 'rule' (default) or 'embedding' (Phase 2).
    """
    if kind not in _SCORER_REGISTRY:
        raise ValueError(f"Unknown scorer kind: {kind!r}. Available: {list(_SCORER_REGISTRY)}")
    return _SCORER_REGISTRY[kind]()
