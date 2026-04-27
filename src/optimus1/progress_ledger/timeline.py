"""Timeline + outcome state cache + renderers. Pure deterministic Python, no LLM."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------- constants ----------
OUTCOME_PENDING = "pending"
OUTCOME_VERIFIED = "verified"
OUTCOME_REVERTED = "reverted"

KN_OUTCOME_SATISFIED = "outcome_satisfied"
KN_OUTCOME_INVALIDATED = "outcome_invalidated"
KN_NAVIGATION = "navigation"
KN_DIALOG_OPENED = "dialog_opened"
KN_DIALOG_CLOSED = "dialog_closed"
KN_VALUE_COMMITTED = "value_committed"

CONF_LOW = "low"
CONF_MEDIUM = "medium"
CONF_HIGH = "high"

EV_ONGOING = "ongoing"
EV_COMMITTED = "committed"
EV_ABANDONED_REPLAN = "abandoned_replan"
EV_ENDED_DONE = "ended_done"

MAX_REVERT_COUNT = 3


@dataclass
class KeyNode:
    """One observed state transition with quoted evidence."""
    kind: str
    target: str           # outcome_id or freeform string for non-outcome kinds
    evidence: str         # quoted text from world delta or observation
    confidence: str       # CONF_LOW / MEDIUM / HIGH
    detected_at_step: int

    def enters_derivation(self) -> bool:
        return self.confidence in (CONF_MEDIUM, CONF_HIGH)


@dataclass
class StepRecord:
    """One planner turn — observation + decision + detected key nodes."""
    step_idx: int
    inventory: Dict[str, int] = field(default_factory=dict)
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dimension: str = "overworld"
    equipped: str = "none"
    actor_action_summary: str = ""
    planner_decision: str = ""           # CONTINUE / REPLAN / DONE
    planner_done_assessment: str = ""    # YES / NO / ""
    key_nodes: List[KeyNode] = field(default_factory=list)


@dataclass
class TimelineEvent:
    """A span of consecutive steps sharing a subgoal."""
    event_idx: int
    subgoal: str
    started_at_step: int
    ended_at_step: Optional[int] = None
    steps: List[StepRecord] = field(default_factory=list)
    outcome: str = EV_ONGOING

    @property
    def n_steps(self) -> int:
        return len(self.steps)

    @property
    def all_key_nodes(self) -> List[KeyNode]:
        out = []
        for s in self.steps:
            out.extend(s.key_nodes)
        return out


class OutcomeStateCache:
    """State machine over outcomes. Updated only via apply_step, which folds in KeyNodes."""

    def __init__(self, outcome_ids: List[str]):
        self.states: Dict[str, str] = {oid: OUTCOME_PENDING for oid in outcome_ids}
        self.last_satisfy_step: Dict[str, int] = {}
        self.last_invalidate_step: Dict[str, int] = {}
        self.revert_count: Dict[str, int] = {oid: 0 for oid in outcome_ids}
        self.evidence: Dict[str, str] = {}

    def get_state(self, oid: str) -> str:
        return self.states.get(oid, OUTCOME_PENDING)

    def all_verified(self) -> bool:
        return all(s == OUTCOME_VERIFIED for s in self.states.values())

    def can_accept_done_claim(self) -> Tuple[bool, str]:
        pending = [oid for oid, s in self.states.items() if s != OUTCOME_VERIFIED]
        if not pending:
            return True, ""
        return False, f"outcomes not verified: {pending}"

    def apply_step(self, step: StepRecord, outcome_ids: List[str]):
        oid_set = set(outcome_ids)
        for kn in step.key_nodes:
            if not kn.enters_derivation():
                continue
            if kn.target not in oid_set:
                continue
            if kn.kind == KN_OUTCOME_SATISFIED:
                # idempotent flip pending/reverted -> verified
                self.states[kn.target] = OUTCOME_VERIFIED
                self.last_satisfy_step[kn.target] = step.step_idx
                self.evidence[kn.target] = kn.evidence
            elif kn.kind == KN_OUTCOME_INVALIDATED:
                # only flip verified -> reverted
                if self.states.get(kn.target) != OUTCOME_VERIFIED:
                    continue
                last_sat = self.last_satisfy_step.get(kn.target, -1)
                if step.step_idx <= last_sat:
                    continue
                if self.revert_count.get(kn.target, 0) >= MAX_REVERT_COUNT:
                    continue
                self.states[kn.target] = OUTCOME_REVERTED
                self.last_invalidate_step[kn.target] = step.step_idx
                self.revert_count[kn.target] = self.revert_count.get(kn.target, 0) + 1


# ---------- timeline event helpers ----------

def append_step(timeline: List[TimelineEvent], step: StepRecord, current_subgoal: str) -> TimelineEvent:
    """Append step to last open event if subgoal matches; else open a new event."""
    last = timeline[-1] if timeline else None
    if (last is None) or (last.outcome != EV_ONGOING) or (last.subgoal.strip().lower() != current_subgoal.strip().lower()):
        new_event = TimelineEvent(
            event_idx=(len(timeline)),
            subgoal=current_subgoal,
            started_at_step=step.step_idx,
            steps=[step],
            outcome=EV_ONGOING,
        )
        timeline.append(new_event)
        return new_event
    last.steps.append(step)
    return last


def close_current_event(timeline: List[TimelineEvent], outcome: str, at_step: int):
    if not timeline:
        return
    last = timeline[-1]
    if last.outcome != EV_ONGOING:
        return
    last.outcome = outcome
    last.ended_at_step = at_step


def event_outcome_for_decision(decision: str, done_assessment: str) -> str:
    """Map planner (decision, done_assessment) tuple to event outcome label."""
    decision = (decision or "").strip().upper()
    done = (done_assessment or "").strip().upper()
    if decision == "DONE":
        return EV_ENDED_DONE
    if done == "YES":
        return EV_COMMITTED
    if decision == "REPLAN":
        return EV_ABANDONED_REPLAN
    return EV_ONGOING


# ---------- renderers ----------

def render_outcome_view(cache: OutcomeStateCache, required_outcomes: List, failed_paths: List) -> str:
    """Structured-text block of outcomes + dead-end paths for the planner prompt."""
    lines = ["[Required Outcomes — derived from observed evidence]"]
    n_verified = 0
    n_reverted = 0
    n_pending = 0
    for o in required_outcomes:
        state = cache.get_state(o.id)
        ev = cache.evidence.get(o.id, "")
        sat_step = cache.last_satisfy_step.get(o.id)
        if state == OUTCOME_VERIFIED:
            n_verified += 1
            tag = f"[verified] {o.id}"
            extra = f" — verified at step {sat_step}" if sat_step is not None else ""
            ev_line = f"\n    evidence: {ev[:200]}" if ev else ""
            lines.append(f"  {tag}{extra}{ev_line}")
        elif state == OUTCOME_REVERTED:
            n_reverted += 1
            inv_step = cache.last_invalidate_step.get(o.id)
            tag = f"[REVERTED] {o.id}"
            extra = f" — verified step {sat_step}, INVALIDATED step {inv_step} ← MUST RE-DO"
            lines.append(f"  {tag}{extra}")
        else:
            n_pending += 1
            tag = f"[pending]  {o.id}"
            hint_line = f"\n    hint: {o.evidence_hint}" if o.evidence_hint else ""
            lines.append(f"  {tag}{hint_line}")

    n_failed = len(failed_paths)
    summary = f"Summary: {n_verified}/{len(required_outcomes)} verified"
    if n_reverted:
        summary += f"; {n_reverted} REVERTED"
    summary += f"; {n_pending} pending"
    if n_failed:
        summary += f"; {n_failed} dead-end strategies known"
    lines.append(summary)

    if failed_paths:
        lines.append("")
        lines.append(f"⚠  DEAD-END PATHS ALREADY TRIED ({n_failed}) — DO NOT REPEAT:")
        for i, fp in enumerate(failed_paths, 1):
            lines.append(f"  ⚠ {i}. Attempted: \"{fp.path}\"")
            if fp.why:
                lines.append(f"        Outcome:   \"{fp.why}\"")
    return "\n".join(lines)


def render_timeline_for_planner(timeline: List[TimelineEvent], n_recent_events: int = 8) -> str:
    """Compact ASCII summary of recent events for the planner prompt."""
    if not timeline:
        return "[Task Event Timeline]\n  (no events yet)"
    recent = timeline[-n_recent_events:]
    lines = ["[Task Event Timeline] (recent events)"]
    lines.append("  idx | subgoal                    | steps | outcome           | key nodes")
    lines.append("  ----|----------------------------|-------|-------------------|----------")
    for ev in recent:
        kn_summary = _summarize_event_keynodes(ev)
        sg = (ev.subgoal[:26] + "…") if len(ev.subgoal) > 27 else ev.subgoal.ljust(27)
        lines.append(f"  {ev.event_idx:3d} | {sg} | {ev.n_steps:5d} | {ev.outcome:17s} | {kn_summary}")
    return "\n".join(lines)


def _summarize_event_keynodes(event: TimelineEvent) -> str:
    if not event.steps:
        return "—"
    counts = {}
    for kn in event.all_key_nodes:
        counts[kn.kind] = counts.get(kn.kind, 0) + 1
    if not counts:
        return "—"
    parts = []
    for kind in [KN_OUTCOME_SATISFIED, KN_OUTCOME_INVALIDATED, KN_NAVIGATION,
                 KN_DIALOG_OPENED, KN_DIALOG_CLOSED, KN_VALUE_COMMITTED]:
        if kind in counts:
            parts.append(f"{kind}×{counts[kind]}")
    return ", ".join(parts) if parts else "—"
