#!/bin/bash
# install_ledger_integration_v2.sh
# Safer ledger integration patcher.
# - Patches in memory, validates with py_compile, only writes if valid.
# - Uses regex with whitespace tolerance.
# - Refuses to patch if file already has ledger markers (use --force to override).
#
# Run from ~/Optimus-1.

set -e
cd ~/Optimus-1

MAIN_PY="src/optimus1/main.py"
BACKUP="src/optimus1/main.py.bak_v2_ledger"

# Pre-flight: ensure main.py compiles before we start
python -m py_compile "$MAIN_PY" 2>&1 || { echo "ERROR: $MAIN_PY does not compile before patching"; exit 1; }

# Pre-flight: refuse if already patched
if grep -q "_ledger_init\|\[LEDGER\]" "$MAIN_PY"; then
  echo "ERROR: $MAIN_PY already contains ledger markers. Run:"
  echo "  git checkout $MAIN_PY"
  echo "before re-running this script."
  exit 1
fi

# Backup
cp "$MAIN_PY" "$BACKUP"
echo "Backup: $BACKUP"

# Run patcher in Python — patch in memory, validate via compile(), then write
python3 << 'PYEOF'
import re
import sys
import tempfile
import os

PATH = "src/optimus1/main.py"
with open(PATH, "r") as f:
    src = f.read()

original_src = src
patches_applied = []
patches_failed = []


def patch(name, pattern, replacement, count=1):
    """Apply regex patch to src. Records success/failure."""
    global src
    new_src, n = re.subn(pattern, replacement, src, count=count, flags=re.MULTILINE)
    if n == count:
        src = new_src
        patches_applied.append(name)
    else:
        patches_failed.append(f"{name} (matched {n}, expected {count})")


# ---------------------------------------------------------------------
# A. Add ledger imports at top, after the LAST top-level import line
#    Strategy: find the last `^(from|import) ...$` line that's NOT continuation
#    of a parenthesized import. Insert AFTER the line just before the first
#    non-import code.
# ---------------------------------------------------------------------
imports_block = """
# === Progress Ledger imports ===
from optimus1.progress_ledger import (
    init_ledger as _ledger_init,
    detect_key_nodes as _ledger_detect,
    compute_world_delta as _ledger_compute_delta,
    StepRecord as _LedgerStepRecord,
    make_call_llm as _ledger_make_call_llm,
)
_LEDGER_CALL_LLM = None
def _ledger_get_call_llm():
    global _LEDGER_CALL_LLM
    if _LEDGER_CALL_LLM is None:
        _LEDGER_CALL_LLM = _ledger_make_call_llm()
    return _LEDGER_CALL_LLM
# === End Progress Ledger imports ===
"""

# Find the start of `def agent_do(` — insert imports just before it.
# This guarantees we are past all imports without parsing them.
m = re.search(r"^def agent_do\(", src, flags=re.MULTILINE)
if m:
    insert_pos = m.start()
    src = src[:insert_pos] + imports_block + "\n\n" + src[insert_pos:]
    patches_applied.append("A. Imports block inserted before agent_do")
else:
    patches_failed.append("A. could not find 'def agent_do(' to anchor imports")

# ---------------------------------------------------------------------
# B. Modify agent_do signature to accept ledger=None
# ---------------------------------------------------------------------
patch(
    "B. agent_do signature",
    r"(def agent_do\(\s*\n(?:\s*[^)]+,\s*\n)*?\s*memory_bank: Memory,\s*\n)(\):)",
    r"\1    ledger=None,\n\2",
)

# ---------------------------------------------------------------------
# C. Snapshot inventory at top of `while current_plan is not None:` loop
# ---------------------------------------------------------------------
snapshot_block = """\\g<0>
            # [LEDGER] snapshot inventory + position before this sub-task
            _ledger_pre_inv = dict(env.status.inventory) if (ledger is not None and hasattr(env, "status")) else {}
            _ledger_pre_loc = dict(env.status.location_stats) if (ledger is not None and hasattr(env, "status")) else {}
            _ledger_pre_equip = env.status.equipment if (ledger is not None and hasattr(env, "status")) else "none"
"""
patch(
    "C. pre-task inventory snapshot",
    r"^        while current_plan is not None:\s*$",
    snapshot_block,
)

