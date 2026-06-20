#!/bin/bash
# install_amep_step4.sh
# Step 4: replace the Step-0 single-trajectory patch in memory.py with the new
# retriever. Multi-example injection (top-3 successes + optional failure).
#
# Run from ~/Optimus-1.

set -e
cd ~/Optimus-1

MEMORY_PY="src/optimus1/memories/memory.py"
AMEP_DIR="src/optimus1/amep"

# ---------- Pre-flight ----------
if [ ! -f "$AMEP_DIR/retriever.py" ]; then
  echo "ERROR: $AMEP_DIR/retriever.py not found. Run Step 3 first."
  exit 1
fi

python -m py_compile "$MEMORY_PY" 2>&1 || { echo "ERROR: $MEMORY_PY does not compile"; exit 1; }

if ! grep -q "\[AMEP\] Using past successful run" "$MEMORY_PY"; then
  echo "ERROR: expected old AMEP patch markers not found in $MEMORY_PY"
  echo "If you've already reverted, restore from backup and try again:"
  echo "  cp $MEMORY_PY.bak_amep $MEMORY_PY"
  exit 1
fi

# Backup
cp "$MEMORY_PY" "${MEMORY_PY}.bak_amep_v2"
echo "Backup: ${MEMORY_PY}.bak_amep_v2"

# ---------- Patch memory.py ----------
python3 << 'PYEOF'
import sys

path = "src/optimus1/memories/memory.py"
with open(path, "r") as f:
    src = f.read()

# -----------------------------------------------------------------------
# 1. Replace the Step-0 AMEP patch block with a call to the new retriever.
# -----------------------------------------------------------------------
# Anchor: start with the comment line we inserted, end with the catch-all
# print + the next blank line before the existing _MEMORY_BANK block.

old_block_start = '        # [AMEP] Tier 1: prefer past successful runs of THIS exact task (sorted by step count)'
old_block_end_marker = 'print(f"[AMEP] Past-success lookup failed: {_e}, falling through")'

start_idx = src.find(old_block_start)
end_anchor_idx = src.find(old_block_end_marker)

if start_idx == -1 or end_anchor_idx == -1:
    print("ERROR: old AMEP patch markers not found. Refusing to patch.")
    sys.exit(1)

# Find end of the line containing the end marker
end_idx = src.find("\n", end_anchor_idx) + 1

# Verify there's also a trailing empty-line block before `if _MEMORY_BANK`
# (we inserted a blank line in Step 0 for readability)
old_block = src[start_idx:end_idx]
print(f"Replacing {len(old_block)} chars (lines {src[:start_idx].count(chr(10))+1} - {src[:end_idx].count(chr(10))+1})")

new_block = '''        # [AMEP] Tier 1: query the unified retriever for past trajectories.
        #   Returns top-K successes (multi-example injection) and optionally one
        #   labeled past failure to warn the planner away from known dead ends.
        try:
            from optimus1.amep import (
                retrieve_for_task,
                render_success_examples,
                render_failure_warning,
            )
            amep_env = getattr(self, "current_environment", "") or ""
            amep_result = retrieve_for_task(
                task=task,
                environment=amep_env,
                initial_inventory={},
                scorer_kind="rule",
                k_success=3,
            )
            if amep_result.has_any() and amep_result.successes:
                best = amep_result.best_success()
                plan = best.record.planning
                render_plan = {}
                for idx, p in enumerate(plan):
                    render_plan[f"step {idx+1}"] = p
                goal = best.record.goal or (plan[-1].get("goal", [""])[0] if plan else "")
                visual_info = best.record.visual_info or "None"
                # Build the examples block: top-1 used as the primary plan,
                # additional successes + failure shown as supplementary context.
                supplementary = []
                if len(amep_result.successes) > 1:
                    supplementary.append(
                        render_success_examples(amep_result.successes[1:], limit=2)
                    )
                if amep_result.failure is not None:
                    supplementary.append(render_failure_warning(amep_result.failure))
                supplementary_text = "\\n\\n".join([s for s in supplementary if s])
                primary_examples = PLAN_EXAMPLE_FORMAT.format(
                    task_key.replace("_", " "),
                    visual_info,
                    self.retrieve_graph(goal),
                    json.dumps(render_plan),
                )
                examples = primary_examples
                if supplementary_text:
                    examples = examples + "\\n\\n" + supplementary_text
                print(
                    f"[AMEP] task={task!r} env={amep_env[:30]!r}: "
                    f"primary={best.record.steps}-step run (score={best.score:.2f}), "
                    f"+{len(amep_result.successes)-1} more successes"
                    f"{', +1 failure warning' if amep_result.failure else ''}"
                )
                return examples, True
        except FileNotFoundError:
            pass
        except Exception as _e:
            print(f"[AMEP] retriever failed ({type(_e).__name__}: {_e}), falling through")
'''

