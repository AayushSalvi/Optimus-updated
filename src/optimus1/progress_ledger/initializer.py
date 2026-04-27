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
