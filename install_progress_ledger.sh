#!/bin/bash
# install_progress_ledger.sh
# Creates the progress_ledger package in src/optimus1/progress_ledger/
# Run from ~/Optimus-1

set -e

PKG_DIR="src/optimus1/progress_ledger"
mkdir -p "$PKG_DIR"

# ============================================================
# __init__.py
# ============================================================
cat > "$PKG_DIR/__init__.py" << 'PYEOF'
"""Progress ledger for Minecraft agent — within-episode working memory.

Adapted from Wenyi's OSWorld progress_ledger. Same architecture; observation
primitive changed from a11y/URL diff to inventory + position + dimension + equipment.
"""
from .ledger import (
    Outcome,
    DoneEntry,
    FailedPath,
    InitialContext,
    ProgressLedger,
)
from .timeline import (
    KeyNode,
    StepRecord,
    TimelineEvent,
    OutcomeStateCache,
    append_step,
    close_current_event,
    event_outcome_for_decision,
    render_timeline_for_planner,
    render_outcome_view,
    OUTCOME_PENDING,
    OUTCOME_VERIFIED,
    OUTCOME_REVERTED,
    KN_OUTCOME_SATISFIED,
    KN_OUTCOME_INVALIDATED,
    KN_NAVIGATION,
    KN_DIALOG_OPENED,
    KN_DIALOG_CLOSED,
    KN_VALUE_COMMITTED,
    CONF_LOW,
    CONF_MEDIUM,
    CONF_HIGH,
    EV_ONGOING,
    EV_COMMITTED,
    EV_ABANDONED_REPLAN,
    EV_ENDED_DONE,
)
from .world_delta import WorldDelta, compute_world_delta
from .initializer import init_ledger
from .key_node_detector import detect_key_nodes
from .summarizer import update_ledger
PYEOF

# ============================================================
# timeline.py — deterministic core, no LLM
# ============================================================
cat > "$PKG_DIR/timeline.py" << 'PYEOF'
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
PYEOF

# ============================================================
# ledger.py
# ============================================================
cat > "$PKG_DIR/ledger.py" << 'PYEOF'
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
PYEOF

# ============================================================
# world_delta.py — Minecraft-specific deterministic diff
# ============================================================
cat > "$PKG_DIR/world_delta.py" << 'PYEOF'
"""Deterministic world-delta computation for Minecraft observations.

Replaces Wenyi's compute_window_delta (a11y/URL diff). Pure Python, no LLM.
Inputs are Optimus-1 status fields: inventory, location_stats, equipment.
"""
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional


@dataclass
class WorldDelta:
    inventory_added: Dict[str, int] = field(default_factory=dict)
    inventory_removed: Dict[str, int] = field(default_factory=dict)
    position_before: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    position_after: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    position_delta: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dimension_before: str = "overworld"
    dimension_after: str = "overworld"
    dimension_changed: bool = False
    equipped_before: str = "none"
    equipped_after: str = "none"
    equipment_changed: bool = False

    @property
    def is_empty(self) -> bool:
        return (
            not self.inventory_added
            and not self.inventory_removed
            and not self.dimension_changed
            and not self.equipment_changed
            and abs(self.position_delta[1]) < 0.5  # vertical movement matters most
            and (self.position_delta[0] ** 2 + self.position_delta[2] ** 2) < 4.0
        )

    def to_prompt_block(self) -> str:
        if self.is_empty:
            return "[World Delta]\n  (no significant change)"
        lines = ["[World Delta — computed from env observations, not interpretation]"]
        if self.inventory_added:
            adds = ", ".join(f"+{c} {k}" for k, c in self.inventory_added.items())
            lines.append(f"  inventory gained: {adds}")
        if self.inventory_removed:
            rems = ", ".join(f"-{c} {k}" for k, c in self.inventory_removed.items())
            lines.append(f"  inventory lost: {rems}")
        if self.dimension_changed:
            lines.append(f"  dimension: {self.dimension_before} → {self.dimension_after}")
        if self.equipment_changed:
            lines.append(f"  equipped: {self.equipped_before} → {self.equipped_after}")
        dx, dy, dz = self.position_delta
        if abs(dy) >= 0.5 or (dx ** 2 + dz ** 2) >= 4.0:
            lines.append(f"  position: {self.position_before} → {self.position_after} (Δ=({dx:+.1f},{dy:+.1f},{dz:+.1f}))")
        return "\n".join(lines)


