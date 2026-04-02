"""
from_vanilla.py — Parse JARVIS-1's vanilla Minecraft recipe JSONs into recipes.json

Input:  860 recipe JSON files from jarvis/assets/recipes/
Output: knowledge_graph/data/recipes.json

Handles these recipe types:
  - crafting_shaped: pattern + key → count symbols for quantities
  - crafting_shapeless: ingredients list → count occurrences
  - smelting / blasting / smoking / campfire_cooking: single ingredient + fuel
  - smithing: base + addition → result
  - stonecutting: single ingredient → result with count
  - crafting_special_*: skipped (no parseable ingredients)

Usage:
  python -m knowledge_graph.builders.from_vanilla --recipe_dir path/to/jarvis/assets/recipes
"""

import json
import os
import argparse
from collections import defaultdict


# Map recipe type to the station required
STATION_MAP = {
    "minecraft:crafting_shaped": "crafting_table",
    "minecraft:crafting_shapeless": "crafting_table",
    "minecraft:smelting": "furnace",
    "minecraft:blasting": "blast_furnace",
    "minecraft:smoking": "smoker",
    "minecraft:campfire_cooking": "campfire",
    "minecraft:stonecutting": "stonecutter",
    "minecraft:smithing": "smithing_table",
}

# Recipe types we skip (no parseable ingredients)
SKIP_TYPES = {
    "minecraft:crafting_special_armordye",
    "minecraft:crafting_special_bannerduplicate",
    "minecraft:crafting_special_bookcloning",
    "minecraft:crafting_special_firework_rocket",
    "minecraft:crafting_special_firework_star",
    "minecraft:crafting_special_mapcloning",
    "minecraft:crafting_special_mapextending",
    "minecraft:crafting_special_repairitem",
    "minecraft:crafting_special_shielddecoration",
    "minecraft:crafting_special_shulkerboxcoloring",
    "minecraft:crafting_special_suspiciousstew",
    "minecraft:crafting_special_tippedarrow",
}


def strip_namespace(name):
    """Remove 'minecraft:' prefix from item/tag names."""
    if name and name.startswith("minecraft:"):
        return name[len("minecraft:"):]
    return name


def resolve_key_entry(entry):
    """Resolve a recipe key entry to an item name.
    
    Entry can be:
      {"item": "minecraft:stick"}           → "stick"
      {"tag": "minecraft:planks"}           → "#planks" (prefixed with # to mark as tag)
      [{"item": "minecraft:coal"}, {"item": "minecraft:charcoal"}]  → "coal"  (take first option)
    """
    if isinstance(entry, list):
        # Multiple options — take first one, but check for tag
        for option in entry:
            if "tag" in option:
                return "#" + strip_namespace(option["tag"])
            if "item" in option:
                return strip_namespace(option["item"])
        return strip_namespace(entry[0].get("item", "unknown"))
    
    if "tag" in entry:
        return "#" + strip_namespace(entry["tag"])
    if "item" in entry:
        return strip_namespace(entry["item"])
    return "unknown"


def parse_shaped(data):
    """Parse a crafting_shaped recipe.
    
    Counts how many times each symbol appears in the pattern,
    then maps symbols to ingredients via the key.
    """
    pattern = data.get("pattern", [])
    key = data.get("key", {})
    
    # Count symbols in pattern (spaces are empty slots)
    symbol_counts = defaultdict(int)
    for row in pattern:
        for char in row:
            if char != " ":
                symbol_counts[char] += 1
    
    # Map symbols to ingredients
    ingredients = {}
    for symbol, count in symbol_counts.items():
        if symbol in key:
            item_name = resolve_key_entry(key[symbol])
            # If same ingredient appears under different symbols, sum them
            if item_name in ingredients:
                ingredients[item_name] += count
            else:
                ingredients[item_name] = count
    
    # Get result
    result = data.get("result", {})
    if isinstance(result, dict):
        output_item = strip_namespace(result.get("item", ""))
        output_qty = result.get("count", 1)
    else:
        output_item = strip_namespace(result)
        output_qty = 1
    
    return {
        "type": "crafting_shaped",
        "ingredients": ingredients,
        "output_qty": output_qty,
        "requires_station": "crafting_table",
    }, output_item


def parse_shapeless(data):
    """Parse a crafting_shapeless recipe.
    
    Counts occurrences of each ingredient in the ingredients list.
    """
    raw_ingredients = data.get("ingredients", [])
    
    ingredients = defaultdict(int)
    for entry in raw_ingredients:
        item_name = resolve_key_entry(entry)
        ingredients[item_name] += 1
    
    result = data.get("result", {})
    if isinstance(result, dict):
        output_item = strip_namespace(result.get("item", ""))
        output_qty = result.get("count", 1)
    else:
        output_item = strip_namespace(result)
        output_qty = 1
    
    return {
        "type": "crafting_shapeless",
        "ingredients": dict(ingredients),
        "output_qty": output_qty,
        "requires_station": "crafting_table",
    }, output_item


def parse_smelting(data, recipe_type):
    """Parse smelting/blasting/smoking/campfire_cooking recipes.
    
    Single ingredient + implicit fuel requirement.
    """
    ingredient_entry = data.get("ingredient", {})
    item_name = resolve_key_entry(ingredient_entry)
    
    result = data.get("result", "")
    if isinstance(result, dict):
        output_item = strip_namespace(result.get("item", ""))
        output_qty = result.get("count", 1)
    else:
        output_item = strip_namespace(result)
        output_qty = 1
    
    clean_type = strip_namespace(recipe_type)
    station = STATION_MAP.get(recipe_type, "furnace")
    
    return {
        "type": clean_type,
        "ingredients": {item_name: 1},
        "output_qty": output_qty,
        "requires_station": station,
        "fuel_required": True,
        "experience": data.get("experience", 0),
        "cookingtime": data.get("cookingtime", 200),
    }, output_item


