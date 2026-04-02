"""
Step 1: Convert JARVIS-1 memory.json into the new enriched memory bank format.

This script:
1. Reads the existing memory.json
2. Wraps each entry into the new structure (plans array, tags, etc.)
3. Extracts all unique mineable items across all tasks
4. Outputs a new JSON file ready to be enriched with Optimus-1 and MineDojo data

Run: python convert_jarvis_memory.py
"""

import json
from collections import defaultdict

# Load JARVIS-1 memory
with open("../JARVIS-1/jarvis/assets/memory.json", "r") as f:
    jarvis_memory = json.load(f)

print(f"Loaded {len(jarvis_memory)} tasks from JARVIS-1 memory.json\n")

# Collect all unique mineable items and their tasks
mine_items = defaultdict(list)  # item -> list of tasks that mine it
all_step_types = set()

for task_name, entry in jarvis_memory.items():
    for step in entry["plan"]:
        all_step_types.add(step["type"])
        if step["type"] == "mine":
            mine_items[step["text"]].append(task_name)

print(f"Step types found: {all_step_types}")
print(f"Unique mineable items: {len(mine_items)}")
print(f"Items: {sorted(mine_items.keys())}\n")

# Items that come from mobs (need source_mob field)
# This should eventually come from knowledge base, not hardcoded
MOB_ITEMS = {
    "wool": {"source_mob": "sheep", "obtain_method": "combat_entity"},
    "white_wool": {"source_mob": "sheep", "obtain_method": "combat_entity"},
    "leather": {"source_mob": "cow", "obtain_method": "combat_entity"},
    "chicken": {"source_mob": "chicken", "obtain_method": "combat_entity"},
    "beef": {"source_mob": "cow", "obtain_method": "combat_entity"},
    "porkchop": {"source_mob": "pig", "obtain_method": "combat_entity"},
    "mutton": {"source_mob": "sheep", "obtain_method": "combat_entity"},
    "string": {"source_mob": "spider", "obtain_method": "combat_entity"},
}

# Items that come from trees
TREE_ITEMS = {
    "logs", "oak_log", "birch_log", "jungle_log", "acacia_log", "apple"
}

# Items that need digging down
UNDERGROUND_ITEMS = {
    "cobblestone", "iron_ore", "gold_ore", "diamond", "redstone", "coal"
}

# Surface items
SURFACE_ITEMS = {
    "sand", "sugar_cane", "yellow_flower", "red_flower", "blue_flower",
    "white_flower", "light_gray_flower", "magenta_flower", "orange_flower",
    "pink_flower"
}


def get_obtain_info(item_name):
    """Determine obtain_method, pre_navigate, source_mob for an item."""
    if item_name in MOB_ITEMS:
        return {
            "obtain_method": MOB_ITEMS[item_name]["obtain_method"],
            "source_mob": MOB_ITEMS[item_name]["source_mob"],
            "pre_navigate": "surface grassland (plains biome)"
        }
    elif item_name in TREE_ITEMS:
        return {
            "obtain_method": "chop_tree",
            "source_mob": None,
            "pre_navigate": None
        }
    elif item_name in UNDERGROUND_ITEMS:
        return {
            "obtain_method": "mine_item",
            "source_mob": None,
            "pre_navigate": "underground/cave"
        }
    elif item_name in SURFACE_ITEMS:
        return {
            "obtain_method": "mine_item",
            "source_mob": None,
            "pre_navigate": None
        }
    else:
        return {
            "obtain_method": "mine_item",
            "source_mob": None,
            "pre_navigate": None
        }


def guess_tags(task_name, plan_steps):
    """Extract tags from the plan steps."""
    tags = set()
    for step in plan_steps:
        tags.add(f"#{step['type']}")
        # Add item-based tags
        if step["type"] == "mine":
            tags.add(f"#{step['text']}")
    # Add the target item
    tags.add(f"#{task_name}")
    return sorted(tags)


def convert_entry(task_name, entry):
    """Convert a single JARVIS-1 memory entry to the new format."""

    # Extract mineable items from this task's plan
    item_knowledge = {}
    for step in entry["plan"]:
        if step["type"] == "mine":
            item_name = step["text"]
            if item_name not in item_knowledge:
                obtain_info = get_obtain_info(item_name)
                item_knowledge[item_name] = {
                    "found_at": "",       # To be filled from MineDojo Wiki
                    "tool_required": "",  # To be filled from MineDojo Wiki
                    "biome": "",          # To be filled from MineDojo Wiki
                    "obtain_method": obtain_info["obtain_method"],
                    "source_mob": obtain_info["source_mob"],
                    "pre_navigate": obtain_info["pre_navigate"],
                    "tips": []            # To be filled from MineDojo Wiki
                }

    new_entry = {
        "task": task_name,
        "tags": guess_tags(task_name, entry["plan"]),

        "plans": [
            {
                "plan_id": f"{task_name}_v1",
                "description": f"Original JARVIS-1 plan for {task_name}",
                "source": "jarvis1_memory",
                "init_inventory": entry.get("init_inventory", {}),
                "steps": entry["plan"]  # Keep exact same format
            }
        ],

        "item_knowledge": item_knowledge,

        "crafting_dependencies": {},  # To be filled from Optimus-1 HDKG

        "strategy": ""  # To be filled later (LLM or manual)
    }

    return new_entry


# Convert all entries
new_memory = {}
for task_name, entry in jarvis_memory.items():
    new_memory[task_name] = convert_entry(task_name, entry)

# Save the converted memory
output_path = "memory_bank_v1.json"
with open(output_path, "w") as f:
    json.dump(new_memory, f, indent=2)

print(f"Converted {len(new_memory)} tasks to new format")
print(f"Saved to {output_path}")

# Print one example to verify
print("\n=== Example: glass ===")
print(json.dumps(new_memory["glass"], indent=2)[:2000])

# Print stats
items_needing_knowledge = set()
for task_name, entry in new_memory.items():
    for item in entry["item_knowledge"]:
        items_needing_knowledge.add(item)

print(f"\n=== Stats ===")
print(f"Total tasks converted: {len(new_memory)}")
print(f"Unique items needing item_knowledge: {len(items_needing_knowledge)}")
print(f"Items: {sorted(items_needing_knowledge)}")
print(f"\nMob items (need source_mob from knowledge base): {sorted(MOB_ITEMS.keys())}")
print(f"Tree items: {sorted(TREE_ITEMS)}")
print(f"Underground items: {sorted(UNDERGROUND_ITEMS)}")
print(f"Surface items: {sorted(SURFACE_ITEMS)}")