def _to_xyz(loc) -> Tuple[float, float, float]:
    """Read x/y/z from a location_stats dict that may contain tensors."""
    if loc is None:
        return (0.0, 0.0, 0.0)
    def _v(k):
        v = loc.get(k, 0.0)
        try:
            return float(v.item())
        except AttributeError:
            return float(v)
    return (_v("xpos"), _v("ypos"), _v("zpos"))


def _inv_diff(before: Dict[str, int], after: Dict[str, int]) -> Tuple[Dict[str, int], Dict[str, int]]:
    added: Dict[str, int] = {}
    removed: Dict[str, int] = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        b = before.get(k, 0)
        a = after.get(k, 0)
        if a > b:
            added[k] = a - b
        elif b > a:
            removed[k] = b - a
    return added, removed


def compute_world_delta(
    *,
    inv_before: Dict[str, int],
    inv_after: Dict[str, int],
    loc_before: Optional[Dict] = None,
    loc_after: Optional[Dict] = None,
    dim_before: str = "overworld",
    dim_after: str = "overworld",
    equipped_before: str = "none",
    equipped_after: str = "none",
) -> WorldDelta:
    added, removed = _inv_diff(inv_before, inv_after)
    pb = _to_xyz(loc_before)
    pa = _to_xyz(loc_after)
    pd = (pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2])
    return WorldDelta(
        inventory_added=added,
        inventory_removed=removed,
        position_before=pb,
        position_after=pa,
        position_delta=pd,
        dimension_before=dim_before,
        dimension_after=dim_after,
        dimension_changed=(dim_before != dim_after),
        equipped_before=equipped_before,
        equipped_after=equipped_after,
        equipment_changed=(equipped_before != equipped_after),
    )
PYEOF

# ============================================================
# initializer.py — LLM call to seed the ledger
# ============================================================
cat > "$PKG_DIR/initializer.py" << 'PYEOF'
"""init_ledger — one LLM call at episode start to extract observable outcomes."""
import json
import logging
import re
from typing import Any, Callable, Dict, Optional

from .ledger import InitialContext, Outcome, ProgressLedger

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an outcome extractor for a Minecraft agent.

Given a task instruction and the agent's starting state, output 1-3 OBSERVABLE outcomes that must be true for the task to be complete. Each outcome must be checkable from inventory, position, dimension, or equipped item — NOT from things the agent did or intended.

Rules:
- Prefer ONE terminal outcome per task ("X is in inventory")
- Each outcome has an id (snake_case, ≤60 chars), description (≤240 chars), and evidence_hint (≤240 chars, concrete check)
- Evidence hints must reference observable state. Examples:
  - "inventory contains wooden_pickaxe (count >= 1)"
  - "inventory contains 3+ items matching *_log"
  - "inventory contains dirt (count >= 1) AND y_position decreased from start"
  - "current dimension == nether"
- Do NOT use config files, eval scripts, or anything not visible from the agent's observation
- Return ONLY valid JSON in this exact shape:

