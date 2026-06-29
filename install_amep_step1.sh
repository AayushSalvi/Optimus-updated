#!/bin/bash
# install_amep_step1.sh
# Step 1 of AMEP build: create the amep/ module skeleton with store.py
# Pure data layer — read/write past trajectories, no LLM, no retrieval logic.
#
# Run from ~/Optimus-1.

set -e
cd ~/Optimus-1

AMEP_DIR="src/optimus1/amep"

# Pre-flight
if [ -d "$AMEP_DIR" ]; then
  echo "ERROR: $AMEP_DIR already exists. Remove or rename before re-running."
  exit 1
fi

mkdir -p "$AMEP_DIR"
echo "Created $AMEP_DIR/"

# ----- __init__.py: package-level exports -----
cat > "$AMEP_DIR/__init__.py" << 'PYEOF'
"""AMEP — Abstracted Multimodal Experience Pool (text-only, Phase 1).

Stores past task trajectories with structured outcome metadata, retrieves
context-similar past runs as few-shot examples for the planner, and surfaces
labeled past failures as "avoid this approach" hints.

Modules:
  store     — read/write past trajectories in plan/success/, plan/failed/
  scorer    — similarity scorer (rule-based; embedding swap in later)
  retriever — top-K retrieval over the store using a scorer
"""
from .store import (
    TrajectoryRecord,
    FailureMetadata,
    AmepStore,
    load_store,
)

__all__ = [
    "TrajectoryRecord",
    "FailureMetadata",
    "AmepStore",
    "load_store",
]
PYEOF

