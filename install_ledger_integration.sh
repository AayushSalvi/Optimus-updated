#!/bin/bash
# install_ledger_integration.sh
# Hooks progress_ledger into Optimus-1's main.py task loop.
# Run from ~/Optimus-1
#
# What this does:
#  1. Backs up main.py to main.py.bak_ledger
#  2. Adds imports for the progress_ledger package
#  3. Adds 3 hook points: init at task start, update per sub-task, inject into planner prompts

set -e

if [ ! -f "src/optimus1/main.py" ]; then
  echo "ERROR: src/optimus1/main.py not found. Run from ~/Optimus-1."
  exit 1
fi

if [ ! -d "src/optimus1/progress_ledger" ]; then
  echo "ERROR: src/optimus1/progress_ledger/ does not exist. Run install_progress_ledger.sh + install_llm_adapter.sh first."
  exit 1
fi

cp src/optimus1/main.py src/optimus1/main.py.bak_ledger
echo "Backed up main.py to main.py.bak_ledger"

python3 << 'PYEOF'
import re

path = "src/optimus1/main.py"
with open(path, "r") as f:
    content = f.read()

# ============================================================
# 1. Add imports if not already present
# ============================================================
imports_to_add = '''# === Progress Ledger imports ===
from optimus1.progress_ledger import (
    init_ledger as _ledger_init,
    detect_key_nodes as _ledger_detect,
    update_ledger as _ledger_summarize,
    compute_world_delta as _ledger_compute_delta,
    StepRecord as _LedgerStepRecord,
    append_step as _ledger_append_step,
    make_call_llm as _ledger_make_call_llm,
)
_LEDGER_CALL_LLM = None  # lazy init on first use

def _ledger_get_call_llm():
    global _LEDGER_CALL_LLM
    if _LEDGER_CALL_LLM is None:
        _LEDGER_CALL_LLM = _ledger_make_call_llm()
    return _LEDGER_CALL_LLM
# === end Progress Ledger imports ===
'''

if "from optimus1.progress_ledger import" not in content:
    # Insert after the last `from optimus1` import line
    last_optimus_import = list(re.finditer(r'(from optimus1[^\n]+\n)', content))
    if last_optimus_import:
        last = last_optimus_import[-1]
        insert_pos = last.end()
        content = content[:insert_pos] + "\n" + imports_to_add + "\n" + content[insert_pos:]
        print("Inserted ledger imports")
    else:
        print("WARNING: could not find optimus1 imports; trying after 'import json' line")
        m = re.search(r'(import json\s*\n)', content)
        if m:
            content = content[:m.end()] + "\n" + imports_to_add + "\n" + content[m.end():]
            print("Inserted ledger imports after 'import json'")
        else:
            raise RuntimeError("Could not find a place to insert imports. Aborting.")
else:
    print("Imports already present, skipping")

# ============================================================
# 2. Hook: initialize ledger at task start
# ============================================================
# Insert right after `obs = env.reset()` line
init_hook = '''
            # === Progress Ledger: init at task start ===
            try:
                _ledger_initial_inv = {}
                _ledger_initial_pos = (0.0, 64.0, 0.0)
                if hasattr(env, "info") and isinstance(env.info, dict):
                    _ledger_initial_inv = dict(env.info.get("inventory", {}) or {})
                    _loc = env.info.get("location_stats", {}) or {}
                    if _loc:
                        try:
                            _ledger_initial_pos = (
                                float(_loc.get("xpos", 0.0)),
                                float(_loc.get("ypos", 64.0)),
                                float(_loc.get("zpos", 0.0)),
                            )
                        except Exception:
                            pass
                _ledger = _ledger_init(
                    instruction=task,
                    initial_inventory=_ledger_initial_inv,
                    initial_position=_ledger_initial_pos,
                    initial_dimension="overworld",
                    initial_equipped="none",
                    call_llm=_ledger_get_call_llm(),
                )
                logger.info(f"[cyan][PROGRESS LEDGER] Initialized with {len(_ledger.required_outcomes)} outcomes[/cyan]")
                for _o in _ledger.required_outcomes:
                    logger.info(f"[cyan]  - {_o.id}: {_o.evidence_hint}[/cyan]")
                _ledger_prev_inv = dict(_ledger_initial_inv)
                _ledger_prev_loc = dict(_loc) if _loc else {}
            except Exception as _e:
                logger.warning(f"[red][PROGRESS LEDGER] init failed: {_e}; will run without ledger[/red]")
                _ledger = None
                _ledger_prev_inv = {}
                _ledger_prev_loc = {}
            # === end Progress Ledger init ===
'''

# Find the line `obs = env.reset()` inside the for-task loop, AFTER `t.join()`
# We expect the pattern: "obs = env.reset()\n            t.join()"
init_anchor = re.compile(r"(\s+obs = env\.reset\(\)\s*\n\s+t\.join\(\)\s*\n)")
m = init_anchor.search(content)
if m:
    if "[PROGRESS LEDGER] Initialized" not in content:
        insert_pos = m.end()
        content = content[:insert_pos] + init_hook + content[insert_pos:]
        print("Inserted ledger init hook")
    else:
        print("Ledger init hook already present, skipping")
