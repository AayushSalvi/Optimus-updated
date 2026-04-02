"""
Step 3: Fill item_knowledge and crafting_dependencies in the memory bank.

Since we only have 29 unique mineable items and ~188 crafting tasks,
we build the knowledge directly from verified Minecraft data rather
than parsing wiki HTML.

Sources: Minecraft Wiki (verified manually), Optimus-1 knowledge

Run: python fill_knowledge.py
"""

import json
import os

# ============================================================
# UPDATE THESE PATHS FOR YOUR MACHINE
# ============================================================
MEMORY_BANK_PATH = "memory_bank_v2.json"
OUTPUT_PATH = "memory_bank_v3.json"
# ============================================================

# ============================================================
# ITEM KNOWLEDGE DATABASE
# All 29 mineable items from JARVIS-1's memory.json
# ============================================================

ITEM_KNOWLEDGE_DB = {
    "oak_log": {
        "found_at": "Surface level, from oak trees",
        "tool_required": "None (axe is faster)",
        "biome": "Forest, plains, most overworld biomes",
        "obtain_method": "chop_tree",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Look for nearest tree from spawn", "One tree gives 4-6 logs"]
    },
    "birch_log": {
        "found_at": "Surface level, from birch trees",
        "tool_required": "None (axe is faster)",
        "biome": "Birch forest, forest, plains",
        "obtain_method": "chop_tree",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["White bark, easy to spot", "Common in birch forest biomes"]
    },
    "jungle_log": {
        "found_at": "Surface level, from jungle trees",
        "tool_required": "None (axe is faster)",
        "biome": "Jungle biome only",
        "obtain_method": "chop_tree",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Jungle trees can be very tall (2x2 trunk)", "Jungle biomes are rare"]
    },
    "acacia_log": {
        "found_at": "Surface level, from acacia trees",
        "tool_required": "None (axe is faster)",
        "biome": "Savanna biome",
        "obtain_method": "chop_tree",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Acacia trees have diagonal trunks", "Only found in savanna"]
    },
    "logs": {
        "found_at": "Surface level, from any tree type",
        "tool_required": "None (axe is faster)",
        "biome": "Any biome with trees",
        "obtain_method": "chop_tree",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Any tree works - oak, birch, spruce, jungle, acacia, dark oak"]
    },
    "apple": {
        "found_at": "Drops from oak tree leaves when broken or decayed",
        "tool_required": "None",
        "biome": "Any biome with oak trees",
        "obtain_method": "chop_tree",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Low drop rate from leaves (~0.5%)", "Break oak leaves or wait for decay after chopping trunk"]
    },
    "cobblestone": {
        "found_at": "Anywhere underground, obtained by mining stone blocks",
        "tool_required": "Wooden pickaxe or better",
        "biome": "Any biome",
        "obtain_method": "dig",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Dig 3-4 blocks down from surface to find stone", "Very abundant underground"]
    },
    "iron_ore": {
        "found_at": "Y=72 to Y=-24, most common around Y=16",
        "tool_required": "Stone pickaxe or better",
        "biome": "Any biome, underground",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": "underground/cave",
        "tips": ["Common in caves and ravines", "Need stone pickaxe minimum"]
    },
    "gold_ore": {
        "found_at": "Y=32 to Y=-64, most common below Y=0",
        "tool_required": "Iron pickaxe or better",
        "biome": "Any biome underground; extra common in badlands/mesa",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": "underground/cave",
        "tips": ["Rare in normal biomes", "Much more common in badlands biome", "Need iron pickaxe minimum"]
    },
    "diamond": {
        "found_at": "Y=16 to Y=-64, most common at Y=-59",
        "tool_required": "Iron pickaxe or better",
        "biome": "Any biome, deep underground",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": "underground/cave",
        "tips": ["Branch mining at Y=-59 is most efficient", "Often near lava, bring water bucket", "Fortune enchantment increases drop rate"]
    },
    "redstone": {
        "found_at": "Y=16 to Y=-64, most common below Y=0",
        "tool_required": "Iron pickaxe or better",
        "biome": "Any biome, deep underground",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": "underground/cave",
        "tips": ["Drops 4-5 redstone dust per ore block", "Found at similar depth to diamond"]
    },
    "sand": {
        "found_at": "Surface level, near water bodies",
        "tool_required": "None (shovel is faster)",
        "biome": "Desert, beach, river banks",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Affected by gravity - will fall if block below removed", "Abundant in deserts and beaches"]
    },
    "sugar_cane": {
        "found_at": "Surface level, next to water",
        "tool_required": "None",
        "biome": "Any biome, grows adjacent to water on sand/dirt",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Must be next to water to grow", "Break middle or top block, leave bottom to regrow"]
    },
    "wool": {
        "found_at": "From sheep",
        "tool_required": "Shears (for shearing) or sword (for killing)",
        "biome": "Plains, grass biomes",
        "obtain_method": "combat_entity",
        "source_mob": "sheep",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Shearing gives 1-3 wool without killing", "Killing gives 1 wool", "Sheep regrow wool after eating grass"]
    },
    "white_wool": {
        "found_at": "From white sheep",
        "tool_required": "Shears or sword",
        "biome": "Plains, grass biomes",
        "obtain_method": "combat_entity",
        "source_mob": "sheep",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Most common sheep color is white", "Shearing is more efficient than killing"]
    },
    "leather": {
        "found_at": "From cows",
        "tool_required": "Any weapon",
        "biome": "Plains, grass biomes",
        "obtain_method": "combat_entity",
        "source_mob": "cow",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Cows drop 0-2 leather when killed", "Also drop raw beef"]
    },
    "string": {
        "found_at": "From spiders",
        "tool_required": "Any weapon",
        "biome": "Any biome at night or in dark areas",
        "obtain_method": "combat_entity",
        "source_mob": "spider",
        "pre_navigate": None,
        "tips": ["Spiders spawn at night or in dark areas", "Drop 0-2 string", "Can also find in abandoned mineshafts as cobwebs"]
    },
    "chicken": {
        "found_at": "From chickens (raw chicken drop)",
        "tool_required": "Any weapon",
        "biome": "Plains, forest, most overworld biomes",
        "obtain_method": "combat_entity",
        "source_mob": "chicken",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Drops 1 raw chicken when killed", "Also drops feathers"]
    },
    "beef": {
        "found_at": "From cows (raw beef drop)",
        "tool_required": "Any weapon",
        "biome": "Plains, grass biomes",
        "obtain_method": "combat_entity",
        "source_mob": "cow",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Drops 1-3 raw beef when killed", "Cook in furnace for cooked beef"]
    },
    "porkchop": {
        "found_at": "From pigs (raw porkchop drop)",
        "tool_required": "Any weapon",
        "biome": "Plains, forest, grass biomes",
        "obtain_method": "combat_entity",
        "source_mob": "pig",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Drops 1-3 raw porkchop when killed", "Cook in furnace for cooked porkchop"]
    },
    "mutton": {
        "found_at": "From sheep (raw mutton drop)",
        "tool_required": "Any weapon",
        "biome": "Plains, grass biomes",
        "obtain_method": "combat_entity",
        "source_mob": "sheep",
        "pre_navigate": "surface grassland (plains biome)",
        "tips": ["Drops 1-2 raw mutton when killed", "Also drops wool"]
    },
    "yellow_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Plains, sunflower plains, flower forest",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Dandelions - very common in plains", "Just walk over or break to collect"]
    },
    "red_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Plains, flower forest, most grassy biomes",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Poppies - common in most grassy biomes"]
    },
    "blue_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Flower forest, swamp (blue orchid)",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Cornflower or blue orchid", "Blue orchid only in swamp biome"]
    },
    "white_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Plains, flower forest",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Azure bluet or lily of the valley"]
    },
    "light_gray_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Plains, flower forest",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Oxeye daisy or white tulip"]
    },
    "magenta_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Flower forest",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Allium or lilac", "More common in flower forest biome"]
    },
    "orange_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Plains, flower forest",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Orange tulip"]
    },
    "pink_flower": {
        "found_at": "Surface, in grass/flower areas",
        "tool_required": "None",
        "biome": "Plains, flower forest",
        "obtain_method": "mine_item",
        "source_mob": None,
        "pre_navigate": None,
        "tips": ["Pink tulip or peony"]
    },
}