# ---------------------------------------------------------------------
# D. Post-craft ledger update — after `progress += 1; pbar.update(all_task, advance=1)`
# in the craft branch (the one with `logger.info(f"[green]{task} Success[/green]!")`)
# ---------------------------------------------------------------------
post_craft_inject = """\\g<0>
                    # [LEDGER] update ledger on craft/smelt/equip success
                    if ledger is not None:
                        try:
                            _post_inv = dict(env.status.inventory)
                            _post_loc = dict(env.status.location_stats)
                            _post_equip = env.status.equipment
                            _delta = _ledger_compute_delta(
                                inv_before=_ledger_pre_inv,
                                inv_after=_post_inv,
                                loc_before=_ledger_pre_loc,
                                loc_after=_post_loc,
                                equipped_before=_ledger_pre_equip,
                                equipped_after=_post_equip,
                            )
                            _states = {o.id: ledger.outcome_cache.get_state(o.id) for o in ledger.required_outcomes}
                            _kns = _ledger_detect(
                                step_idx=env.num_steps,
                                required_outcomes=ledger.required_outcomes,
                                current_outcome_states=_states,
                                world_delta=_delta,
                                actor_action_summary=f"completed sub-task: {task}",
                                call_llm=_ledger_get_call_llm(),
                            )
                            _step_rec = _LedgerStepRecord(
                                step_idx=env.num_steps,
                                inventory=_post_inv,
                                actor_action_summary=f"completed sub-task: {task}",
                                key_nodes=_kns,
                            )
                            ledger.apply_step_keynodes(_step_rec)
                            logger.info(f"[cyan][LEDGER] After {task!r}: pending={ledger.pending()}, all_done={ledger.all_done()}[/cyan]")
                        except Exception as _e:
                            logger.warning(f"[LEDGER] update failed: {_e}")
"""
patch(
    "D. post-craft ledger update",
    r"^                if done:\s*\n\s*logger\.info\(f\"\[green\]\{task\} Success\[/green\]!\"\)\s*\n\s*progress \+= 1\s*\n\s*pbar\.update\(all_task, advance=1\)",
    post_craft_inject,
)

# ---------------------------------------------------------------------
# E. Inject ledger block into REPLAN (graph_summary append)
# Anchor: `replan = ServerAPI.get_plan(`
# ---------------------------------------------------------------------
replan_inject = """                    # [LEDGER] inject working-memory state into replan prompt
                    if ledger is not None:
                        try:
                            graph_summary = (graph_summary or "") + "\\n\\n" + ledger.to_prompt_block()
                        except Exception as _e:
                            logger.warning(f"[LEDGER] inject into replan failed: {_e}")
\\g<0>"""
patch(
    "E. ledger into replan",
    r"^                    replan = ServerAPI\.get_plan\(\s*\n\s*cfg\[\"server\"\], obs, task, info, examples, graph_summary\s*\n\s*\)",
    replan_inject,
)

# ---------------------------------------------------------------------
# F. Init ledger after `obs = env.reset()` and `t.join()` in main()
# ---------------------------------------------------------------------
init_inject = """\\g<0>

            # [LEDGER] initialize per-episode progress ledger
            ledger = None
            try:
                _init_inv = dict(env.status.inventory) if hasattr(env, "status") else {}
                _init_loc = env.status.location_stats if hasattr(env, "status") else {}
                def _xyz(loc):
                    if not loc:
                        return (0.0, 64.0, 0.0)
                    def _v(k):
                        v = loc.get(k, 0.0)
                        return float(v.item() if hasattr(v, "item") else v)
                    return (_v("xpos"), _v("ypos"), _v("zpos"))
                _init_pos = _xyz(_init_loc)
                _init_equip = env.status.equipment if hasattr(env, "status") else "none"
                ledger = _ledger_init(
                    instruction=task,
                    initial_inventory=_init_inv,
                    initial_position=_init_pos,
                    initial_dimension="overworld",
                    initial_equipped=_init_equip,
                    call_llm=_ledger_get_call_llm(),
                )
                logger.info(f"[cyan][LEDGER] Initialized for task={task!r}: outcomes={[o.id for o in ledger.required_outcomes]}[/cyan]")
            except Exception as _e:
                logger.warning(f"[LEDGER] init failed: {_e}")
                ledger = None
"""
patch(
    "F. ledger init in main()",
    r"^            obs = env\.reset\(\)\s*\n\s*t\.join\(\)\s*$",
    init_inject,
)

