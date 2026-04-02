"""
from_minecraft_data.py — Extract item properties, mob drops, and tags from minecraft-data

Input:  minecraft-data Python package (pip install minecraft-data)
Output: 
  - knowledge_graph/data/items.json (item/block properties with tool requirements)
  - knowledge_graph/data/mob_drops.json (entity loot tables)
  - knowledge_graph/data/tags.json (item group aliases for recipe tag resolution)

Usage:
  python -m knowledge_graph.builders.from_minecraft_data
  python from_minecraft_data.py --output_dir knowledge_graph/data
"""

import json
import os
import argparse

try:
    import minecraft_data
except ImportError:
    print("ERROR: minecraft-data not installed. Run: pip install minecraft-data")
    exit(1)


MC_VERSION = "1.16.5"


def build_tool_lookup(mc):
    """Build a lookup from item ID to item name for tool resolution."""
    return {item["id"]: item["name"] for item in mc.items_list}


def get_harvest_tool_names(block, item_lookup):
    """Resolve harvestTools IDs to tool names for a block."""
    tools = []
    for tool_id_str in block.get("harvestTools", {}):
        tool_id = int(tool_id_str)
        if tool_id in item_lookup:
            tools.append(item_lookup[tool_id])
    return tools


def get_minimum_tool(tool_names):
    """From a list of valid harvest tools, find the minimum tier required.
    
    Tool tier order: wooden < stone < iron < diamond < netherite
    Returns the lowest tier tool name, or None if no tool needed.
    """
    tier_order = ["wooden", "stone", "iron", "golden", "diamond", "netherite"]
    
    best_tier = len(tier_order)
    best_tool = None
    
    for tool_name in tool_names:
        for i, tier in enumerate(tier_order):
            if tool_name.startswith(tier):
                if i < best_tier:
                    best_tier = i
                    best_tool = tool_name
                break
    
    return best_tool


def categorize_item(item_name, block_data, recipe_exists):
    """Determine the category of an item based on its properties."""
    # Tools
    tool_keywords = ["pickaxe", "axe", "shovel", "hoe", "sword"]
    if any(item_name.endswith(f"_{kw}") or item_name == kw for kw in tool_keywords):
        return "tool"
    
    # Armor
    armor_keywords = ["helmet", "chestplate", "leggings", "boots"]
    if any(item_name.endswith(f"_{kw}") for kw in armor_keywords):
        return "armor"
    
    # If it's a block that can be mined
    if block_data and not recipe_exists:
        return "raw_material"
    
    # If it has a recipe, it's a craftable/smeltable material
    if recipe_exists:
        return "craftable"
    
    # If it's a block with no recipe (like dirt, sand)
    if block_data:
        return "raw_material"
    
    return "item"


def determine_obtain_methods(item_name, block_data, has_recipe, mob_drop_items):
    """Figure out how an item can be obtained."""
    methods = []
    
    if has_recipe:
        methods.append("craft")
    
    if block_data and block_data.get("diggable"):
        methods.append("mine")
    
    if item_name in mob_drop_items:
        methods.append("mob_drop")
    
    if not methods:
        methods.append("unknown")
    
    return methods


def determine_mine_skill(item_name, block_data):
    """Determine what skill template the agent should use to obtain this item."""
    if not block_data:
        return None
    
    material = block_data.get("material", "")
    
    # Wood-based blocks
    if material == "wood" or "log" in item_name or "wood" in item_name:
        return "chop_tree"
    
    # Underground ores
    ore_items = {"iron_ore", "gold_ore", "diamond_ore", "redstone_ore",
                 "coal_ore", "lapis_ore", "emerald_ore", "nether_gold_ore",
                 "nether_quartz_ore", "ancient_debris"}
    if item_name in ore_items:
        return "mine_item"
    
    # Stone-like materials (cobblestone comes from mining stone)
    if material == "rock" or item_name in {"cobblestone", "stone", "netherrack",
                                            "end_stone", "sandstone"}:
        return "mine_item"
    
    # Dirt/sand (diggable surface blocks)
    if material == "dirt" or item_name in {"sand", "gravel", "clay", "soul_sand"}:
        return "dig"
    
    # Plants
    if material in ("plant", "leaves") or item_name in {"sugar_cane", "wheat",
                                                          "cactus", "bamboo"}:
        return "mine_item"
    
    return "mine_item"


