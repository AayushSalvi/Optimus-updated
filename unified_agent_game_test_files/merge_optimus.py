"""
Step 2: Convert Optimus-1 experience pool data and merge into the JARVIS-1 memory bank.

USAGE:
  python merge_optimus_data.py

BEFORE RUNNING:
  1. Run convert_jarvis_memory.py first to generate memory_bank_v1.json
  2. Update the paths below to match your local setup
"""

import json
import os
import re
from collections import defaultdict

# ============================================================
# UPDATE THESE PATHS FOR YOUR MACHINE
# ============================================================
MEMORY_BANK_PATH = "memory_bank_v1.json"
OPTIMUS_SUCCESS_DIR = "../plan/success"  # <-- CHANGE THIS
OUTPUT_PATH = "memory_bank_v2.json"
# ============================================================


def infer_type(task_name, goal_item):
    task_lower = task_name.lower()
    if any(w in task_lower for w in ["smelt", "furnace"]):
        return "smelt"
    if any(w in task_lower for w in ["equip", "wear", "put on"]):
        return "equip"
    if any(w in task_lower for w in ["craft", "make", "create"]):
        return "craft"
    if any(w in task_lower for w in [
        "chop", "mine", "dig", "break", "collect", "gather", "find", "obtain",
        "harvest", "kill", "hunt", "approach", "locate", "search", "explore",
        "navigate", "move", "walk", "exit", "eat", "retrieve", "achieve"
    ]):
        return "mine"

    craft_items = {
        "planks", "stick", "sticks", "crafting_table", "furnace",
        "wooden_pickaxe", "stone_pickaxe", "iron_pickaxe",
        "wooden_axe", "stone_axe", "iron_axe",
        "wooden_sword", "stone_sword", "iron_sword",
        "wooden_shovel", "stone_shovel", "iron_shovel",
        "wooden_hoe", "stone_hoe", "iron_hoe",
        "bowl", "chest", "bucket", "ladder", "torch",
        "diamond_pickaxe", "diamond_sword", "diamond_axe",
        "golden_pickaxe", "golden_sword", "golden_axe",
        "iron_nugget", "iron_bars", "iron_door",
        "blast_furnace", "smoker", "smithing_table", "stonecutter",
        "shield", "shears", "compass", "hopper", "dropper",
        "piston", "note_block", "jukebox", "rail", "activator_rail",
        "redstone_torch", "tripwire_hook", "chain", "iron_trapdoor",
        "leather_helmet", "leather_chestplate", "leather_leggings", "leather_boots",
        "iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots",
        "golden_helmet", "golden_chestplate", "golden_leggings", "golden_boots",
        "diamond_helmet", "diamond_chestplate", "diamond_leggings", "diamond_boots",
    }
    smelt_items = {
        "iron_ingot", "gold_ingot", "glass", "charcoal",
        "stone", "smooth_stone", "cooked_chicken", "cooked_beef",
        "cooked_porkchop", "cooked_mutton",
    }
    if goal_item in smelt_items:
        return "smelt"
    if goal_item in craft_items:
        return "craft"
    return "mine"


def convert_optimus_step(optimus_step):
    task_name = optimus_step["task"]
    goal = optimus_step["goal"]
    item_name = goal[0]
    count = goal[1] if len(goal) > 1 else 1

    if item_name == "environment":
        return {"goal": {"environment": 1}, "type": "mine", "text": task_name}

    if isinstance(count, str):
        try:
            count = int(count)
        except ValueError:
            count = 1

    step_type = infer_type(task_name, item_name)
    return {"goal": {item_name: count}, "type": step_type, "text": item_name}


def convert_optimus_plan(optimus_entry):
    steps = []
    for planning_step in optimus_entry["planning"]:
        steps.append(convert_optimus_step(planning_step))
    return steps


def get_target_item(optimus_data):
    if "plan" not in optimus_data or len(optimus_data["plan"]) == 0:
        return None
    entry = optimus_data["plan"][0]
    if "goal" in entry and isinstance(entry["goal"], str):
        return entry["goal"]
    if "planning" in entry and len(entry["planning"]) > 0:
        last_step = entry["planning"][-1]
        if "goal" in last_step and isinstance(last_step["goal"], list) and len(last_step["goal"]) > 0:
            return last_step["goal"][0]
    return None


def steps_signature(steps):
    """Hashable signature for dedup."""
    sig = []
    for step in steps:
        items = sorted(step["goal"].items())
        sig.append((step["type"], tuple(items)))
    return tuple(sig)


