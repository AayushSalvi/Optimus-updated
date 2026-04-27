"""ProgressLedger — task state container. Read-only from the planner's perspective."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .timeline import (
    OutcomeStateCache, KeyNode, StepRecord,
    KN_OUTCOME_SATISFIED, OUTCOME_VERIFIED,
    CONF_HIGH, render_outcome_view,
)


@dataclass
class Outcome:
    id: str
    description: str
    evidence_hint: str


@dataclass
class DoneEntry:
    """Append-only log of outcome verifications. Legacy/replay; cache is source of truth."""
    outcome_id: str
    verified_at_step: int
    evidence: str = ""


@dataclass
class FailedPath:
    path: str       # e.g., "chop_tree → no tree found in 600 steps"
    why: str        # why it failed
    first_observed_at_step: int


@dataclass
class InitialContext:
    """Captured once at episode start. Minecraft-specific fields."""
    active_dimension: str = "overworld"
    starting_coords: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    starting_inventory_summary: dict = field(default_factory=dict)
    starting_equipped: str = "none"


@dataclass
class ProgressLedger:
    initial_context: InitialContext = field(default_factory=InitialContext)
    required_outcomes: List[Outcome] = field(default_factory=list)
    done: List[DoneEntry] = field(default_factory=list)
    failed_paths: List[FailedPath] = field(default_factory=list)
    outcome_cache: Optional[OutcomeStateCache] = None

    def __post_init__(self):
        if self.outcome_cache is None:
            self.outcome_cache = OutcomeStateCache([o.id for o in self.required_outcomes])

    # ---------- views ----------
    def all_done(self) -> bool:
        return self.outcome_cache.all_verified()

    def can_accept_done_claim(self) -> Tuple[bool, str]:
        return self.outcome_cache.can_accept_done_claim()

    def pending(self) -> List[str]:
        return [o.id for o in self.required_outcomes
                if self.outcome_cache.get_state(o.id) != OUTCOME_VERIFIED]

    # ---------- writes ----------
    def apply_step_keynodes(self, step: StepRecord):
        prev_states = {o.id: self.outcome_cache.get_state(o.id) for o in self.required_outcomes}
        self.outcome_cache.apply_step(step, [o.id for o in self.required_outcomes])
        for o in self.required_outcomes:
            new_state = self.outcome_cache.get_state(o.id)
            if prev_states[o.id] != OUTCOME_VERIFIED and new_state == OUTCOME_VERIFIED:
                ev = ""
                for kn in step.key_nodes:
                    if kn.kind == KN_OUTCOME_SATISFIED and kn.target == o.id:
                        ev = kn.evidence
                        break
                self.done.append(DoneEntry(outcome_id=o.id, verified_at_step=step.step_idx, evidence=ev))

    def add_failed_path(self, path: str, why: str, step_idx: int) -> bool:
        norm = path.strip().lower()
        if not norm:
            return False
        for fp in self.failed_paths:
            if fp.path.strip().lower() == norm:
                return False
        self.failed_paths.append(FailedPath(path=path, why=why, first_observed_at_step=step_idx))
        return True

    # ---------- prompt rendering ----------
    def to_prompt_block(self) -> str:
        lines = []
        ic = self.initial_context
        ic_lines = ["[Initial context]"]
        ic_lines.append(f"  • dimension: {ic.active_dimension}")
        ic_lines.append(f"  • starting coords: {ic.starting_coords}")
        if ic.starting_inventory_summary:
            inv_str = ", ".join(f"{k}×{v}" for k, v in list(ic.starting_inventory_summary.items())[:8])
            ic_lines.append(f"  • starting inventory: {inv_str}")
        if ic.starting_equipped and ic.starting_equipped != "none":
            ic_lines.append(f"  • starting equipped: {ic.starting_equipped}")
        lines.append("\n".join(ic_lines))
        lines.append("")
        lines.append(render_outcome_view(self.outcome_cache, self.required_outcomes, self.failed_paths))
        return "\n".join(lines)