# ---------------------------------------------------------------------
# G. Inject ledger block into INITIAL planning (graph append)
# Anchor: `planning = ServerAPI.get_plan(cfg["server"], obs, task, None, example, graph, visual_info)`
# ---------------------------------------------------------------------
plan_inject = """                        # [LEDGER] inject ledger block into the initial planner's graph context
                        _graph_with_ledger = graph
                        if ledger is not None:
                            try:
                                _graph_with_ledger = (graph or "") + "\\n\\n" + ledger.to_prompt_block()
                            except Exception as _e:
                                logger.warning(f"[LEDGER] inject into initial plan failed: {_e}")
\\g<0>"""
# Match the call but capture original exactly via lookbehind-safe approach.
# Easier: replace the whole call with a marker version.
old_plan_call_re = (
    r"^                        planning = ServerAPI\.get_plan\(\s*\n"
    r"\s*cfg\[\"server\"\], obs, task, None, example, graph, visual_info\s*\n"
    r"\s*\)"
)
new_plan_call = """                        # [LEDGER] inject ledger block into initial planner's graph context
                        _graph_with_ledger = graph
                        if ledger is not None:
                            try:
                                _graph_with_ledger = (graph or "") + "\\n\\n" + ledger.to_prompt_block()
                            except Exception as _e:
                                logger.warning(f"[LEDGER] inject into initial plan failed: {_e}")
                        planning = ServerAPI.get_plan(
                            cfg["server"], obs, task, None, example, _graph_with_ledger, visual_info
                        )"""
patch(
    "G. ledger into initial plan",
    old_plan_call_re,
    new_plan_call,
)

# ---------------------------------------------------------------------
# H. Pass ledger to agent_do(...) call in main()
# ---------------------------------------------------------------------
patch(
    "H. agent_do call passes ledger",
    r"^            status, steps, current_planning = agent_do\(\s*\n\s*cfg, env, logger, current_monitos, planning, obs, memory_bank\s*\n\s*\)",
    """            status, steps, current_planning = agent_do(
                cfg, env, logger, current_monitos, planning, obs, memory_bank, ledger=ledger
            )""",
)

# ---------------------------------------------------------------------
# Validate by compiling in-memory
# ---------------------------------------------------------------------
print()
print("=== Patches applied ===")
for p in patches_applied:
    print("  ✓", p)
if patches_failed:
    print()
    print("=== Patches FAILED ===")
    for p in patches_failed:
        print("  ✗", p)

# Compile-check
try:
    compile(src, PATH, "exec")
    print()
    print("Compile check: OK")
except SyntaxError as e:
    print()
    print(f"Compile check: SYNTAX ERROR")
    print(f"  {e}")
    print(f"  Refusing to write file. Restoring backup is automatic.")
    sys.exit(1)

if patches_failed:
    print()
    print("Some patches did not apply. Refusing to write file.")
    print("File is NOT modified. Backup is intact.")
    sys.exit(1)

# Write
with open(PATH, "w") as f:
    f.write(src)
print()
print(f"Wrote patched {PATH}")
PYEOF

# Final compile-check on disk
python -m py_compile "$MAIN_PY" 2>&1
echo ""
echo "=== Marker counts ==="
echo "Ledger imports: $(grep -c 'from optimus1.progress_ledger import' $MAIN_PY)"
echo "[LEDGER] markers: $(grep -c '\[LEDGER\]' $MAIN_PY)"
echo ""
echo "Backup at: $BACKUP"
echo "To revert: cp $BACKUP $MAIN_PY"
