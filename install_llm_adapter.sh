#!/bin/bash
# install_llm_adapter.sh
# Adds llm_client.py to progress_ledger/ and creates a smoke test.
# Run from ~/Optimus-1

set -e

PKG_DIR="src/optimus1/progress_ledger"

if [ ! -d "$PKG_DIR" ]; then
  echo "ERROR: $PKG_DIR does not exist. Run install_progress_ledger.sh first."
  exit 1
fi

# ============================================================
# llm_client.py — adapter that wraps vLLM/OpenAI client for our 3 modules
# ============================================================
cat > "$PKG_DIR/llm_client.py" << 'PYEOF'
"""LLM client adapter.

Wraps the existing vLLM/OpenAI client (same one used by gpt4_planning.py) into a
simple callable that initializer.py / key_node_detector.py / summarizer.py can use.

Usage:
    call_llm = make_call_llm()   # returns a callable
    response = call_llm(system_prompt, user_text)   # returns str
"""
import logging
from typing import Optional

import openai

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_BASE_URL = "http://localhost:8000/v1"

# Single shared client (same pattern as gpt4_planning.py)
_client = openai.OpenAI(
    api_key="not-needed",
    base_url=DEFAULT_BASE_URL,
    timeout=120,
    max_retries=2,
)


def make_call_llm(model: str = DEFAULT_MODEL, max_tokens: int = 1200, temperature: float = 0.0):
    """Returns a callable: (system_prompt, user_text, model_override=None) -> str.

    The 3 progress_ledger LLM modules accept this callable as a dependency,
    so they don't import openai directly.
    """
    def call_llm(system_prompt: str, user_text: str, model_override: Optional[str] = None) -> str:
        model_to_use = model_override or model
        try:
            response = _client.chat.completions.create(
                model=model_to_use,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content or ""
            return content
        except Exception as e:
            logger.warning(f"[ProgressLedger.llm] call failed: {type(e).__name__}: {e}")
            raise
    return call_llm


def health_check() -> bool:
    """Quick check that vLLM is reachable. Returns True on success."""
    try:
        call = make_call_llm(max_tokens=20)
        out = call("You answer in one word.", "Say OK.")
        logger.info(f"[ProgressLedger.llm] health check response: {out!r}")
        return bool(out)
    except Exception as e:
        logger.warning(f"[ProgressLedger.llm] health check failed: {e}")
        return False
PYEOF

echo "Created $PKG_DIR/llm_client.py"

# ============================================================
# Update __init__.py to also export llm_client helpers
# ============================================================
if ! grep -q "llm_client" "$PKG_DIR/__init__.py"; then
  cat >> "$PKG_DIR/__init__.py" << 'PYEOF'
from .llm_client import make_call_llm, health_check
PYEOF
  echo "Appended llm_client exports to __init__.py"
fi

# Compile check
python -m py_compile "$PKG_DIR"/*.py && echo "All files compile OK"

# ============================================================
# Day 2 smoke test — exercises all three LLM calls end-to-end
# ============================================================
cat > /tmp/test_progress_ledger_llm.py << 'PYEOF'
"""Smoke test for progress_ledger LLM calls.

Tests the full chain: init_ledger -> detect_key_nodes -> update_ledger.
Uses synthetic Minecraft observations (no MineRL needed).

Run from ~/Optimus-1:
    python3 /tmp/test_progress_ledger_llm.py
"""
import logging
import sys

sys.path.insert(0, "src")

from optimus1.progress_ledger import (
    make_call_llm, health_check,
    init_ledger, detect_key_nodes, update_ledger,
    compute_world_delta,
    StepRecord, append_step, close_current_event, event_outcome_for_decision,
    OUTCOME_VERIFIED,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ---------- 0. Health check ----------
print("=" * 60)
print("0. vLLM health check")
print("=" * 60)
if not health_check():
    print("ERROR: vLLM not responding. Make sure it's running on localhost:8000.")
    sys.exit(1)
print("vLLM responding.\n")

call_llm = make_call_llm()

# ---------- 1. init_ledger ----------
print("=" * 60)
print("1. init_ledger — extract outcomes from task instruction")
print("=" * 60)
ledger = init_ledger(
    instruction="Craft a wooden pickaxe",
    initial_inventory={},
    initial_position=(0.0, 64.0, 0.0),
    initial_dimension="overworld",
    initial_equipped="none",
    call_llm=call_llm,
)
print(f"\nNumber of outcomes: {len(ledger.required_outcomes)}")
for o in ledger.required_outcomes:
    print(f"  - id: {o.id}")
    print(f"    description: {o.description}")
    print(f"    evidence_hint: {o.evidence_hint}")
print()
print("Initial ledger prompt block:")
print(ledger.to_prompt_block())
print()

if not ledger.required_outcomes:
    print("WARNING: init_ledger produced 0 outcomes. The LLM response may have been malformed.")
    print("Continuing test, but expect detect_key_nodes to be a no-op.")

# ---------- 2. detect_key_nodes — simulate gaining a wooden pickaxe ----------
print("=" * 60)
print("2. detect_key_nodes — simulate inventory change after a craft")
print("=" * 60)

delta = compute_world_delta(
    inv_before={"oak_planks": 3, "stick": 2, "crafting_table": 1},
    inv_after={"crafting_table": 1, "wooden_pickaxe": 1},
)
print("World delta:")
print(delta.to_prompt_block())
print()

current_states = {o.id: ledger.outcome_cache.get_state(o.id) for o in ledger.required_outcomes}
print(f"Current outcome states before detection: {current_states}")
print()

key_nodes = detect_key_nodes(
    step_idx=42,
    required_outcomes=ledger.required_outcomes,
    current_outcome_states=current_states,
    world_delta=delta,
    actor_action_summary="Crafted wooden_pickaxe at crafting_table",
    call_llm=call_llm,
)
print(f"Number of key nodes detected: {len(key_nodes)}")
for kn in key_nodes:
    print(f"  - kind: {kn.kind}, target: {kn.target}, conf: {kn.confidence}")
    print(f"    evidence: {kn.evidence}")
print()

# Apply the key nodes to the ledger via a synthetic StepRecord
step = StepRecord(
    step_idx=42,
    inventory={"crafting_table": 1, "wooden_pickaxe": 1},
    position=(0.0, 64.0, 0.0),
    actor_action_summary="Crafted wooden_pickaxe",
    key_nodes=key_nodes,
)
ledger.apply_step_keynodes(step)

print("Outcome states AFTER applying key nodes:")
for o in ledger.required_outcomes:
    print(f"  {o.id}: {ledger.outcome_cache.get_state(o.id)}")
print()
print(f"all_done(): {ledger.all_done()}")
print(f"can_accept_done_claim(): {ledger.can_accept_done_claim()}")
print()

# ---------- 3. summarizer — synthetic dead-end timeline ----------
print("=" * 60)
print("3. update_ledger — synthetic dead-end strategy")
print("=" * 60)

# Build a fake timeline showing 60 steps of failed tree-chopping
timeline = []
fake_step = StepRecord(step_idx=0, actor_action_summary="chop_tree skill")
append_step(timeline, fake_step, current_subgoal="chop tree")
for i in range(1, 61):
    fake_step = StepRecord(step_idx=i, actor_action_summary="chop_tree skill (still no log)")
    append_step(timeline, fake_step, current_subgoal="chop tree")
close_current_event(timeline, outcome="abandoned_replan", at_step=60)

print(f"Timeline has {len(timeline)} event(s); first event has {timeline[0].n_steps} steps.")
print()

ledger = update_ledger(
    ledger=ledger,
    timeline_window=timeline,
    recent_actions=["chop_tree skill"] * 12,
    step_idx=60,
    call_llm=call_llm,
)

print(f"Failed paths after summarizer: {len(ledger.failed_paths)}")
for fp in ledger.failed_paths:
    print(f"  - path: {fp.path}")
    print(f"    why: {fp.why}")
print()
print("Final ledger prompt block:")
print(ledger.to_prompt_block())
print()

print("=" * 60)
print("Smoke test complete.")
print("=" * 60)
PYEOF

echo ""
echo "Smoke test written to /tmp/test_progress_ledger_llm.py"
echo ""
echo "Run it (with vLLM serving on localhost:8000):"
echo "  python3 /tmp/test_progress_ledger_llm.py"