def build_items(mc, recipes, mob_drop_items):
    """Build items.json from minecraft-data."""
    item_lookup = build_tool_lookup(mc)
    items = {}
    
    # Process all items
    for item in mc.items_list:
        name = item["name"]
        
        # Check if this item has a corresponding block
        block = mc.blocks_name.get(name)
        
        # Check if this item has recipes
        has_recipe = name in recipes
        
        # Build item entry
        entry = {
            "display_name": item.get("displayName", name),
            "category": categorize_item(name, block, has_recipe),
            "obtain_methods": determine_obtain_methods(name, block, has_recipe, mob_drop_items),
            "stackable": item.get("stackSize", 64) > 1,
            "max_stack": item.get("stackSize", 64),
        }
        
        # Add block-specific properties
        if block:
            # Tool requirements
            harvest_tools = get_harvest_tool_names(block, item_lookup)
            min_tool = get_minimum_tool(harvest_tools)
            
            if min_tool:
                entry["tool_required"] = min_tool
                entry["harvest_tools"] = harvest_tools
            else:
                entry["tool_required"] = None
            
            entry["hardness"] = block.get("hardness", 0)
            entry["material"] = block.get("material", "")
            entry["mine_skill"] = determine_mine_skill(name, block)
            
            # Resolve drop items
            drop_names = []
            for drop_id in block.get("drops", []):
                if drop_id in item_lookup:
                    drop_names.append(item_lookup[drop_id])
            if drop_names:
                entry["block_drops"] = drop_names
        
        items[name] = entry
    
    return items


def build_mob_drops(mc):
    """Build mob_drops.json from minecraft-data entityLoot."""
    mob_drops = {}
    mob_drop_items = set()  # Track all items that come from mobs
    
    # Entity categories
    for entry in mc.entityLoot_list:
        mob_name = entry["entity"]
        drops = []
        
        for drop in entry.get("drops", []):
            drop_entry = {
                "item": drop["item"],
                "drop_chance": drop.get("dropChance", 1),
                "stack_range": drop.get("stackSizeRange", [1, 1]),
            }
            drops.append(drop_entry)
            mob_drop_items.add(drop["item"])
        
        if drops:
            # Get entity info
            entity = mc.entities_name.get(mob_name, {})
            
            mob_drops[mob_name] = {
                "display_name": entity.get("displayName", mob_name),
                "drops": drops,
                "category": entity.get("category", "unknown"),
                "hostile": entity.get("category", "") in ("Hostile mobs",),
            }
    
    # Manually add wool for sheep (comes from shearing, not in entityLoot)
    if "sheep" in mob_drops:
        mob_drops["sheep"]["drops"].append({
            "item": "white_wool",
            "drop_chance": 1,
            "stack_range": [1, 3],
            "note": "From shearing, not killing"
        })
        mob_drop_items.add("white_wool")
    
    return mob_drops, mob_drop_items


