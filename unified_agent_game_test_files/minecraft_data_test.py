# import minecraft_data
# mc = minecraft_data("1.16.5")  # JARVIS-1 uses 1.16

# # Check what's available
# print("Items:", len(mc.items_list))
# print("Recipes:", len(mc.recipes))
# print("Blocks:", len(mc.blocks_list))
# print("Entities:", len(mc.entities_list))

# # Look at iron ore
# iron_ore = mc.blocks_name["iron_ore"]
# print("\nIron ore block data:")
# for k, v in iron_ore.items():
#     print(f"  {k}: {v}")

# # Look at a recipe
# if "iron_pickaxe" in mc.recipes:
#     print("\nIron pickaxe recipe:")
#     print(mc.recipes["iron_pickaxe"])


# import minecraft_data
# mc = minecraft_data("1.16.5")

# # Resolve the harvest tools for iron_ore
# iron_ore = mc.blocks_name["iron_ore"]
# print("=== Iron Ore harvest tools ===")
# for tool_id in iron_ore.get("harvestTools", {}):
#     tool_item = mc.items[int(tool_id)]
#     print(f"  ID {tool_id} = {tool_item['name']}")

# # Resolve drops
# print("\nIron Ore drops:")
# for drop_id in iron_ore.get("drops", []):
#     drop_item = mc.items[drop_id]
#     print(f"  ID {drop_id} = {drop_item['name']}")

# # Check a recipe
# print("\n=== Iron Pickaxe Recipe ===")
# if "iron_pickaxe" in mc.recipes:
#     print(mc.recipes["iron_pickaxe"])
# elif 590 in mc.recipes:
#     print(mc.recipes[590])

# # Check diamond_sword recipe
# print("\n=== Diamond Sword Recipe ===")
# for name in ["diamond_sword"]:
#     item = mc.items_name.get(name)
#     if item:
#         item_id = item["id"]
#         if item_id in mc.recipes:
#             print(mc.recipes[item_id])

# # Check if entities have drop info
# print("\n=== Sheep entity ===")
# sheep = mc.entities_name.get("sheep")
# if sheep:
#     for k, v in sheep.items():
#         print(f"  {k}: {v}")

# # Check a few items we need
# print("\n=== Checking our 29 items ===")
# our_items = ["diamond", "iron_ore", "gold_ore", "cobblestone", "sand",
#              "oak_log", "birch_log", "redstone", "sugar_cane", "leather"]
# for item_name in our_items:
#     item = mc.items_name.get(item_name)
#     block = mc.blocks_name.get(item_name)
#     has_recipe = False
#     if item:
#         has_recipe = item["id"] in mc.recipes
#     print(f"  {item_name}: item={'YES' if item else 'NO'}, block={'YES' if block else 'NO'}, recipe={'YES' if has_recipe else 'NO'}")



# import os
# import json

# recipe_dir = "../JARVIS-1/jarvis/assets"  # Update this to your actual path
# files = [f for f in os.listdir(recipe_dir) if f.endswith('.json')]
# print(f"Total recipe files: {len(files)}")
# print(f"First 10: {files[:10]}")

# # Show one example
# with open(os.path.join(recipe_dir, files[0])) as f:
#     print(f"\nExample ({files[0]}):")
#     print(json.dumps(json.load(f), indent=2))



# import os
# import json

# recipe_dir = "../JARVIS-1/jarvis/assets/recipes"

# # Find examples of each recipe type
# types_seen = {}
# for fname in os.listdir(recipe_dir):
#     if not fname.endswith('.json'):
#         continue
#     with open(os.path.join(recipe_dir, fname)) as f:
#         data = json.load(f)
#     rtype = data.get("type", "unknown")
#     if rtype not in types_seen:
#         types_seen[rtype] = fname

# print(f"Recipe types found: {list(types_seen.keys())}\n")

# # Show one example of each type
# for rtype, fname in types_seen.items():
#     with open(os.path.join(recipe_dir, fname)) as f:
#         data = json.load(f)
#     print(f"=== {rtype} ({fname}) ===")
#     print(json.dumps(data, indent=2)[:600])
#     print()


# import os
# import json

# recipe_dir = "../JARVIS-1/jarvis/assets/recipes"

# # Show specific recipes we care about
# for fname in ["iron_pickaxe.json", "stick.json", "iron_ingot_from_smelting.json", 
#               "charcoal.json", "diamond_sword.json", "white_bed.json"]:
#     fpath = os.path.join(recipe_dir, fname)
#     if os.path.exists(fpath):
#         with open(fpath) as f:
#             data = json.load(f)
#         print(f"=== {fname} ===")
#         print(json.dumps(data, indent=2))
#         print()
#     else:
#         # Try to find it with a different name
#         matches = [f for f in os.listdir(recipe_dir) if fname.split('.')[0] in f]
#         if matches:
#             print(f"=== {fname} not found, but found: {matches} ===")