else:
    print("WARNING: could not find anchor `obs = env.reset()` + `t.join()`. Init hook NOT inserted.")

# ============================================================
# 3. Hook: update ledger after sub-task transitions
# ============================================================
# We add a helper inside the file (NOT inside any function) that updates the ledger
# from a fresh observation. Then we call it after key state transitions.

helper_func = '''
def _ledger_update_from_env(_ledger, env, logger, _prev_inv, _prev_loc, step_idx, action_summary, required_outcomes_cache=None):
    """Compute world delta vs prev snapshot and run detect_key_nodes. Returns (new_inv, new_loc)."""
    if _ledger is None or not _ledger.required_outcomes:
        return _prev_inv, _prev_loc
    try:
        _new_inv = {}
        _new_loc = {}
        if hasattr(env, "info") and isinstance(env.info, dict):
            _new_inv = dict(env.info.get("inventory", {}) or {})
            _new_loc = dict(env.info.get("location_stats", {}) or {})
        _delta = _ledger_compute_delta(
            inv_before=_prev_inv,
            inv_after=_new_inv,
            loc_before=_prev_loc,
            loc_after=_new_loc,
        )
        if _delta.is_empty:
            return _new_inv, _new_loc
        _current_states = {_o.id: _ledger.outcome_cache.get_state(_o.id) for _o in _ledger.required_outcomes}
        _key_nodes = _ledger_detect(
            step_idx=step_idx,
            required_outcomes=_ledger.required_outcomes,
            current_outcome_states=_current_states,
            world_delta=_delta,
            actor_action_summary=action_summary,
            call_llm=_ledger_get_call_llm(),
        )
        if _key_nodes:
            _step = _LedgerStepRecord(
                step_idx=step_idx,
                inventory=_new_inv,
                actor_action_summary=action_summary,
                key_nodes=_key_nodes,
            )
            _ledger.apply_step_keynodes(_step)
            for _kn in _key_nodes:
                logger.info(f"[cyan][PROGRESS LEDGER] {_kn.kind} -> {_kn.target} (conf={_kn.confidence})[/cyan]")
            _verified = [_o.id for _o in _ledger.required_outcomes if _ledger.outcome_cache.get_state(_o.id) == "verified"]
            if _verified:
                logger.info(f"[cyan][PROGRESS LEDGER] verified: {_verified}; all_done={_ledger.all_done()}[/cyan]")
        return _new_inv, _new_loc
    except Exception as _e:
        logger.warning(f"[red][PROGRESS LEDGER] update failed: {_e}; continuing[/red]")
        return _prev_inv, _prev_loc
'''

# Insert helper right before `def main(cfg: DictConfig):`
if "_ledger_update_from_env" not in content:
    main_match = re.search(r"\ndef main\(cfg:\s*DictConfig\)", content)
    if main_match:
        content = content[:main_match.start()] + "\n" + helper_func + "\n" + content[main_match.start():]
        print("Inserted _ledger_update_from_env helper")
    else:
        print("WARNING: could not find `def main(cfg: DictConfig)`; helper NOT inserted")

# ============================================================
# 4. Hook: inject ledger block into planner prompt
# ============================================================
# We modify the `graph` string just before the two ServerAPI.get_plan() calls.
# (We're operating on string append since the planner only reads `graph` as a string.)

# Hook point A: initial plan at line ~318
# Pattern: planning = ServerAPI.get_plan(\n  cfg["server"], obs, task, None, example, graph, visual_info\n)
initial_plan_anchor = '''                    if not has_done:
                        planning = ServerAPI.get_plan(
                            cfg["server"], obs, task, None, example, graph, visual_info
                        )'''

initial_plan_replacement = '''                    if not has_done:
                        # === Progress Ledger: inject into graph param ===
                        try:
                            _ledger_block = _ledger.to_prompt_block() if _ledger is not None else ""
                            graph_with_ledger = (graph or "") + ("\\n\\n" + _ledger_block if _ledger_block else "")
                        except Exception:
                            graph_with_ledger = graph
                        # === end Progress Ledger inject ===
                        planning = ServerAPI.get_plan(
                            cfg["server"], obs, task, None, example, graph_with_ledger, visual_info
                        )'''

if initial_plan_anchor in content:
    content = content.replace(initial_plan_anchor, initial_plan_replacement, 1)
    print("Inserted ledger block into initial planner call")
else:
    print("WARNING: could not find initial planner anchor; ledger NOT injected at line ~318")

# Hook point B: replan call at line ~154
replan_anchor = '''                    replan = ServerAPI.get_plan(
                        cfg["server"], obs, task, info, examples, graph_summary
                    )'''