# ============================================================
# CRAFTING RECIPES DATABASE
# Maps item -> {requires: [...], station: "..."}
# ============================================================

CRAFTING_RECIPES = {
    # Basic materials
    "oak_planks": {"requires": ["oak_log x1"], "station": "inventory"},
    "birch_planks": {"requires": ["birch_log x1"], "station": "inventory"},
    "jungle_planks": {"requires": ["jungle_log x1"], "station": "inventory"},
    "acacia_planks": {"requires": ["acacia_log x1"], "station": "inventory"},
    "planks": {"requires": ["logs x1"], "station": "inventory"},
    "stick": {"requires": ["planks x2"], "station": "inventory"},

    # Workstations
    "crafting_table": {"requires": ["planks x4"], "station": "inventory"},
    "furnace": {"requires": ["cobblestone x8"], "station": "crafting_table"},
    "smoker": {"requires": ["furnace x1", "logs x4"], "station": "crafting_table"},
    "smithing_table": {"requires": ["iron_ingot x2", "planks x4"], "station": "crafting_table"},
    "loom": {"requires": ["string x2", "planks x2"], "station": "crafting_table"},

    # Wooden tools
    "wooden_pickaxe": {"requires": ["planks x3", "stick x2"], "station": "crafting_table"},
    "wooden_axe": {"requires": ["planks x3", "stick x2"], "station": "crafting_table"},
    "wooden_shovel": {"requires": ["planks x1", "stick x2"], "station": "crafting_table"},
    "wooden_hoe": {"requires": ["planks x2", "stick x2"], "station": "crafting_table"},
    "wooden_sword": {"requires": ["planks x2", "stick x1"], "station": "crafting_table"},

    # Stone tools
    "stone_pickaxe": {"requires": ["cobblestone x3", "stick x2"], "station": "crafting_table"},
    "stone_axe": {"requires": ["cobblestone x3", "stick x2"], "station": "crafting_table"},
    "stone_shovel": {"requires": ["cobblestone x1", "stick x2"], "station": "crafting_table"},
    "stone_hoe": {"requires": ["cobblestone x2", "stick x2"], "station": "crafting_table"},
    "stone_sword": {"requires": ["cobblestone x2", "stick x1"], "station": "crafting_table"},

    # Iron tools
    "iron_pickaxe": {"requires": ["iron_ingot x3", "stick x2"], "station": "crafting_table"},
    "iron_axe": {"requires": ["iron_ingot x3", "stick x2"], "station": "crafting_table"},
    "iron_shovel": {"requires": ["iron_ingot x1", "stick x2"], "station": "crafting_table"},
    "iron_hoe": {"requires": ["iron_ingot x2", "stick x2"], "station": "crafting_table"},
    "iron_sword": {"requires": ["iron_ingot x2", "stick x1"], "station": "crafting_table"},

    # Golden tools
    "golden_pickaxe": {"requires": ["gold_ingot x3", "stick x2"], "station": "crafting_table"},
    "golden_axe": {"requires": ["gold_ingot x3", "stick x2"], "station": "crafting_table"},
    "golden_shovel": {"requires": ["gold_ingot x1", "stick x2"], "station": "crafting_table"},
    "golden_hoe": {"requires": ["gold_ingot x2", "stick x2"], "station": "crafting_table"},
    "golden_sword": {"requires": ["gold_ingot x2", "stick x1"], "station": "crafting_table"},

    # Diamond tools
    "diamond_pickaxe": {"requires": ["diamond x3", "stick x2"], "station": "crafting_table"},
    "diamond_axe": {"requires": ["diamond x3", "stick x2"], "station": "crafting_table"},
    "diamond_shovel": {"requires": ["diamond x1", "stick x2"], "station": "crafting_table"},
    "diamond_hoe": {"requires": ["diamond x2", "stick x2"], "station": "crafting_table"},
    "diamond_sword": {"requires": ["diamond x2", "stick x1"], "station": "crafting_table"},

    # Iron armor
    "iron_helmet": {"requires": ["iron_ingot x5"], "station": "crafting_table"},
    "iron_chestplate": {"requires": ["iron_ingot x8"], "station": "crafting_table"},
    "iron_leggings": {"requires": ["iron_ingot x7"], "station": "crafting_table"},
    "iron_boots": {"requires": ["iron_ingot x4"], "station": "crafting_table"},

    # Golden armor
    "golden_helmet": {"requires": ["gold_ingot x5"], "station": "crafting_table"},
    "golden_chestplate": {"requires": ["gold_ingot x8"], "station": "crafting_table"},
    "golden_leggings": {"requires": ["gold_ingot x7"], "station": "crafting_table"},
    "golden_boots": {"requires": ["gold_ingot x4"], "station": "crafting_table"},

    # Diamond armor
    "diamond_helmet": {"requires": ["diamond x5"], "station": "crafting_table"},
    "diamond_chestplate": {"requires": ["diamond x8"], "station": "crafting_table"},
    "diamond_leggings": {"requires": ["diamond x7"], "station": "crafting_table"},
    "diamond_boots": {"requires": ["diamond x4"], "station": "crafting_table"},

    # Leather armor
    "leather_helmet": {"requires": ["leather x5"], "station": "crafting_table"},
    "leather_chestplate": {"requires": ["leather x8"], "station": "crafting_table"},
    "leather_leggings": {"requires": ["leather x7"], "station": "crafting_table"},
    "leather_boots": {"requires": ["leather x4"], "station": "crafting_table"},

    # Smelting
    "iron_ingot": {"requires": ["iron_ore x1", "fuel x1"], "station": "furnace"},
    "gold_ingot": {"requires": ["gold_ore x1", "fuel x1"], "station": "furnace"},
    "glass": {"requires": ["sand x1", "fuel x1"], "station": "furnace"},
    "stone": {"requires": ["cobblestone x1", "fuel x1"], "station": "furnace"},
    "charcoal": {"requires": ["logs x1", "fuel x1"], "station": "furnace"},
    "cooked_chicken": {"requires": ["chicken x1", "fuel x1"], "station": "furnace"},
    "cooked_beef": {"requires": ["beef x1", "fuel x1"], "station": "furnace"},
    "cooked_porkchop": {"requires": ["porkchop x1", "fuel x1"], "station": "furnace"},
    "cooked_mutton": {"requires": ["mutton x1", "fuel x1"], "station": "furnace"},

    # Misc crafting
    "bowl": {"requires": ["planks x3"], "station": "crafting_table"},
    "chest": {"requires": ["planks x8"], "station": "crafting_table"},
    "barrel": {"requires": ["planks x6", "oak_slab x2"], "station": "crafting_table"},
    "composter": {"requires": ["oak_slab x7"], "station": "crafting_table"},
    "bucket": {"requires": ["iron_ingot x3"], "station": "crafting_table"},
    "shears": {"requires": ["iron_ingot x2"], "station": "crafting_table"},
    "shield": {"requires": ["planks x6", "iron_ingot x1"], "station": "crafting_table"},
    "ladder": {"requires": ["stick x7"], "station": "crafting_table"},
    "painting": {"requires": ["stick x8", "wool x1"], "station": "crafting_table"},
    "item_frame": {"requires": ["stick x8", "leather x1"], "station": "crafting_table"},
    "book": {"requires": ["paper x3", "leather x1"], "station": "crafting_table"},
    "paper": {"requires": ["sugar_cane x3"], "station": "crafting_table"},
    "glass_bottle": {"requires": ["glass x3"], "station": "crafting_table"},
    "compass": {"requires": ["iron_ingot x4", "redstone x1"], "station": "crafting_table"},
    "clock": {"requires": ["gold_ingot x4", "redstone x1"], "station": "crafting_table"},

    # Iron items
    "iron_nugget": {"requires": ["iron_ingot x1"], "station": "crafting_table"},
    "iron_bars": {"requires": ["iron_ingot x6"], "station": "crafting_table"},
    "iron_door": {"requires": ["iron_ingot x6"], "station": "crafting_table"},
    "iron_trapdoor": {"requires": ["iron_ingot x4"], "station": "crafting_table"},
    "chain": {"requires": ["iron_nugget x2", "iron_ingot x1"], "station": "crafting_table"},
    "cauldron": {"requires": ["iron_ingot x7"], "station": "crafting_table"},
    "hopper": {"requires": ["iron_ingot x5", "chest x1"], "station": "crafting_table"},
    "heavy_weighted_pressure_plate": {"requires": ["iron_ingot x2"], "station": "crafting_table"},
    "crossbow": {"requires": ["stick x3", "iron_ingot x1", "string x2", "tripwire_hook x1"], "station": "crafting_table"},
    "tripwire_hook": {"requires": ["iron_ingot x1", "stick x1", "planks x1"], "station": "crafting_table"},
    "rail": {"requires": ["iron_ingot x6", "stick x1"], "station": "crafting_table"},
    "activator_rail": {"requires": ["iron_ingot x6", "stick x2", "redstone_torch x1"], "station": "crafting_table"},
    "minecart": {"requires": ["iron_ingot x5"], "station": "crafting_table"},
    "golden_apple": {"requires": ["gold_ingot x8", "apple x1"], "station": "crafting_table"},
    "gold_nugget": {"requires": ["gold_ingot x1"], "station": "crafting_table"},

    # Redstone
    "redstone_torch": {"requires": ["redstone x1", "stick x1"], "station": "crafting_table"},
    "redstone_block": {"requires": ["redstone x9"], "station": "crafting_table"},
    "piston": {"requires": ["planks x3", "cobblestone x4", "iron_ingot x1", "redstone x1"], "station": "crafting_table"},
    "dropper": {"requires": ["cobblestone x7", "redstone x1"], "station": "crafting_table"},
    "note_block": {"requires": ["planks x8", "redstone x1"], "station": "crafting_table"},
    "jukebox": {"requires": ["planks x8", "diamond x1"], "station": "crafting_table"},

    # Wood variants - slabs, boats, doors, etc.
    "oak_slab": {"requires": ["oak_planks x3"], "station": "crafting_table"},
    "birch_slab": {"requires": ["birch_planks x3"], "station": "crafting_table"},
    "jungle_slab": {"requires": ["jungle_planks x3"], "station": "crafting_table"},
    "acacia_slab": {"requires": ["acacia_planks x3"], "station": "crafting_table"},
    "oak_wood": {"requires": ["oak_log x4"], "station": "crafting_table"},
    "birch_wood": {"requires": ["birch_log x4"], "station": "crafting_table"},
    "jungle_wood": {"requires": ["jungle_log x4"], "station": "crafting_table"},
    "acacia_wood": {"requires": ["acacia_log x4"], "station": "crafting_table"},
    "oak_boat": {"requires": ["oak_planks x5"], "station": "crafting_table"},
    "birch_boat": {"requires": ["birch_planks x5"], "station": "crafting_table"},
    "jungle_boat": {"requires": ["jungle_planks x5"], "station": "crafting_table"},
    "acacia_boat": {"requires": ["acacia_planks x5"], "station": "crafting_table"},
    "oak_door": {"requires": ["oak_planks x6"], "station": "crafting_table"},
    "birch_door": {"requires": ["birch_planks x6"], "station": "crafting_table"},
    "jungle_door": {"requires": ["jungle_planks x6"], "station": "crafting_table"},
    "acacia_door": {"requires": ["acacia_planks x6"], "station": "crafting_table"},
    "oak_fence": {"requires": ["oak_planks x4", "stick x2"], "station": "crafting_table"},
    "birch_fence": {"requires": ["birch_planks x4", "stick x2"], "station": "crafting_table"},
    "jungle_fence": {"requires": ["jungle_planks x4", "stick x2"], "station": "crafting_table"},
    "acacia_fence": {"requires": ["acacia_planks x4", "stick x2"], "station": "crafting_table"},
    "oak_fence_gate": {"requires": ["stick x4", "oak_planks x2"], "station": "crafting_table"},
    "birch_fence_gate": {"requires": ["stick x4", "birch_planks x2"], "station": "crafting_table"},
    "jungle_fence_gate": {"requires": ["stick x4", "jungle_planks x2"], "station": "crafting_table"},
    "acacia_fence_gate": {"requires": ["stick x4", "acacia_planks x2"], "station": "crafting_table"},
    "oak_trapdoor": {"requires": ["oak_planks x6"], "station": "crafting_table"},
    "birch_trapdoor": {"requires": ["birch_planks x6"], "station": "crafting_table"},
    "jungle_trapdoor": {"requires": ["jungle_planks x6"], "station": "crafting_table"},
    "acacia_trapdoor": {"requires": ["acacia_planks x6"], "station": "crafting_table"},
    "oak_sign": {"requires": ["oak_planks x6", "stick x1"], "station": "crafting_table"},
    "birch_sign": {"requires": ["birch_planks x6", "stick x1"], "station": "crafting_table"},
    "jungle_sign": {"requires": ["jungle_planks x6", "stick x1"], "station": "crafting_table"},
    "acacia_sign": {"requires": ["acacia_planks x6", "stick x1"], "station": "crafting_table"},
    "oak_button": {"requires": ["oak_planks x1"], "station": "crafting_table"},
    "birch_button": {"requires": ["birch_planks x1"], "station": "crafting_table"},
    "jungle_button": {"requires": ["jungle_planks x1"], "station": "crafting_table"},
    "acacia_button": {"requires": ["acacia_planks x1"], "station": "crafting_table"},

    # Dyes
    "yellow_dye": {"requires": ["yellow_flower x1"], "station": "crafting_table"},
    "red_dye": {"requires": ["red_flower x1"], "station": "crafting_table"},
    "blue_dye": {"requires": ["blue_flower x1"], "station": "crafting_table"},
    "white_dye": {"requires": ["white_flower x1"], "station": "crafting_table"},
    "light_gray_dye": {"requires": ["light_gray_flower x1"], "station": "crafting_table"},
    "magenta_dye": {"requires": ["magenta_flower x1"], "station": "crafting_table"},
    "orange_dye": {"requires": ["orange_flower x1"], "station": "crafting_table"},
    "pink_dye": {"requires": ["pink_flower x1"], "station": "crafting_table"},
    "light_blue_dye": {"requires": ["blue_dye x1", "white_dye x1"], "station": "crafting_table"},
    "purple_dye": {"requires": ["blue_dye x1", "red_dye x1"], "station": "crafting_table"},

    # Colored wool (dye + white wool)
    "yellow_wool": {"requires": ["white_wool x1", "yellow_dye x1"], "station": "crafting_table"},
    "red_wool": {"requires": ["white_wool x1", "red_dye x1"], "station": "crafting_table"},
    "blue_wool": {"requires": ["white_wool x1", "blue_dye x1"], "station": "crafting_table"},
    "light_gray_wool": {"requires": ["white_wool x1", "light_gray_dye x1"], "station": "crafting_table"},
    "magenta_wool": {"requires": ["white_wool x1", "magenta_dye x1"], "station": "crafting_table"},
    "orange_wool": {"requires": ["white_wool x1", "orange_dye x1"], "station": "crafting_table"},
    "pink_wool": {"requires": ["white_wool x1", "pink_dye x1"], "station": "crafting_table"},
    "light_blue_wool": {"requires": ["white_wool x1", "light_blue_dye x1"], "station": "crafting_table"},
    "purple_wool": {"requires": ["white_wool x1", "purple_dye x1"], "station": "crafting_table"},

    # Beds (wool + planks)
    "white_bed": {"requires": ["white_wool x3", "planks x3"], "station": "crafting_table"},
    "yellow_bed": {"requires": ["yellow_wool x3", "planks x3"], "station": "crafting_table"},
    "red_bed": {"requires": ["red_wool x3", "planks x3"], "station": "crafting_table"},
    "blue_bed": {"requires": ["blue_wool x3", "planks x3"], "station": "crafting_table"},
    "light_gray_bed": {"requires": ["light_gray_wool x3", "planks x3"], "station": "crafting_table"},
    "magenta_bed": {"requires": ["magenta_wool x3", "planks x3"], "station": "crafting_table"},
    "orange_bed": {"requires": ["orange_wool x3", "planks x3"], "station": "crafting_table"},
    "pink_bed": {"requires": ["pink_wool x3", "planks x3"], "station": "crafting_table"},
    "light_blue_bed": {"requires": ["light_blue_wool x3", "planks x3"], "station": "crafting_table"},
    "purple_bed": {"requires": ["purple_wool x3", "planks x3"], "station": "crafting_table"},

    # Carpets (wool x2)
    "white_carpet": {"requires": ["white_wool x2"], "station": "crafting_table"},
    "yellow_carpet": {"requires": ["yellow_wool x2"], "station": "crafting_table"},
    "red_carpet": {"requires": ["red_wool x2"], "station": "crafting_table"},
    "blue_carpet": {"requires": ["blue_wool x2"], "station": "crafting_table"},
    "light_gray_carpet": {"requires": ["light_gray_wool x2"], "station": "crafting_table"},
    "magenta_carpet": {"requires": ["magenta_wool x2"], "station": "crafting_table"},
    "orange_carpet": {"requires": ["orange_wool x2"], "station": "crafting_table"},
    "pink_carpet": {"requires": ["pink_wool x2"], "station": "crafting_table"},
    "light_blue_carpet": {"requires": ["light_blue_wool x2"], "station": "crafting_table"},
    "purple_carpet": {"requires": ["purple_wool x2"], "station": "crafting_table"},

    # Banners (wool x6 + stick)
    "white_banner": {"requires": ["white_wool x6", "stick x1"], "station": "crafting_table"},
    "yellow_banner": {"requires": ["yellow_wool x6", "stick x1"], "station": "crafting_table"},
    "red_banner": {"requires": ["red_wool x6", "stick x1"], "station": "crafting_table"},
    "blue_banner": {"requires": ["blue_wool x6", "stick x1"], "station": "crafting_table"},
    "light_gray_banner": {"requires": ["light_gray_wool x6", "stick x1"], "station": "crafting_table"},
    "magenta_banner": {"requires": ["magenta_wool x6", "stick x1"], "station": "crafting_table"},
    "orange_banner": {"requires": ["orange_wool x6", "stick x1"], "station": "crafting_table"},
    "pink_banner": {"requires": ["pink_wool x6", "stick x1"], "station": "crafting_table"},
    "light_blue_banner": {"requires": ["light_blue_wool x6", "stick x1"], "station": "crafting_table"},
    "purple_banner": {"requires": ["purple_wool x6", "stick x1"], "station": "crafting_table"},
}