def parse_stonecutting(data):
    """Parse a stonecutting recipe."""
    ingredient_entry = data.get("ingredient", {})
    item_name = resolve_key_entry(ingredient_entry)
    
    result = data.get("result", "")
    output_item = strip_namespace(result)
    output_qty = data.get("count", 1)
    
    return {
        "type": "stonecutting",
        "ingredients": {item_name: 1},
        "output_qty": output_qty,
        "requires_station": "stonecutter",
    }, output_item


def parse_smithing(data):
    """Parse a smithing recipe (e.g., netherite upgrades)."""
    base = data.get("base", {})
    addition = data.get("addition", {})
    
    base_item = resolve_key_entry(base)
    addition_item = resolve_key_entry(addition)
    
    result = data.get("result", {})
    if isinstance(result, dict):
        output_item = strip_namespace(result.get("item", ""))
        output_qty = result.get("count", 1)
    else:
        output_item = strip_namespace(result)
        output_qty = 1
    
    return {
        "type": "smithing",
        "ingredients": {base_item: 1, addition_item: 1},
        "output_qty": output_qty,
        "requires_station": "smithing_table",
    }, output_item


def parse_recipe_file(filepath):
    """Parse a single recipe JSON file. Returns (recipe_dict, output_item) or (None, None)."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    
    recipe_type = data.get("type", "")
    
    # Skip special recipes with no parseable ingredients
    if recipe_type in SKIP_TYPES:
        return None, None
    
    try:
        if recipe_type == "minecraft:crafting_shaped":
            return parse_shaped(data)
        elif recipe_type == "minecraft:crafting_shapeless":
            return parse_shapeless(data)
        elif recipe_type in ("minecraft:smelting", "minecraft:blasting",
                             "minecraft:smoking", "minecraft:campfire_cooking"):
            return parse_smelting(data, recipe_type)
        elif recipe_type == "minecraft:stonecutting":
            return parse_stonecutting(data)
        elif recipe_type == "minecraft:smithing":
            return parse_smithing(data)
        else:
            print(f"  Unknown recipe type: {recipe_type} in {filepath}")
            return None, None
    except Exception as e:
        print(f"  Error parsing {filepath}: {e}")
        return None, None


def build_recipes(recipe_dir):
    """Parse all recipe files and group by output item.
    
    Returns dict: item_name -> [list of recipe variants]
    """
    recipes = defaultdict(list)
    stats = {
        "total_files": 0,
        "parsed": 0,
        "skipped": 0,
        "errors": 0,
        "by_type": defaultdict(int),
    }
    
    files = sorted([f for f in os.listdir(recipe_dir) if f.endswith(".json")])
    stats["total_files"] = len(files)
    
    for fname in files:
        filepath = os.path.join(recipe_dir, fname)
        recipe, output_item = parse_recipe_file(filepath)
        
        if recipe is None:
            stats["skipped"] += 1
            continue
        
        if output_item:
            recipe["source_file"] = fname
            recipes[output_item].append(recipe)
            stats["parsed"] += 1
            stats["by_type"][recipe["type"]] += 1
        else:
            stats["errors"] += 1
    
    return dict(recipes), stats


def main():
    #C:\Data_science_projects\research_task\unified_memory\JARVIS-1\jarvis\assets\recipes
    parser = argparse.ArgumentParser(description="Parse JARVIS-1 vanilla recipes into recipes.json")
    parser.add_argument("--recipe_dir", required=True, help="/JARVIS-1/jarvis/assets/recipes")
    parser.add_argument("--output", default="../data/recipes.json", help="Output path")
    args = parser.parse_args()
    
    if not os.path.exists(args.recipe_dir):
        print(f"ERROR: Recipe directory not found: {args.recipe_dir}")
        return
    
    print(f"Parsing recipes from: {args.recipe_dir}")
    recipes, stats = build_recipes(args.recipe_dir)
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(recipes, f, indent=2)
    
    # Print stats
    print(f"\n{'='*50}")
    print(f"RESULTS")
    print(f"{'='*50}")
    print(f"Total files:    {stats['total_files']}")
    print(f"Parsed:         {stats['parsed']}")
    print(f"Skipped:        {stats['skipped']} (special recipes)")
    print(f"Errors:         {stats['errors']}")
    print(f"Unique items:   {len(recipes)}")
    print(f"\nBy type:")
    for rtype, count in sorted(stats["by_type"].items()):
        print(f"  {rtype}: {count}")
    
    # Show items with multiple recipe variants
    multi = {k: len(v) for k, v in recipes.items() if len(v) > 1}
    if multi:
        print(f"\nItems with multiple recipes: {len(multi)}")
        for item, count in sorted(multi.items(), key=lambda x: -x[1])[:15]:
            print(f"  {item}: {count} variants")
    
    # Show a few examples
    print(f"\n{'='*50}")
    print("EXAMPLES")
    print(f"{'='*50}")
    for example in ["diamond_sword", "iron_ingot", "stick", "charcoal"]:
        if example in recipes:
            print(f"\n{example}:")
            for r in recipes[example]:
                print(f"  {r['type']}: {r['ingredients']} → {r['output_qty']} @ {r['requires_station']}")
    
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()