replan_replacement = '''                    # === Progress Ledger: inject into replan graph_summary ===
                    try:
                        _ledger_block = _ledger.to_prompt_block() if _ledger is not None else ""
                        graph_summary_with_ledger = (graph_summary or "") + ("\\n\\n" + _ledger_block if _ledger_block else "")
                    except Exception:
                        graph_summary_with_ledger = graph_summary
                    # === end Progress Ledger inject ===
                    replan = ServerAPI.get_plan(
                        cfg["server"], obs, task, info, examples, graph_summary_with_ledger
                    )'''

if replan_anchor in content:
    content = content.replace(replan_anchor, replan_replacement, 1)
    print("Inserted ledger block into replan planner call")
else:
    print("WARNING: could not find replan planner anchor; ledger NOT injected at line ~154")

# ============================================================
# 5. Hook: update ledger inside agent_do after helper.step() and env.step()
# ============================================================
# We pass _ledger in via memory_bank's attributes (least-invasive: stash on memory_bank).
# But simpler: we just call _ledger_update_from_env when state changes.
# Pattern to wrap:  done, info = helper.step(task, goal)
helper_step_anchor = '                done, info = helper.step(task, goal)  # type: ignore'
helper_step_replacement = '''                done, info = helper.step(task, goal)  # type: ignore
                # === Progress Ledger: update after helper.step ===
                try:
                    _ledger_obj = getattr(memory_bank, "_progress_ledger", None)
                    if _ledger_obj is not None:
                        _prev_inv = getattr(memory_bank, "_ledger_prev_inv", {})
                        _prev_loc = getattr(memory_bank, "_ledger_prev_loc", {})
                        _new_inv, _new_loc = _ledger_update_from_env(
                            _ledger_obj, env, logger, _prev_inv, _prev_loc,
                            step_idx=env.num_steps,
                            action_summary=f"helper.step({task})",
                        )
                        memory_bank._ledger_prev_inv = _new_inv
                        memory_bank._ledger_prev_loc = _new_loc
                except Exception as _e:
                    logger.warning(f"[red][PROGRESS LEDGER] helper.step hook failed: {_e}[/red]")
                # === end Progress Ledger update ==='''

if helper_step_anchor in content:
    content = content.replace(helper_step_anchor, helper_step_replacement, 1)
    print("Inserted ledger update after helper.step")
else:
    print("WARNING: could not find helper.step anchor; ledger update hook NOT inserted")

# Pattern to wrap:  obs, reward, game_over, info = env.step(action, goal)
env_step_anchor = '                    obs, reward, game_over, info = env.step(action, goal)'
env_step_replacement = '''                    obs, reward, game_over, info = env.step(action, goal)
                    # === Progress Ledger: update after env.step ===
                    try:
                        _ledger_obj = getattr(memory_bank, "_progress_ledger", None)
                        if _ledger_obj is not None:
                            _prev_inv = getattr(memory_bank, "_ledger_prev_inv", {})
                            _prev_loc = getattr(memory_bank, "_ledger_prev_loc", {})
                            _new_inv, _new_loc = _ledger_update_from_env(
                                _ledger_obj, env, logger, _prev_inv, _prev_loc,
                                step_idx=env.num_steps,
                                action_summary=f"env.step({task})",
                            )
                            memory_bank._ledger_prev_inv = _new_inv
                            memory_bank._ledger_prev_loc = _new_loc
                    except Exception as _e:
                        logger.warning(f"[red][PROGRESS LEDGER] env.step hook failed: {_e}[/red]")
                    # === end Progress Ledger update ==='''

if env_step_anchor in content:
    content = content.replace(env_step_anchor, env_step_replacement, 1)
    print("Inserted ledger update after env.step")
else:
    print("WARNING: could not find env.step anchor; ledger update hook NOT inserted")

# ============================================================
# 6. Hook: stash ledger on memory_bank after init (so agent_do can find it)
# ============================================================
# After we initialized _ledger, we need to put it on memory_bank so agent_do can read it
stash_hook = '''            # === Progress Ledger: stash on memory_bank for agent_do ===
            try:
                memory_bank._progress_ledger = _ledger
                memory_bank._ledger_prev_inv = _ledger_prev_inv
                memory_bank._ledger_prev_loc = _ledger_prev_loc
            except Exception:
                pass
            # === end stash ===
'''

# Insert right after the init hook (which ends with `# === end Progress Ledger init ===`)
init_end_anchor = "            # === end Progress Ledger init ==="
if init_end_anchor in content and "memory_bank._progress_ledger" not in content:
    content = content.replace(
        init_end_anchor,
        init_end_anchor + "\n" + stash_hook,
        1,
    )
    print("Inserted memory_bank stash hook")

# Save
with open(path, "w") as f:
    f.write(content)
PYEOF

# ============================================================
# Compile check
# ============================================================
python -m py_compile src/optimus1/main.py && echo "" && echo "main.py compiles OK"

echo ""
echo "Done. To revert if something breaks:"
echo "  cp src/optimus1/main.py.bak_ledger src/optimus1/main.py"