{
  "outcomes": [
    {"id": "...", "description": "...", "evidence_hint": "..."}
  ],
  "initial_context_summary": "..."
}
"""


def init_ledger(
    *,
    instruction: str,
    initial_inventory: Dict[str, int],
    initial_position: tuple,
    initial_dimension: str = "overworld",
    initial_equipped: str = "none",
    call_llm: Callable[..., str],
    model: Optional[str] = None,
) -> ProgressLedger:
    """Seed a ProgressLedger from the task instruction + starting observation.

    `call_llm` must be a callable taking (system_prompt, user_text, model) -> str.
    On any failure, returns an empty ledger with InitialContext populated. The
    rest of the agent can still run; the ledger just doesn't gate DONE.
    """
    ic = InitialContext(
        active_dimension=initial_dimension,
        starting_coords=initial_position,
        starting_inventory_summary=dict(initial_inventory),
        starting_equipped=initial_equipped,
    )

    user_text = (
        f"TASK: {instruction}\n\n"
        f"STARTING STATE:\n"
        f"  inventory: {dict(initial_inventory)}\n"
        f"  position: {initial_position}\n"
        f"  dimension: {initial_dimension}\n"
        f"  equipped: {initial_equipped}\n\n"
        f"Output the JSON only."
    )

    outcomes = []
    try:
        response_text = call_llm(_SYSTEM_PROMPT, user_text, model)
        parsed = _parse_seed_json(response_text)
        outcomes = _build_outcomes(parsed.get("outcomes", []))
    except Exception as e:
        logger.warning(f"[ProgressLedger.init] LLM call/parse failed: {e}; returning empty ledger")
        outcomes = []

    return ProgressLedger(initial_context=ic, required_outcomes=outcomes)


def _parse_seed_json(text: str) -> Dict[str, Any]:
    """Tolerant JSON extractor — strips markdown fences, finds outermost {...}."""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    start = t.find("{")
    if start < 0:
        return {}
    depth = 0
    for i, ch in enumerate(t[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start : i + 1])
                except Exception:
                    return {}
    return {}


def _build_outcomes(items) -> list:
    """Validate and normalize outcome list."""
    out = []
    seen_ids = set()
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        oid = str(item.get("id", "")).strip()
        desc = str(item.get("description", "")).strip()
        hint = str(item.get("evidence_hint", "")).strip()
        if not oid or not desc or not hint:
            continue
        oid = re.sub(r"[^a-zA-Z0-9_]+", "_", oid).strip("_").lower()[:60]
        if not oid or oid in seen_ids:
            continue
        seen_ids.add(oid)
        out.append(Outcome(id=oid, description=desc[:240], evidence_hint=hint[:240]))
    return out
PYEOF

# ============================================================
# key_node_detector.py — per-turn LLM call
# ============================================================
cat > "$PKG_DIR/key_node_detector.py" << 'PYEOF'
"""detect_key_nodes — per-turn LLM call. Outputs KeyNodes that drive the cache."""
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from .timeline import (
    KeyNode,
    KN_OUTCOME_SATISFIED, KN_OUTCOME_INVALIDATED, KN_NAVIGATION,
    KN_DIALOG_OPENED, KN_DIALOG_CLOSED, KN_VALUE_COMMITTED,
    CONF_LOW, CONF_MEDIUM, CONF_HIGH,
    OUTCOME_PENDING, OUTCOME_VERIFIED, OUTCOME_REVERTED,
)
from .world_delta import WorldDelta

logger = logging.getLogger(__name__)

_VALID_KINDS = {
    KN_OUTCOME_SATISFIED, KN_OUTCOME_INVALIDATED,
    KN_NAVIGATION, KN_DIALOG_OPENED, KN_DIALOG_CLOSED, KN_VALUE_COMMITTED,
}
_VALID_CONF = {CONF_LOW, CONF_MEDIUM, CONF_HIGH}


_SYSTEM_PROMPT = """You are a per-turn state-transition detector for a Minecraft agent.

Inputs you receive:
- The current outcomes table with each outcome's evidence_hint and current state
- A WorldDelta (deterministic diff): what changed in inventory, position, dimension, equipped
- The actor's last action summary

Your job: identify state TRANSITIONS that just happened. Output 0..N KeyNodes.

Output kinds:
- "outcome_satisfied": an outcome's evidence_hint is now true and was not before
- "outcome_invalidated": an outcome that was previously verified is no longer true (e.g., crafted item destroyed)
- "navigation": dimension or biome change
- "dialog_opened" / "dialog_closed": GUI opened/closed (crafting table, furnace, inventory)
- "value_committed": a discrete world change (block placed, item dropped) that's not an outcome