def match_to_jarvis_task(optimus_filename, optimus_data, jarvis_tasks):
    target_item = get_target_item(optimus_data)

    if target_item and target_item in jarvis_tasks:
        return target_item

    # Normalize plural -> singular
    name_map = {
        "oak_logs": "oak_log", "birch_logs": "birch_log",
        "jungle_logs": "jungle_log", "acacia_logs": "acacia_log",
        "sticks": "stick", "iron_ingots": "iron_ingot",
        "gold_ingots": "gold_ingot", "bowls": "bowl",
    }
    if target_item and target_item in name_map:
        mapped = name_map[target_item]
        if mapped in jarvis_tasks:
            return mapped

    # Try extracting item from filename
    fname = optimus_filename.replace(".json", "").lower()
    for prefix in ["craft_a_", "craft_an_", "craft_", "smelt_a_", "smelt_",
                    "smelt_and_craft_a_"]:
        if fname.startswith(prefix):
            remainder = fname[len(prefix):]
            for suffix in ["_from_planks", "_from_sticks", "_from_logs",
                           "_using_planks", "_using_sticks", "_with_coal",
                           "_from_cobblestone", "_and_sticks", "_and_planks",
                           "_from_sticks_and_planks", "_from_planks_and_sticks",
                           "_using_sticks_and_planks", "_using_planks_and_sticks",
                           "_using_sticks_and_cobblestone", "_from_sticks_and_cobblestone",
                           "_using_sticks_and_birch_planks",
                           "_in_furnace", "_into_iron_ingot", "_into_iron_ingots",
                           "_to_iron_ingots", "_using_furnace", "_using_coal",
                           "_into_stone", "_into_smooth_stone",
                           "_obtained", "_from_logs_obtained"]:
                if remainder.endswith(suffix):
                    remainder = remainder[:-len(suffix)]
                    break
            if remainder in jarvis_tasks:
                return remainder

    return None


def merge_optimus_into_memory(memory_bank, optimus_dir):
    if not os.path.exists(optimus_dir):
        print(f"ERROR: Directory not found: {optimus_dir}")
        print("Please update OPTIMUS_SUCCESS_DIR in the script.")
        return 0, [], []

    jarvis_tasks = set(memory_bank.keys())
    matched_count = 0
    unmatched = []
    matched_details = []

    # Track existing plan signatures to avoid duplicates
    existing_sigs = {}
    for task_name, entry in memory_bank.items():
        existing_sigs[task_name] = set()
        for plan in entry["plans"]:
            existing_sigs[task_name].add(steps_signature(plan["steps"]))

    files = sorted([f for f in os.listdir(optimus_dir) if f.endswith(".json")])
    print(f"Found {len(files)} Optimus-1 success files\n")

    for filename in files:
        filepath = os.path.join(optimus_dir, filename)
        try:
            with open(filepath, "r") as f:
                optimus_data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"  Skipping invalid file: {filename}")
            continue

        jarvis_task = match_to_jarvis_task(filename, optimus_data, jarvis_tasks)
        if jarvis_task is None:
            unmatched.append(filename)
            continue

        added_from_this_file = False
        for plan_entry in optimus_data.get("plan", []):
            if plan_entry.get("status") != "success":
                continue
            if "planning" not in plan_entry or len(plan_entry["planning"]) == 0:
                continue

            converted_steps = convert_optimus_plan(plan_entry)
            sig = steps_signature(converted_steps)

            # Skip if duplicate
            if sig in existing_sigs[jarvis_task]:
                continue

            plan_idx = len(memory_bank[jarvis_task]["plans"])
            new_plan = {
                "plan_id": f"{jarvis_task}_optimus_{plan_idx}",
                "description": f"Optimus-1: {filename.replace('.json', '')}",
                "source": "optimus1_experience",
                "init_inventory": {},
                "steps": converted_steps
            }

            if plan_entry.get("environment") and plan_entry["environment"] != "none":
                new_plan["environment"] = plan_entry["environment"]
            if plan_entry.get("steps", 0) > 0:
                new_plan["total_env_steps"] = plan_entry["steps"]

            memory_bank[jarvis_task]["plans"].append(new_plan)
            existing_sigs[jarvis_task].add(sig)
            matched_count += 1
            added_from_this_file = True

        if added_from_this_file:
            matched_details.append((filename, jarvis_task))

    return matched_count, unmatched, matched_details


if __name__ == "__main__":
    if not os.path.exists(MEMORY_BANK_PATH):
        print(f"ERROR: {MEMORY_BANK_PATH} not found.")
        print("Run convert_jarvis_memory.py first.")
        exit(1)

    with open(MEMORY_BANK_PATH, "r") as f:
        memory_bank = json.load(f)
    print(f"Loaded memory bank with {len(memory_bank)} tasks")

    matched, unmatched, details = merge_optimus_into_memory(memory_bank, OPTIMUS_SUCCESS_DIR)

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Plans added from Optimus-1: {matched}")
    print(f"Files that didn't match: {len(unmatched)}")

    if details:
        print(f"\nMatched files:")
        for fname, task in details:
            print(f"  {fname} -> {task}")

    if unmatched:
        print(f"\nUnmatched files (first 30):")
        for fname in unmatched[:30]:
            print(f"  {fname}")
        if len(unmatched) > 30:
            print(f"  ... and {len(unmatched) - 30} more")

    multi = {k: v for k, v in memory_bank.items() if len(v["plans"]) > 1}
    print(f"\nTasks with multiple plans: {len(multi)}")
    for task_name, entry in sorted(multi.items()):
        print(f"  {task_name}: {len(entry['plans'])} plans")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(memory_bank, f, indent=2)
    print(f"\nSaved to {OUTPUT_PATH}")

    total = sum(len(e["plans"]) for e in memory_bank.values())
    print(f"\nTotal plans: {total}")
    print(f"Tasks with 1 plan: {sum(1 for e in memory_bank.values() if len(e['plans']) == 1)}")
    print(f"Tasks with 2+ plans: {sum(1 for e in memory_bank.values() if len(e['plans']) > 1)}")