# import os
# recipe_dir = "../JARVIS-1/jarvis/assets/recipes"
# matches = [f for f in os.listdir(recipe_dir) if "iron_ingot" in f]
# print(matches)


# import json
# recipe_dir = "../JARVIS-1/jarvis/assets/recipes"

# for fname in ["iron_ingot.json", "iron_ingot_from_blasting.json", 
#               "iron_ingot_from_iron_block.json", "iron_ingot_from_nuggets.json"]:
#     with open(f"{recipe_dir}/{fname}") as f:
#         data = json.load(f)
#     print(f"=== {fname} ===")
#     print(json.dumps(data, indent=2))
#     print()

# import minecraft_data
# mc = minecraft_data("1.16.5")

# # Check what attributes are available
# print("Available attributes:")
# attrs = [a for a in dir(mc) if not a.startswith('_')]
# print(attrs)

# # Check if tags exist
# for attr in ['tags', 'item_tags', 'block_tags', 'items_list', 'blocks_list', 'entities_list']:
#     if hasattr(mc, attr):
#         val = getattr(mc, attr)
#         if isinstance(val, list):
#             print(f"\n{attr}: {len(val)} entries")
#             if val:
#                 print(f"  First entry: {val[0]}")
#         elif isinstance(val, dict):
#             print(f"\n{attr}: {len(val)} entries")
#             print(f"  First 5 keys: {list(val.keys())[:5]}")

# # Check a specific block for all its fields
# print("\n=== diamond_ore block (all fields) ===")
# block = mc.blocks_name.get("diamond_ore")
# if block:
#     for k, v in block.items():
#         print(f"  {k}: {v}")

# # Check what entities look like
# print("\n=== cow entity (all fields) ===")
# cow = mc.entities_name.get("cow")
# if cow:
#     for k, v in cow.items():
#         print(f"  {k}: {v}")

# # Resolve harvestTools for diamond_ore
# print("\n=== diamond_ore harvest tools resolved ===")
# if block and "harvestTools" in block:
#     for tool_id in block["harvestTools"]:
#         tool = mc.items[int(tool_id)]
#         print(f"  {tool['name']}")

# import json
# import minecraft_data
# mc = minecraft_data("1.16.5")

# # Check entityLoot - this might have mob drops!
# print("=== entityLoot ===")
# print(f"Total: {len(mc.entityLoot_list)}")
# print(f"First 5 names: {[e['entity'] for e in mc.entityLoot_list[:5]]}")

# # Find sheep drops
# for entry in mc.entityLoot_list:
#     if entry.get("entity") == "sheep":
#         print(f"\nSheep loot:")
#         print(json.dumps(entry, indent=2)[:1000])
#         break

# # Find cow drops
# for entry in mc.entityLoot_list:
#     if entry.get("entity") == "cow":
#         print(f"\nCow loot:")
#         print(json.dumps(entry, indent=2)[:1000])
#         break

# # Check blockLoot
# print("\n=== blockLoot ===")
# print(f"Total: {len(mc.blockLoot_list)}")

# # Find iron_ore drops
# for entry in mc.blockLoot_list:
#     if entry.get("block") == "iron_ore":
#         print(f"\nIron ore loot:")
#         print(json.dumps(entry, indent=2)[:500])
#         break

# # Check biomes
# print("\n=== biomes ===")
# print(f"Total: {len(mc.biomes_list)}")
# print(f"First 5: {[b['name'] for b in mc.biomes_list[:5]]}")


import minecraft_data
import json
mc = minecraft_data("1.16.5")

# Check materials
print("=== materials ===")
print(json.dumps(mc.materials, indent=2)[:2000])

# Check a few more mob drops we need
for mob_name in ["spider", "chicken", "pig", "zombie", "skeleton"]:
    for entry in mc.entityLoot_list:
        if entry.get("entity") == mob_name:
            drops = [d["item"] for d in entry["drops"]]
            print(f"{mob_name}: {drops}")
            break

# Check if sheep drops wool (it showed only mutton above)
# Wool comes from shearing, not killing - let's verify
for entry in mc.entityLoot_list:
    if entry.get("entity") == "sheep":
        print(f"\nSheep full entry:")
        print(json.dumps(entry, indent=2))
        break