REASONING RULES:
- For each outcome, answer: hint_holds_now: YES|NO. Then verdict: pending+YES → SATISFIED, reverted+YES → SATISFIED, verified+NO → INVALIDATED, else NO_CHANGE
- Reason FROM the WorldDelta. Do not invent inventory items not in the delta.
- DO NOT fire outcome_satisfied if the item is only "visible on screen" — it must be in inventory per the delta
- Quote the specific delta line as evidence (e.g., "inventory gained: +2 oak_log")
- Confidence: high if delta directly proves it, medium if delta strongly implies, low otherwise (low nodes are dropped)

Output format — XML-tagged JSON:
<reasoning>
For outcome 'X': hint = "..."; current state = pending; hint_holds_now = YES (delta shows ...); verdict = SATISFIED.
</reasoning>
<patch>
{
  "key_nodes": [
    {"kind": "outcome_satisfied", "target": "wooden_pickaxe_in_inventory",
     "evidence": "inventory gained: +1 wooden_pickaxe", "confidence": "high"}
  ]
}
</patch>

If nothing changed, output an empty key_nodes list.
"""


def detect_key_nodes(
    *,
    step_idx: int,
    required_outcomes: List,
    current_outcome_states: Dict[str, str],
    world_delta: WorldDelta,
    actor_action_summary: str,
    call_llm: Callable[..., str],
    model: Optional[str] = None,
) -> List[KeyNode]:
    """Returns a list of KeyNode objects (already filtered for validity)."""
    if not required_outcomes:
        return []

    user_text = _build_user_text(
        required_outcomes, current_outcome_states, world_delta, actor_action_summary
    )

    try:
        response_text = call_llm(_SYSTEM_PROMPT, user_text, model)
    except Exception as e:
        logger.warning(f"[ProgressLedger.detect] LLM call failed: {e}")
        return []

    return _parse_response(response_text, current_outcome_states, step_idx)


def _build_user_text(required_outcomes, current_states, delta: WorldDelta, action_summary: str) -> str:
    lines = ["[Outcomes table]"]
    lines.append("  outcome_id | current_state | evidence_hint")
    lines.append("  -----------|---------------|--------------")
    for o in required_outcomes:
        st = current_states.get(o.id, OUTCOME_PENDING)
        lines.append(f"  {o.id} | {st} | {o.evidence_hint}")
    lines.append("")
    lines.append(delta.to_prompt_block())
    lines.append("")
    lines.append(f"[Last actor action]\n  {action_summary or '(none recorded)'}")
    lines.append("")
    lines.append("Now output <reasoning>...</reasoning><patch>{json}</patch>.")
    return "\n".join(lines)


def _parse_response(text: str, current_states: Dict[str, str], step_idx: int) -> List[KeyNode]:
    if not text:
        return []
    m = re.search(r"<patch>\s*(.+?)\s*</patch>", text, re.DOTALL)
    if not m:
        return []
    raw = m.group(1).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning(f"[ProgressLedger.detect] patch JSON parse failed: {e}; raw={raw[:200]!r}")
        return []

    nodes_raw = data.get("key_nodes", [])
    if not isinstance(nodes_raw, list):
        return []

    valid_targets = set(current_states.keys())
    out: List[KeyNode] = []
    for n in nodes_raw:
        if not isinstance(n, dict):
            continue
        kind = str(n.get("kind", "")).strip().lower()
        target = str(n.get("target", "")).strip()
        evidence = str(n.get("evidence", "")).strip()
        conf_raw = n.get("confidence", "low")
        if isinstance(conf_raw, (int, float)):
            conf = CONF_HIGH if conf_raw >= 0.75 else (CONF_MEDIUM if conf_raw >= 0.4 else CONF_LOW)
        else:
            conf = str(conf_raw).strip().lower()
        if kind not in _VALID_KINDS:
            continue
        if conf not in _VALID_CONF:
            continue
        if not evidence or not target:
            continue
        # outcome-targeted nodes must reference a real outcome id
        if kind in (KN_OUTCOME_SATISFIED, KN_OUTCOME_INVALIDATED):
            if target not in valid_targets:
                continue
            cs = current_states.get(target, OUTCOME_PENDING)
            if kind == KN_OUTCOME_SATISFIED and cs == OUTCOME_VERIFIED:
                continue  # already verified, skip dup
            if kind == KN_OUTCOME_INVALIDATED and cs != OUTCOME_VERIFIED:
                continue  # can't invalidate something not currently verified
        out.append(KeyNode(
            kind=kind, target=target[:120], evidence=evidence[:240],
            confidence=conf, detected_at_step=step_idx,
        ))
    return out
PYEOF

# ============================================================
# summarizer.py — every-N-turn dead-end-path summarizer
# ============================================================
cat > "$PKG_DIR/summarizer.py" << 'PYEOF'
"""update_ledger — periodic LLM call to detect strategy-level dead ends."""
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from .ledger import ProgressLedger

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a strategic-failure detector for a Minecraft agent.

You receive a window of recent agent activity. Your job is to identify whether any STRATEGIES (multi-step approaches, not single misclicks) have proven to be dead ends. Output failed_paths so the planner avoids retrying them.

Rules:
- Only output failed_path entries for genuine dead ends (>= 50 wasted env steps OR a recurring failed subgoal)
- Single-action failures, single misclicks, or partial progress are NOT failed paths
- Each failed_path has:
  - "path": short text describing the strategy attempted (≤200 chars)
  - "why": brief reason it failed (≤200 chars)
- DO NOT modify outcomes — that's the per-turn detector's job. Only output failed_paths.

Output:
<reasoning>
The agent attempted X over Y steps. Conclusion: dead end / not a dead end.
</reasoning>
<patch>
{"failed_add": [{"path": "...", "why": "..."}]}
</patch>

If no dead ends, output an empty failed_add list.
"""


