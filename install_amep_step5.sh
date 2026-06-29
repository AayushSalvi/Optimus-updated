#!/bin/bash
# install_amep_step5.sh
# Step 5: failure-metadata capture at write time.
# - Augment memory.save_plan() / _save_plan() to accept optional failure_metadata
# - At main.py save_plan call site, extract failure metadata from ledger + monitors
#   when status == "failed", pass it through.
#
# Run from ~/Optimus-1.

set -e
cd ~/Optimus-1

MEMORY_PY="src/optimus1/memories/memory.py"
MAIN_PY="src/optimus1/main.py"

# Pre-flight
python -m py_compile "$MEMORY_PY" && python -m py_compile "$MAIN_PY" || {
  echo "ERROR: files don't compile pre-patch"; exit 1
}

if grep -q "failure_metadata" "$MEMORY_PY" || grep -q "failure_metadata" "$MAIN_PY"; then
  echo "ERROR: failure_metadata already present, refusing to re-patch"
  exit 1
fi

# Backups
cp "$MEMORY_PY" "${MEMORY_PY}.bak_amep_step5"
cp "$MAIN_PY" "${MAIN_PY}.bak_amep_step5"
echo "Backups created"

# ============================================================
# Patch 1: memory.py — augment save_plan and _save_plan
# ============================================================
python3 << 'PYEOF'
import sys

path = "src/optimus1/memories/memory.py"
with open(path) as f:
    src = f.read()

results = []

# Augment save_plan signature
old_sp_sig = '''    def save_plan(
        self,
        task: str,
        visual_info: str,
        goal: str,
        status: str,
        planning: List[Dict[str, Any]],
        steps: int | float,
        video_file: MultiThreadServerAPI | None = None,
        environment: str = "none",
    ):'''
new_sp_sig = '''    def save_plan(
        self,
        task: str,
        visual_info: str,
        goal: str,
        status: str,
        planning: List[Dict[str, Any]],
        steps: int | float,
        video_file: MultiThreadServerAPI | None = None,
        environment: str = "none",
        failure_metadata: dict | None = None,
    ):'''
if old_sp_sig in src:
    src = src.replace(old_sp_sig, new_sp_sig, 1)
    results.append("  [OK] save_plan signature")
else:
    results.append("  [FAIL] save_plan signature anchor not found")

# Pass failure_metadata through to _save_plan via the thread args
old_thread_args = '''            args=(
                task,
                visual_info,
                goal,
                status,
                planning,
                steps,
                video_file,
                environment,
            ),'''
new_thread_args = '''            args=(
                task,
                visual_info,
                goal,
                status,
                planning,
                steps,
                video_file,
                environment,
                failure_metadata,
            ),'''
if old_thread_args in src:
    src = src.replace(old_thread_args, new_thread_args, 1)
    results.append("  [OK] thread args")
else:
    results.append("  [FAIL] thread args anchor not found")

# Augment _save_plan signature
old_spi_sig = '''    def _save_plan(
        self,
        task: str,
        visual_info: str,
        goal: str,
        status: str,
        planning: List[Dict[str, Any]],
        steps: int | float,
        video_file: MultiThreadServerAPI | None = None,
        environment: str = "none",
    ):'''
new_spi_sig = '''    def _save_plan(
        self,
        task: str,
        visual_info: str,
        goal: str,
        status: str,
        planning: List[Dict[str, Any]],
        steps: int | float,
        video_file: MultiThreadServerAPI | None = None,
        environment: str = "none",
        failure_metadata: dict | None = None,
    ):'''
if old_spi_sig in src:
    src = src.replace(old_spi_sig, new_spi_sig, 1)
    results.append("  [OK] _save_plan signature")
else:
    results.append("  [FAIL] _save_plan signature anchor not found")

# Augment the entry dict construction to include failure_metadata
old_entry = '''            memory["plan"].append(
                {
                    "id": shortuuid.uuid(),
                    "environment": environment,
                    "visual_info": visual_info,
                    "goal": goal,
                    "video": vf,
                    "planning": planning,
                    "status": status,
                    "steps": steps,
                }
            )'''
new_entry = '''            entry = {
                "id": shortuuid.uuid(),
                "environment": environment,
                "visual_info": visual_info,
                "goal": goal,
                "video": vf,
                "planning": planning,
                "status": status,
                "steps": steps,
            }
            if failure_metadata is not None and status == "failed":
                entry["failure_metadata"] = failure_metadata
            from datetime import datetime as _dt
            entry["saved_at"] = _dt.utcnow().isoformat(timespec="seconds") + "Z"
            memory["plan"].append(entry)'''
if old_entry in src:
    src = src.replace(old_entry, new_entry, 1)
    results.append("  [OK] entry dict construction")
else:
    results.append("  [FAIL] entry dict anchor not found")

# Compile + write
print("=== memory.py patches ===")
for r in results:
    print(r)