# ----- store.py: schema + IO over plan/success/, plan/failed/ -----
cat > "$AMEP_DIR/store.py" << 'PYEOF'
"""AMEP storage layer.

Reads and writes past trajectories in the existing Optimus-1 folders:
  src/optimus1/memories/<version>/plan/success/<Task_name>.json
  src/optimus1/memories/<version>/plan/failed/<Task_name>.json

Each JSON file has shape {"plan": [entry, entry, ...]}.

Augmented schema (per entry):
  Required (from Optimus-1):
    id, environment, visual_info, goal, planning, status, steps
  New (AMEP-added, optional for backwards-compat reads):
    initial_context: dict  -- biome, dimension, initial_inventory snapshot
    outcomes_verified: list[str]  -- ledger outcome ids that were verified at task end
    failure_metadata: dict  -- only present on failed entries; see FailureMetadata
    saved_at: ISO timestamp

Entries written before AMEP existed lack the new fields — readers must default.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
@dataclass
class FailureMetadata:
    """What went wrong when a task failed.

    Populated at the moment the run is closed out with status='failed'.
    Designed so that any single field can be missing (str defaults to empty).
    """
    failed_subtask: str = ""      # e.g. "craft wooden_pickaxe" — the sub-task that triggered task failure
    failed_at_step: int = 0       # cumulative step count when it gave up
    pending_outcomes: List[str] = field(default_factory=list)  # ledger outcome ids still pending
    last_error: str = ""          # last error message from the framework
    sub_task_summary: Dict[str, Any] = field(default_factory=dict)  # raw Monitors dict

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "FailureMetadata":
        if not d:
            return cls()
        return cls(
            failed_subtask=d.get("failed_subtask", "") or "",
            failed_at_step=int(d.get("failed_at_step", 0) or 0),
            pending_outcomes=list(d.get("pending_outcomes", []) or []),
            last_error=d.get("last_error", "") or "",
            sub_task_summary=dict(d.get("sub_task_summary", {}) or {}),
        )


@dataclass
class TrajectoryRecord:
    """One past task execution — either a success or a failure."""
    task: str                              # human-readable task instruction
    task_key: str                          # snake-case form, matches filename stem
    status: str                            # "success" or "failed"
    steps: int                             # total env steps used
    planning: List[Dict[str, Any]]         # the sub-task sequence agent executed
    environment: str = ""                  # biome / visual env description
    visual_info: str = ""
    goal: str = ""

    # AMEP-added fields (optional; backwards-compat readers must default)
    initial_context: Dict[str, Any] = field(default_factory=dict)
    outcomes_verified: List[str] = field(default_factory=list)
    failure_metadata: Optional[FailureMetadata] = None
    saved_at: str = ""

    # Original Optimus-1 fields we preserve but don't actively use
    id: str = ""
    video: str = ""

    def to_optimus_entry(self) -> Dict[str, Any]:
        """Serialize to the per-entry dict shape that lives in plan/success/*.json."""
        d: Dict[str, Any] = {
            "id": self.id,
            "environment": self.environment,
            "visual_info": self.visual_info,
            "goal": self.goal,
            "video": self.video,
            "planning": self.planning,
            "status": self.status,
            "steps": self.steps,
        }
        # AMEP-added (only emit if populated — keeps backwards-compat tooling happy)
        if self.initial_context:
            d["initial_context"] = self.initial_context
        if self.outcomes_verified:
            d["outcomes_verified"] = self.outcomes_verified
        if self.failure_metadata is not None:
            d["failure_metadata"] = self.failure_metadata.to_dict()
        if self.saved_at:
            d["saved_at"] = self.saved_at
        return d

    @classmethod
    def from_optimus_entry(cls, entry: Dict[str, Any], task: str, task_key: str) -> "TrajectoryRecord":
        """Build a TrajectoryRecord from one entry inside plan/{success,failed}/*.json."""
        return cls(
            task=task,
            task_key=task_key,
            status=entry.get("status", "success") or "success",
            steps=int(entry.get("steps", 0) or 0),
            planning=list(entry.get("planning", []) or []),
            environment=entry.get("environment", "") or "",
            visual_info=entry.get("visual_info", "") or "",
            goal=entry.get("goal", "") or "",
            initial_context=dict(entry.get("initial_context", {}) or {}),
            outcomes_verified=list(entry.get("outcomes_verified", []) or []),
            failure_metadata=FailureMetadata.from_dict(entry.get("failure_metadata")),
            saved_at=entry.get("saved_at", "") or "",
            id=entry.get("id", "") or "",
            video=entry.get("video", "") or "",
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class AmepStore:
    """File-backed store for past trajectories.

    Reads and writes the existing Optimus-1 success/failed plan folders.
    """

    def __init__(self, memory_root: str):
        """
        Args:
            memory_root: e.g. 'src/optimus1/memories/v1' — the folder containing plan/.
        """
        self.memory_root = memory_root
        self.success_dir = os.path.join(memory_root, "plan", "success")
        self.failed_dir = os.path.join(memory_root, "plan", "failed")

    # ----- helpers -----
    @staticmethod
    def _task_to_filename(task_or_key: str) -> str:
        """Convert a task instruction (or already-normalized key) to a filename.

        Optimus-1's convention for filenames is mixed — some files preserve the
        capitalization of the instruction (e.g. 'Craft_a_torch.json'), others
        use lowercase (e.g. 'chop_a_tree.json'). We don't try to guess; the
        retriever does case-insensitive matching at lookup time.
        """
        return task_or_key.replace(" ", "_") + ".json"

    def _list_dir(self, dir_path: str) -> List[str]:
        try:
            return os.listdir(dir_path)
        except FileNotFoundError:
            return []

    def _find_matching_file(self, dir_path: str, task: str) -> Optional[str]:
        """Case-insensitive exact match by filename stem."""
        target = task.replace(" ", "_").lower()
        for fname in self._list_dir(dir_path):
            base = fname.replace(".json", "").lower()
            if base == target:
                return fname
        return None

    # ----- read -----
    def _read_entries(self, dir_path: str, task: str) -> List[TrajectoryRecord]:
        fname = self._find_matching_file(dir_path, task)
        if fname is None:
            return []
        path = os.path.join(dir_path, fname)
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"[AMEP.store] failed to read {path}: {e}")
            return []
        entries = data.get("plan", []) or []
        task_key = fname.replace(".json", "").replace("_", " ").lower()
        records = []
        for entry in entries:
            try:
                records.append(TrajectoryRecord.from_optimus_entry(entry, task=task, task_key=task_key))
            except Exception as e:
                logger.warning(f"[AMEP.store] skipped malformed entry in {fname}: {e}")
        return records

    def read_successes(self, task: str) -> List[TrajectoryRecord]:
        """Return all past successful runs for this task (case-insensitive match)."""
        return self._read_entries(self.success_dir, task)

    def read_failures(self, task: str) -> List[TrajectoryRecord]:
        """Return all past failed runs for this task (case-insensitive match)."""
        return self._read_entries(self.failed_dir, task)

    # ----- write -----
    def _append_entry(self, dir_path: str, task: str, record: TrajectoryRecord) -> None:
        os.makedirs(dir_path, exist_ok=True)
        # Prefer to append to an existing file with the same case if present;
        # otherwise create a new file with the task instruction's whitespace converted.
        existing = self._find_matching_file(dir_path, task)
        if existing:
            path = os.path.join(dir_path, existing)
        else:
            path = os.path.join(dir_path, self._task_to_filename(task))

        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning(f"[AMEP.store] {path} unreadable, starting fresh: {e}")
                data = {"plan": []}
        else:
            data = {"plan": []}

        if "plan" not in data or not isinstance(data["plan"], list):
            data["plan"] = []

        if not record.saved_at:
            record.saved_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        data["plan"].append(record.to_optimus_entry())
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"[AMEP.store] appended {record.status} entry to {path} (now {len(data['plan'])} entries)")

    def append_success(self, task: str, record: TrajectoryRecord) -> None:
        record.status = "success"
        self._append_entry(self.success_dir, task, record)

    def append_failure(self, task: str, record: TrajectoryRecord) -> None:
        record.status = "failed"
        self._append_entry(self.failed_dir, task, record)


def load_store(version: str = "v1") -> AmepStore:
    """Convenience constructor.

    Args:
        version: Optimus-1 memory version label (e.g. 'v1').
    """
    return AmepStore(memory_root=f"src/optimus1/memories/{version}")
PYEOF

echo "Created $AMEP_DIR/__init__.py"
echo "Created $AMEP_DIR/store.py"

# Compile check
python -m py_compile "$AMEP_DIR"/__init__.py "$AMEP_DIR"/store.py && echo "Compile: OK"

# ----- smoke test: read existing entries via the new store -----
echo ""
echo "=== Smoke test: read existing past trajectories ==="
python3 << 'PYEOF'
from optimus1.amep import load_store

store = load_store()

# 1. Existing wooden task with many entries
successes = store.read_successes("Craft a crafting table")
print(f"Successes for 'Craft a crafting table': {len(successes)}")
if successes:
    fastest = min(successes, key=lambda r: r.steps)
    print(f"  Fastest: {fastest.steps} steps, env={fastest.environment[:30]!r}")
    print(f"  Plan length: {len(fastest.planning)} sub-tasks")

# 2. Existing stone task with one entry
successes = store.read_successes("Craft a stone sword")
print(f"\nSuccesses for 'Craft a stone sword': {len(successes)}")
if successes:
    print(f"  Steps: {successes[0].steps}, env={successes[0].environment!r}")

# 3. Task with no past entries
successes = store.read_successes("Craft a diamond pickaxe")
print(f"\nSuccesses for 'Craft a diamond pickaxe': {len(successes)} (expect 0)")

# 4. Read failures (these exist from earlier sessions)
failures = store.read_failures("Craft a torch")
print(f"\nFailures for 'Craft a torch': {len(failures)}")
PYEOF

echo ""
echo "Step 1 complete."
echo ""
echo "Next: review the smoke test output above. If counts look right (Craft a"
echo "crafting table = ~11, Craft a stone sword = 1, diamond pickaxe = 0, torch"
echo "failures = some number), the store layer is healthy and we move to Step 2"
echo "(scorer)."