def build_tags():
    """Build tags.json for resolving recipe tag references.
    
    These are the vanilla Minecraft item tags used in recipes.
    minecraft-data doesn't expose tags directly, so we define the
    ones that appear in our parsed recipes.
    """
    tags = {
        # Wood tags (used in many recipes)
        "planks": [
            "oak_planks", "birch_planks", "spruce_planks",
            "jungle_planks", "acacia_planks", "dark_oak_planks",
            "crimson_planks", "warped_planks"
        ],
        "logs": [
            "oak_log", "birch_log", "spruce_log",
            "jungle_log", "acacia_log", "dark_oak_log"
        ],
        "logs_that_burn": [
            "oak_log", "birch_log", "spruce_log",
            "jungle_log", "acacia_log", "dark_oak_log",
            "stripped_oak_log", "stripped_birch_log", "stripped_spruce_log",
            "stripped_jungle_log", "stripped_acacia_log", "stripped_dark_oak_log",
            "oak_wood", "birch_wood", "spruce_wood",
            "jungle_wood", "acacia_wood", "dark_oak_wood"
        ],
        "acacia_logs": ["acacia_log", "stripped_acacia_log", "acacia_wood", "stripped_acacia_wood"],
        "birch_logs": ["birch_log", "stripped_birch_log", "birch_wood", "stripped_birch_wood"],
        "dark_oak_logs": ["dark_oak_log", "stripped_dark_oak_log", "dark_oak_wood", "stripped_dark_oak_wood"],
        "jungle_logs": ["jungle_log", "stripped_jungle_log", "jungle_wood", "stripped_jungle_wood"],
        "oak_logs": ["oak_log", "stripped_oak_log", "oak_wood", "stripped_oak_wood"],
        "spruce_logs": ["spruce_log", "stripped_spruce_log", "spruce_wood", "stripped_spruce_wood"],
        "crimson_stems": ["crimson_stem", "stripped_crimson_stem", "crimson_hyphae", "stripped_crimson_hyphae"],
        "warped_stems": ["warped_stem", "stripped_warped_stem", "warped_hyphae", "stripped_warped_hyphae"],
        
        # Stone tags
        "stone_crafting_materials": ["cobblestone", "blackstone"],
        "stone_tool_materials": ["cobblestone", "blackstone"],
        
        # Wool and dye tags
        "wool": [
            "white_wool", "orange_wool", "magenta_wool", "light_blue_wool",
            "yellow_wool", "lime_wool", "pink_wool", "gray_wool",
            "light_gray_wool", "cyan_wool", "purple_wool", "blue_wool",
            "brown_wool", "green_wool", "red_wool", "black_wool"
        ],
        
        # Fuel tags
        "coals": ["coal", "charcoal"],
        
        # Sand
        "sand": ["sand", "red_sand"],
        
        # Misc tags used in recipes
        "wooden_slabs": [
            "oak_slab", "birch_slab", "spruce_slab",
            "jungle_slab", "acacia_slab", "dark_oak_slab"
        ],
        "wooden_buttons": [
            "oak_button", "birch_button", "spruce_button",
            "jungle_button", "acacia_button", "dark_oak_button"
        ],
        "wooden_doors": [
            "oak_door", "birch_door", "spruce_door",
            "jungle_door", "acacia_door", "dark_oak_door"
        ],
        "wooden_fences": [
            "oak_fence", "birch_fence", "spruce_fence",
            "jungle_fence", "acacia_fence", "dark_oak_fence"
        ],
        "wooden_pressure_plates": [
            "oak_pressure_plate", "birch_pressure_plate", "spruce_pressure_plate",
            "jungle_pressure_plate", "acacia_pressure_plate", "dark_oak_pressure_plate"
        ],
        "wooden_stairs": [
            "oak_stairs", "birch_stairs", "spruce_stairs",
            "jungle_stairs", "acacia_stairs", "dark_oak_stairs"
        ],
        "wooden_trapdoors": [
            "oak_trapdoor", "birch_trapdoor", "spruce_trapdoor",
            "jungle_trapdoor", "acacia_trapdoor", "dark_oak_trapdoor"
        ],
        
        # Flower tags
        "flowers": [
            "dandelion", "poppy", "blue_orchid", "allium",
            "azure_bluet", "red_tulip", "orange_tulip", "white_tulip",
            "pink_tulip", "oxeye_daisy", "cornflower", "lily_of_the_valley",
            "sunflower", "lilac", "rose_bush", "peony"
        ],
        "small_flowers": [
            "dandelion", "poppy", "blue_orchid", "allium",
            "azure_bluet", "red_tulip", "orange_tulip", "white_tulip",
            "pink_tulip", "oxeye_daisy", "cornflower", "lily_of_the_valley"
        ],
    }
    
    return tags