def update_ledger(
    *,
    ledger: ProgressLedger,
    timeline_window: List,            # list of TimelineEvent
    recent_actions: List[str],
    step_idx: int,
    call_llm: Callable[..., str],
    model: Optional[str] = None,
) -> ProgressLedger:
    """Mutates ledger.failed_paths in place. Returns the same ledger."""
    if not timeline_window:
        return ledger

    user_text = _build_user_text(ledger, timeline_window, recent_actions)

    try:
        response_text = call_llm(_SYSTEM_PROMPT, user_text, model)
    except Exception as e:
        logger.warning(f"[ProgressLedger.summarize] LLM call failed: {e}")
        return ledger

    new_paths = _parse_failed_paths(response_text)
    for fp in new_paths:
        ledger.add_failed_path(path=fp["path"], why=fp["why"], step_idx=step_idx)
    return ledger


def _build_user_text(ledger: ProgressLedger, timeline_window, recent_actions) -> str:
    lines = ["[Current ledger]"]
    lines.append(ledger.to_prompt_block())
    lines.append("")
    lines.append("[Recent timeline events]")
    for ev in timeline_window[-8:]:
        lines.append(f"  event {ev.event_idx}: subgoal={ev.subgoal!r}, steps={ev.n_steps}, outcome={ev.outcome}")
    lines.append("")
    lines.append("[Recent actor actions]")
    for a in recent_actions[-12:]:
        lines.append(f"  - {a}")
    lines.append("")
    lines.append("Output <reasoning>...</reasoning><patch>{json}</patch>.")
    return "\n".join(lines)


def _parse_failed_paths(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    m = re.search(r"<patch>\s*(.+?)\s*</patch>", text, re.DOTALL)
    if not m:
        return []
    raw = m.group(1).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except Exception:
        return []
    items = data.get("failed_add", [])
    if not isinstance(items, list):
        return []
    out: List[Dict[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        path = str(it.get("path", "")).strip()
        why = str(it.get("why", "")).strip()
        if path and why:
            out.append({"path": path[:200], "why": why[:200]})
    return out
PYEOF

# ============================================================
# Done
# ============================================================
echo "Created $PKG_DIR with files:"
ls -la "$PKG_DIR"
echo ""
echo "Compile check:"
python -m py_compile "$PKG_DIR"/*.py && echo "All files compile OK"