try:
    compile(src, path, "exec")
    print("Compile: OK")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    sys.exit(1)

if any("[FAIL]" in r for r in results):
    print("Some patches failed. NOT writing.")
    sys.exit(1)

with open(path, "w") as f:
    f.write(src)
print(f"Wrote {path}")
PYEOF

python -m py_compile "$MEMORY_PY" && echo "memory.py: OK"

# ============================================================
# Patch 2: main.py — capture failure metadata + pass to save_plan
# ============================================================
python3 << 'PYEOF'
import sys

path = "src/optimus1/main.py"
with open(path) as f:
    src = f.read()

# Replace the save_plan call to first capture failure metadata
old_call = '''            video_file = env.save_video(task, status)
            # * save planning
            t = memory_bank.save_plan(
                task,
                visual_info,
                goal,
                status,
                current_planning,
                steps,
                video_file,
                environment=environment,
            )'''

new_call = '''            video_file = env.save_video(task, status)

            # [AMEP] Capture failure metadata when status == "failed"
            #   Pulls from the ledger (pending outcomes) and current_monitos (which
            #   sub-task failed and at what step count).
            _amep_failure_metadata = None
            if status == "failed":
                try:
                    _summary = current_monitos.get_metric() if current_monitos else {}
                    # Find the last sub-task with SuccessMonitor=0 (or last entry if all succeeded)
                    _failed_subtask = ""
                    _failed_at_step = int(steps) if steps else 0
                    if isinstance(_summary, dict):
                        for sub_name, sub_metrics in _summary.items():
                            if isinstance(sub_metrics, dict) and sub_metrics.get("SuccessMonitor") == 0:
                                _failed_subtask = sub_name
                                _step_val = sub_metrics.get("StepMonitor", 0)
                                if isinstance(_step_val, (int, float)):
                                    _failed_at_step = int(_step_val)
                    _pending_outcomes = []
                    if ledger is not None:
                        try:
                            _pending_outcomes = list(ledger.pending())
                        except Exception:
                            pass
                    _amep_failure_metadata = {
                        "failed_subtask": _failed_subtask,
                        "failed_at_step": _failed_at_step,
                        "pending_outcomes": _pending_outcomes,
                        "last_error": "",  # could populate from a logged warning later
                        "sub_task_summary": _summary if isinstance(_summary, dict) else {},
                    }
                    logger.info(
                        f"[AMEP] Captured failure metadata: failed at {_failed_subtask!r} "
                        f"(step {_failed_at_step}); pending outcomes: {_pending_outcomes}"
                    )
                except Exception as _e:
                    logger.warning(f"[AMEP] failure metadata capture failed: {_e}")

            # * save planning
            t = memory_bank.save_plan(
                task,
                visual_info,
                goal,
                status,
                current_planning,
                steps,
                video_file,
                environment=environment,
                failure_metadata=_amep_failure_metadata,
            )'''

if old_call not in src:
    print("ERROR: save_plan call anchor not found")
    sys.exit(1)

src = src.replace(old_call, new_call, 1)

try:
    compile(src, path, "exec")
    print("=== main.py patch ===")
    print("  [OK] Compile check passed")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    sys.exit(1)

with open(path, "w") as f:
    f.write(src)
print(f"Wrote {path}")
PYEOF

python -m py_compile "$MAIN_PY" && echo "main.py: OK"

# ============================================================
# Verify
# ============================================================
echo ""
echo "=== Verification ==="
echo "failure_metadata references in memory.py (expect 4):"
grep -c "failure_metadata" "$MEMORY_PY"
echo ""
echo "failure_metadata references in main.py (expect ~5):"
grep -c "failure_metadata\|_amep_failure_metadata" "$MAIN_PY"
echo ""
echo "[AMEP] markers in main.py (expect previous + 1 or 2 new):"
grep -c "\[AMEP\]" "$MAIN_PY"

echo ""
echo "Step 5 complete."
echo ""
echo "How to test:"
echo "  Run a task you expect to fail (e.g., stone task 6) so we exercise"
echo "  the failure-capture path. Then inspect the new failed entry:"
echo ""
echo "  rm -f src/optimus1/memories/v1/plan/failed/*.json"
echo "  CUDA_VISIBLE_DEVICES=3 xvfb-run -a python -m optimus1.main \\"
echo "    server.port=9000 benchmark=stone evaluate='[6]' env.times=1 env.max_minutes=6 \\"
echo "    2>&1 | tee /tmp/stone_6_amep_v2.log | tail -10"
echo "  grep '\\[AMEP\\]' /tmp/stone_6_amep_v2.log | head -5"
echo "  cat src/optimus1/memories/v1/plan/failed/Craft_a_stone_sword.json | python3 -m json.tool | head -40"
echo ""
echo "To revert:"
echo "  cp ${MEMORY_PY}.bak_amep_step5 ${MEMORY_PY}"
echo "  cp ${MAIN_PY}.bak_amep_step5 ${MAIN_PY}"