def main():
    parser = argparse.ArgumentParser(description="Extract data from minecraft-data package")
    parser.add_argument("--output_dir", default="knowledge_graph/data", help="Output directory")
    parser.add_argument("--version", default="1.16.5", help="Minecraft version")
    args = parser.parse_args()
    
    print(f"Loading minecraft-data for version {args.version}...")
    mc = minecraft_data(args.version)
    
    # Load existing recipes to check which items are craftable
    recipes_path = os.path.join(args.output_dir, "recipes.json")
    recipes = {}
    if os.path.exists(recipes_path):
        with open(recipes_path, encoding="utf-8") as f:
            recipes = json.load(f)
        print(f"Loaded {len(recipes)} recipes from {recipes_path}")
    else:
        print(f"WARNING: {recipes_path} not found. Run from_vanilla.py first.")
        print("Continuing without recipe data...\n")
    
    # Build mob drops first (we need the item set for build_items)
    print("Building mob drops...")
    mob_drops, mob_drop_items = build_mob_drops(mc)
    
    # Build items
    print("Building items...")
    items = build_items(mc, recipes, mob_drop_items)
    
    # Build tags
    print("Building tags...")
    tags = build_tags()
    
    # Ensure output directory exists
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Save items.json
    items_path = os.path.join(args.output_dir, "items.json")
    with open(items_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    
    # Save mob_drops.json
    mob_drops_path = os.path.join(args.output_dir, "mob_drops.json")
    with open(mob_drops_path, "w", encoding="utf-8") as f:
        json.dump(mob_drops, f, indent=2)
    
    # Save tags.json
    tags_path = os.path.join(args.output_dir, "tags.json")
    with open(tags_path, "w", encoding="utf-8") as f:
        json.dump(tags, f, indent=2)
    
    # Print stats
    print(f"\n{'='*50}")
    print("RESULTS")
    print(f"{'='*50}")
    print(f"Items:     {len(items)} → {items_path}")
    print(f"Mob drops: {len(mob_drops)} mobs → {mob_drops_path}")
    print(f"Tags:      {len(tags)} tag groups → {tags_path}")
    
    # Category breakdown
    categories = {}
    for item_name, item_data in items.items():
        cat = item_data["category"]
        categories[cat] = categories.get(cat, 0) + 1
    print(f"\nItem categories:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    
    # Items with tool requirements
    tool_items = {k: v["tool_required"] for k, v in items.items() if v.get("tool_required")}
    print(f"\nBlocks requiring tools: {len(tool_items)}")
    for item, tool in sorted(tool_items.items())[:15]:
        print(f"  {item}: {tool}")
    if len(tool_items) > 15:
        print(f"  ... and {len(tool_items) - 15} more")
    
    # Mob drop summary
    print(f"\nMob drops:")
    for mob, data in sorted(mob_drops.items()):
        drops = [d["item"] for d in data["drops"]]
        hostile = "hostile" if data["hostile"] else "passive"
        print(f"  {mob} ({hostile}): {drops}")
    
    # Check which recipe tags are covered
    recipe_tags_used = set()
    for item_name, recipe_list in recipes.items():
        for recipe in recipe_list:
            for ingredient in recipe.get("ingredients", {}):
                if ingredient.startswith("#"):
                    recipe_tags_used.add(ingredient[1:])  # Remove # prefix
    
    print(f"\nTags used in recipes: {len(recipe_tags_used)}")
    for tag in sorted(recipe_tags_used):
        resolved = "YES" if tag in tags else "NO"
        print(f"  {tag}: {resolved}")
    
    # Examples
    print(f"\n{'='*50}")
    print("EXAMPLES")
    print(f"{'='*50}")
    for name in ["diamond_ore", "iron_ore", "oak_log", "cobblestone", "sand"]:
        if name in items:
            item = items[name]
            print(f"\n{name}:")
            print(f"  category: {item['category']}")
            print(f"  obtain_methods: {item['obtain_methods']}")
            print(f"  tool_required: {item.get('tool_required')}")
            print(f"  mine_skill: {item.get('mine_skill')}")
            print(f"  hardness: {item.get('hardness')}")


if __name__ == "__main__":
    main()