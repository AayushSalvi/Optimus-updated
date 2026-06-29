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