src = src[:start_idx] + new_block + src[end_idx:]

# -----------------------------------------------------------------------
# 2. Compile check
# -----------------------------------------------------------------------
try:
    compile(src, path, "exec")
    print("Compile check: OK")
except SyntaxError as e:
    print(f"SyntaxError after patch: line {e.lineno}: {e.msg}")
    # Print a few lines around the error
    lines = src.split("\n")
    start = max(0, e.lineno - 5)
    end = min(len(lines), e.lineno + 5)
    for i in range(start, end):
        marker = " >>" if i == e.lineno - 1 else "   "
        print(f"  {marker} {i+1:4d}: {lines[i]}")
    sys.exit(1)

with open(path, "w") as f:
    f.write(src)
print(f"Patched {path}")
PYEOF

python -m py_compile "$MEMORY_PY" && echo "compiles OK"

# ---------- Verify ----------
echo ""
echo "=== Verification ==="
echo "Old patch markers (should be 0):"
grep -c "Using past successful run" "$MEMORY_PY"
echo ""
echo "New AMEP markers (should be >= 3):"
grep -c "\[AMEP\]" "$MEMORY_PY"
echo ""
echo "Imports the retriever?"
grep -c "from optimus1.amep import" "$MEMORY_PY"

# ---------- Smoke test (no Minecraft, just verify retrieve_plan returns sensible output) ----------
echo ""
echo "=== Smoke test: call retrieve_plan directly ==="
python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")

# Build a minimal Memory instance to call retrieve_plan
from optimus1.memories.memory import Memory

class _StubLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass

class _StubCfg:
    def __getitem__(self, k):
        return {"version": "v1", "task": {"interactive": False}, "type": "headless"}.get(k, None)

mem = Memory.__new__(Memory)  # bypass __init__ to avoid file deps we don't need
mem.version = "v1"
mem.current_environment = "forest"
mem.logger = _StubLogger()

# Test on a task with multiple past successes
examples, has_done = mem.retrieve_plan("Craft a crafting table")
print(f"\n--- Craft a crafting table ---")
print(f"has_done: {has_done}")
print(f"examples length: {len(examples) if examples else 0} chars")
if examples:
    print("First 600 chars of examples:")
    print(examples[:600])
    print("...")
    # Confirm supplementary examples got injected
    if "Past successful runs" in examples:
        print("\n[OK] Supplementary AMEP examples found in output")
    else:
        print("\n[INFO] No supplementary examples in output (only 1 candidate above threshold)")
PYEOF

echo ""
echo "Step 4 complete."
echo ""
echo "Next: full end-to-end smoke test in Minecraft on wooden task 5."
echo "  rm -f src/optimus1/memories/v1/plan/failed/*.json"
echo "  CUDA_VISIBLE_DEVICES=3 xvfb-run -a python -m optimus1.main \\"
echo "    server.port=9000 benchmark=wooden evaluate='[5]' env.times=1 env.max_minutes=3 \\"
echo "    2>&1 | tee /tmp/wooden_5_amep_v2.log | tail -15"
echo "  grep '\\[AMEP\\]' /tmp/wooden_5_amep_v2.log | head -5"
echo "  grep -E 'All tasks are completed|Some tasks are not completed' /tmp/wooden_5_amep_v2.log | head -1"
echo ""
echo "To revert: cp ${MEMORY_PY}.bak_amep_v2 ${MEMORY_PY}"