def get_full_dependency_tree(target_item, recipes, visited=None):
    """Recursively build the full crafting dependency tree for an item."""
    if visited is None:
        visited = set()

    if target_item in visited:
        return {}

    visited.add(target_item)
    tree = {}

    if target_item in recipes:
        tree[target_item] = recipes[target_item]
        # Recursively add dependencies
        for req in recipes[target_item]["requires"]:
            # Parse "item xN" format
            parts = req.rsplit(" x", 1)
            item_name = parts[0]
            if item_name in recipes and item_name not in visited:
                sub_tree = get_full_dependency_tree(item_name, recipes, visited)
                tree.update(sub_tree)

    return tree


def fill_knowledge(memory_bank):
    """Fill item_knowledge and crafting_dependencies in the memory bank."""

    items_filled = 0
    items_missing = []
    deps_filled = 0
    deps_missing = []

    for task_name, entry in memory_bank.items():
        # Fill item_knowledge
        for item_name in list(entry.get("item_knowledge", {}).keys()):
            if item_name in ITEM_KNOWLEDGE_DB:
                entry["item_knowledge"][item_name] = ITEM_KNOWLEDGE_DB[item_name]
                items_filled += 1
            else:
                items_missing.append(item_name)

        # Fill crafting_dependencies
        dep_tree = get_full_dependency_tree(task_name, CRAFTING_RECIPES)
        if dep_tree:
            entry["crafting_dependencies"] = dep_tree
            deps_filled += 1
        else:
            deps_missing.append(task_name)

    return items_filled, items_missing, deps_filled, deps_missing


