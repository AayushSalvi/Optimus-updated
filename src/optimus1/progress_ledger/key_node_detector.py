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
