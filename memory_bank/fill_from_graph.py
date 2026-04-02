"""
fill_from_graph.py — Use the MinecraftKnowledgeGraph to fill memory_bank_v2 → v3

Replaces the old hardcoded fill_knowledge.py with graph-based filling.
Reads item_knowledge and crafting_dependencies from the knowledge graph
built by the three builder scripts.

Usage:
  python fill_from_graph.py --data_dir knowledge_graph/data --memory_bank memory_bank_v2.json --output memory_bank_v3.json
"""

import json
import os
import sys
import argparse

# Add parent dir to path so we can import graph
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge_graph.graph import MinecraftKnowledgeGraph


def resolve_item_name(item_name, graph):
    """Resolve a generic/alias item name to a concrete Minecraft item ID.
    
    JARVIS-1 plans use generic names like 'wool', 'logs', 'log' that don't
    exist as actual Minecraft items. We resolve these by:
    1. Direct match in items.json
    2. Tag match in tags.json (wool -> white_wool, logs -> oak_log)
    3. Common alias mapping (log -> oak_log, etc.)
    """
    # 1. Direct match
    if graph.get_item_info(item_name):
        return item_name
    
    # 2. Tag match — use first concrete item from the tag
    resolved = graph.resolve_tag(item_name)
    if resolved and resolved[0] != item_name:
        # Tag found, use the first item
        return resolved[0]
    
    # 3. Common aliases used in JARVIS-1 and Optimus-1 plans
    aliases = {
        "log": "oak_log",
        "logs": "oak_log",
        "oak_logs": "oak_log",
        "birch_logs": "birch_log",
        "jungle_logs": "jungle_log",
        "acacia_logs": "acacia_log",
        "wool": "white_wool",
        "sticks": "stick",
        "cobble": "cobblestone",
        "plank": "oak_planks",
        "stone_tool_materials": "cobblestone",
        "gold_ores": "gold_ore",
    }
    if item_name in aliases:
        return aliases[item_name]
    
    # 4. Try adding common suffixes
    for suffix in ["_log", "_ore", "_planks"]:
        candidate = item_name + suffix
        if graph.get_item_info(candidate):
            return candidate
    
    # No match found
    return None


def fill_item_knowledge(memory_bank, graph):
    """Fill item_knowledge for all mine steps in each task's plans."""
    filled = 0
    missing = []
    resolved_count = 0
    
    for task_name, entry in memory_bank.items():
        # Collect all mineable items from all plans for this task
        mine_items = set()
        for plan in entry.get("plans", []):
            for step in plan.get("steps", []):
                if step.get("type") == "mine":
                    mine_items.add(step.get("text", ""))
        
        # Build item_knowledge for each mineable item
        knowledge = {}
        for item in mine_items:
            if not item:
                continue
            
            # Try to resolve the item name to a real Minecraft item
            resolved = resolve_item_name(item, graph)
            
            if resolved:
                info = graph.get_item_info(resolved)
                mob = graph.get_mob_for_item(resolved)
                biomes = graph.get_biomes(resolved)
                
                knowledge[item] = {
                    "tool_required": info.get("tool_required") if info else None,
                    "mine_skill": info.get("mine_skill") if info else None,
                    "obtain_methods": info.get("obtain_methods", []) if info else [],
                    "biomes": biomes,
                    "source_mob": mob,
                    "hardness": info.get("hardness") if info else None,
                }
                if resolved != item:
                    knowledge[item]["resolved_from"] = resolved
                    resolved_count += 1
                filled += 1
            else:
                # No match — store with nulls but flag it
                knowledge[item] = {
                    "tool_required": None,
                    "mine_skill": None,
                    "obtain_methods": [],
                    "biomes": None,
                    "source_mob": None,
                    "hardness": None,
                    "unresolved": True,
                }
                filled += 1
        
        if knowledge:
            entry["item_knowledge"] = knowledge
        elif mine_items:
            missing.append(task_name)
    
    return filled, missing, resolved_count


def fill_crafting_dependencies(memory_bank, graph):
    """Fill crafting_dependencies using the graph's dependency tree."""
    filled = 0
    no_recipe = []
    
    for task_name, entry in memory_bank.items():
        dep_tree = graph.get_dependency_tree(task_name)
        
        if dep_tree:
            entry["crafting_dependencies"] = dep_tree
            filled += 1
        else:
            no_recipe.append(task_name)
    
    return filled, no_recipe


def main():
    parser = argparse.ArgumentParser(description="Fill memory bank v2 → v3 using knowledge graph")
    parser.add_argument("--data_dir", required=True, help="Path to knowledge_graph/data/")
    parser.add_argument("--memory_bank", required=True, help="Path to memory_bank_v2.json")
    parser.add_argument("--output", default="memory_bank_v3.json", help="Output path")
    args = parser.parse_args()
    
    # Load graph
    print(f"Loading knowledge graph from {args.data_dir}...")
    graph = MinecraftKnowledgeGraph(args.data_dir)
    graph.stats()
    
    # Load memory bank
    if not os.path.exists(args.memory_bank):
        print(f"\nERROR: {args.memory_bank} not found.")
        return
    
    with open(args.memory_bank, encoding='utf-8') as f:
        memory_bank = json.load(f)
    print(f"\nLoaded memory bank with {len(memory_bank)} tasks")
    
    # Fill item knowledge
    print("\nFilling item_knowledge...")
    items_filled, items_missing, resolved_count = fill_item_knowledge(memory_bank, graph)
    
    # Fill crafting dependencies
    print("Filling crafting_dependencies...")
    deps_filled, no_recipe = fill_crafting_dependencies(memory_bank, graph)
    
    # Save
    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(memory_bank, f, indent=2)
    
    # Stats
    print(f"\n{'='*50}")
    print("RESULTS")
    print(f"{'='*50}")
    print(f"Item knowledge entries filled: {items_filled}")
    print(f"  Resolved via tags/aliases: {resolved_count}")
    if items_missing:
        print(f"Tasks with mine steps but no knowledge: {len(items_missing)}")
    
    print(f"Crafting dependencies filled: {deps_filled}")
    print(f"Tasks without recipes (raw materials): {len(no_recipe)}")
    if no_recipe:
        print(f"  {no_recipe[:15]}")
    
    # Show examples
    print(f"\n{'='*50}")
    print("EXAMPLES")
    print(f"{'='*50}")
    
    for task in ["iron_pickaxe", "diamond_sword", "glass", "white_bed"]:
        if task in memory_bank:
            entry = memory_bank[task]
            print(f"\n--- {task} ---")
            
            # Item knowledge
            ik = entry.get("item_knowledge", {})
            if ik:
                print(f"  Item knowledge ({len(ik)} items):")
                for item, info in ik.items():
                    tool = info.get("tool_required") or "none"
                    skill = info.get("mine_skill") or "?"
                    mob = info.get("source_mob")
                    biomes = info.get("biomes")
                    parts = [f"tool={tool}", f"skill={skill}"]
                    if mob:
                        parts.append(f"mob={mob}")
                    if biomes:
                        parts.append(f"biomes={biomes[:2]}")
                    print(f"    {item}: {', '.join(parts)}")
            
            # Crafting deps
            deps = entry.get("crafting_dependencies", {})
            if deps:
                print(f"  Crafting deps ({len(deps)} steps):")
                for item, recipe in deps.items():
                    ing = recipe.get("ingredients", {})
                    station = recipe.get("requires_station", "?")
                    print(f"    {item}: {ing} @ {station}")
    
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()