if __name__ == "__main__":
    if not os.path.exists(MEMORY_BANK_PATH):
        print(f"ERROR: {MEMORY_BANK_PATH} not found.")
        exit(1)

    with open(MEMORY_BANK_PATH, "r") as f:
        memory_bank = json.load(f)
    print(f"Loaded memory bank with {len(memory_bank)} tasks")

    items_filled, items_missing, deps_filled, deps_missing = fill_knowledge(memory_bank)

    print(f"\nItem knowledge: {items_filled} filled")
    if items_missing:
        unique_missing = sorted(set(items_missing))
        print(f"  Missing items ({len(unique_missing)}): {unique_missing}")

    print(f"\nCrafting dependencies: {deps_filled} filled, {len(deps_missing)} missing")
    if deps_missing:
        print(f"  Tasks without recipes (first 20): {deps_missing[:20]}")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(memory_bank, f, indent=2)
    print(f"\nSaved to {OUTPUT_PATH}")

    # Show example
    print("\n=== Example: iron_pickaxe ===")
    ex = memory_bank.get("iron_pickaxe", {})
    print(f"Item knowledge:")
    for item, info in ex.get("item_knowledge", {}).items():
        print(f"  {item}: {info.get('found_at', 'N/A')} | tool: {info.get('tool_required', 'N/A')}")
    print(f"Crafting deps:")
    for item, recipe in ex.get("crafting_dependencies", {}).items():
        print(f"  {item}: {recipe}")