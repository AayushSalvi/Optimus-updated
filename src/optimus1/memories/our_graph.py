"""
MinecraftKnowledgeGraph — Core graph class for Minecraft item/recipe knowledge.

Loads all 4 data files (recipes.json, items.json, mob_drops.json, tags.json)
and provides query methods for the Planner.

Directed graph where:
  - Nodes = items/blocks/entities
  - Edges = recipes (craft/smelt/mine/mob_drop)
  - Edge direction: product -> ingredients (forward = "what do I need?")

Usage:
    graph = MinecraftKnowledgeGraph("knowledge_graph/data")
    
    # What ingredients does diamond_sword need?
    graph.get_ingredients("diamond_sword")
    # → {"diamond": 2, "stick": 1}
    
    # What raw materials (things you mine/kill) does diamond_sword need?
    graph.get_raw_materials("diamond_sword")
    # → {"diamond": 2, "logs": 1}
    
    # Full step-by-step plan from scratch
    graph.get_crafting_chain("diamond_sword")
    # → [mine logs, craft planks, craft stick, mine diamond, craft diamond_sword]
    
    # Full plan including tool prerequisites
    graph.get_full_plan("diamond_sword")
    # → [mine logs, craft planks, craft sticks, craft crafting_table, craft wooden_pickaxe,
    #     mine cobblestone, craft stone_pickaxe, mine iron_ore, smelt iron_ingot,
    #     craft iron_pickaxe, mine diamond, craft diamond_sword]
    
    # Human-readable summary for LLM planner prompt
    graph.compile_for_planner("diamond_sword")
"""

import json
import os
from collections import defaultdict, deque


class MinecraftKnowledgeGraph:
    def __init__(self, data_dir):
        """Initialize graph from data directory containing the 4 JSON files."""
        self.data_dir = data_dir
        self.recipes = {}       # item -> [list of recipe variants]
        self.items = {}         # item -> {properties}
        self.mob_drops = {}     # mob -> {drops, hostile, ...}
        self.tags = {}          # tag_name -> [item_names]
        
        # Adjacency lists (built from recipes)
        self.forward = defaultdict(dict)   # product -> {ingredient: qty}
        self.reverse = defaultdict(set)    # ingredient -> set of products
        
        # Mob drop reverse lookup
        self.item_to_mob = {}  # item -> mob that drops it
        
        # Tool tier ordering
        self.tool_tiers = [
            ("wooden_pickaxe", "wooden"),
            ("stone_pickaxe", "stone"),
            ("iron_pickaxe", "iron"),
            ("diamond_pickaxe", "diamond"),
            ("netherite_pickaxe", "netherite"),
        ]
        
        # Items that have recipes but should be treated as raw materials
        # (their recipe is a reverse/decomposition, not the primary way to obtain them)
        self.force_raw = set()
        
        self._load()
        self._identify_force_raw()
        self._build_edges()
        self._build_mob_lookup()
    
    def _identify_force_raw(self):
        """Identify items that have recipes but are primarily obtained by mining/gathering.
        
        For example, diamond has a recipe (from diamond_block) but you primarily mine it.
        We use two approaches:
        1. Explicit list of known mineable items that also have decomposition recipes
        2. Heuristic: if ALL recipes for an item use a "block_of_X" ingredient or are
           smelting from an ore, and the item drops from a mineable block, treat as raw.
        """
        # Explicit list: items you mine/gather, that also happen to have recipes
        # (typically decomposition recipes like diamond_block -> 9 diamonds)
        known_mineable = {
            # Ores and gems that drop themselves
            "diamond", "emerald", "coal", "lapis_lazuli", "redstone",
            "nether_quartz", "flint",
            # Raw ores (1.17+)
            "raw_iron", "raw_gold", "raw_copper",
            # Items that can be crafted from blocks but are primarily mined
            "clay_ball", "glowstone_dust", "melon_slice",
        }
        
        for item_name in known_mineable:
            if item_name in self.recipes:
                self.force_raw.add(item_name)
        
        # Heuristic: check items that have a block variant with drops
        for item_name, item_data in self.items.items():
            if item_name not in self.recipes:
                continue
            # Check if there's a corresponding ore block
            ore_name = item_name + "_ore"
            block_name = item_name + "_block"
            if ore_name in self.items:
                # This item drops from an ore - it's a raw material
                # But only if its recipe is decomposition (from block) or smelting
                recipes = self.recipes[item_name]
                all_secondary = True
                for recipe in recipes:
                    rtype = recipe.get("type", "")
                    ingredients = recipe.get("ingredients", {})
                    ing_names = [k.lstrip("#") for k in ingredients.keys()]
                    
                    is_decomposition = any("block" in n for n in ing_names)
                    is_from_nuggets = any("nugget" in n for n in ing_names)
                    is_smelting = "smelting" in rtype or "blasting" in rtype
                    
                    if not (is_decomposition or is_from_nuggets or is_smelting):
                        all_secondary = False
                        break
                
                if all_secondary:
                    self.force_raw.add(item_name)
    
    # ============================================================
    # LOADING
    # ============================================================
    
    def _load(self):
        """Load all JSON data files."""
        recipes_path = os.path.join(self.data_dir, "recipes.json")
        items_path = os.path.join(self.data_dir, "items.json")
        mob_drops_path = os.path.join(self.data_dir, "mob_drops.json")
        tags_path = os.path.join(self.data_dir, "tags.json")
        
        if os.path.exists(recipes_path):
            with open(recipes_path, encoding='utf-8') as f:
                self.recipes = json.load(f)
        
        if os.path.exists(items_path):
            with open(items_path, encoding='utf-8') as f:
                self.items = json.load(f)
        
        if os.path.exists(mob_drops_path):
            with open(mob_drops_path, encoding='utf-8') as f:
                self.mob_drops = json.load(f)
        
        if os.path.exists(tags_path):
            with open(tags_path, encoding='utf-8') as f:
                self.tags = json.load(f)
    
    def _build_edges(self):
        """Build adjacency lists from recipes. Uses the first recipe variant for each item."""
        self.forward.clear()
        self.reverse.clear()
        
        for product, recipe_list in self.recipes.items():
            if not recipe_list:
                continue
            # Use first recipe variant as the default
            recipe = recipe_list[0]
            ingredients = recipe.get("ingredients", {})
            
            for ingredient, qty in ingredients.items():
                # Resolve tags: "#planks" -> use the tag name without #
                clean_name = ingredient.lstrip("#")
                self.forward[product][clean_name] = qty
                self.reverse[clean_name].add(product)
    
    def _build_mob_lookup(self):
        """Build reverse lookup from dropped item -> mob.
        
        Prefers common passive mobs over rare ones.
        Filters out items that are primarily obtained by crafting
        (like stick from witch, iron_ingot from zombies).
        """
        self.item_to_mob.clear()
        
        # Priority order: prefer common passive mobs the agent actually interacts with
        mob_priority = {
            "cow": 10, "sheep": 10, "pig": 10, "chicken": 10,
            "spider": 8, "zombie": 7, "skeleton": 7, "creeper": 7,
            "horse": 5, "donkey": 4, "llama": 3, "trader_llama": 2,
            "mooshroom": 3, "rabbit": 4, "squid": 5, "enderman": 6,
            "blaze": 6, "ghast": 5, "iron_golem": 4,
        }
        
        # Items that are clearly NOT mob drops as their primary source
        # These are common crafted/mined items that some mobs happen to drop
        not_primarily_mob_drop = {
            "stick", "iron_ingot", "gold_ingot", "redstone", "glass_bottle",
            "sugar", "gunpowder", "carrot", "potato", "iron_shovel",
            "iron_sword", "bow", "arrow", "cod", "bone_meal",
        }
        
        item_best_mob = {}  # item -> (mob_name, priority)
        
        for mob_name, mob_data in self.mob_drops.items():
            priority = mob_priority.get(mob_name, 1)
            for drop in mob_data.get("drops", []):
                item = drop.get("item", "")
                if not item:
                    continue
                if item in not_primarily_mob_drop:
                    continue
                # Keep the highest priority mob for each item
                if item not in item_best_mob or priority > item_best_mob[item][1]:
                    item_best_mob[item] = (mob_name, priority)
        
        for item, (mob, _) in item_best_mob.items():
            self.item_to_mob[item] = mob
    
    # ============================================================
    # TAG RESOLUTION
    # ============================================================
    
    def resolve_tag(self, tag_name):
        """Resolve a tag to its list of concrete items.
        
        'planks' -> ['oak_planks', 'birch_planks', ...]
        'logs' -> ['oak_log', 'birch_log', ...]
        If not a tag, returns [tag_name] (treat as a concrete item).
        """
        clean = tag_name.lstrip("#")
        if clean in self.tags:
            return self.tags[clean]
        return [clean]
    
    def is_tag(self, name):
        """Check if a name is a tag (item group alias)."""
        clean = name.lstrip("#")
        return clean in self.tags
    
    # ============================================================
    # CORE QUERIES
    # ============================================================
    
    def get_recipe(self, item):
        """Return all recipe variants for an item, or None."""
        return self.recipes.get(item, None)
    
    def get_primary_recipe(self, item):
        """Return the first (primary) recipe variant, or None."""
        recipes = self.recipes.get(item)
        if recipes and len(recipes) > 0:
            return recipes[0]
        return None
    
    def get_item_info(self, item):
        """Get item properties from items.json."""
        return self.items.get(item, None)
    
    def get_ingredients(self, item):
        """Direct ingredients for an item (1 level deep).
        
        Returns dict: {ingredient_name: quantity}
        """
        return dict(self.forward.get(item, {}))
    
    def get_products(self, ingredient):
        """What items can this ingredient be used to make?
        
        Returns set of product names.
        """
        clean = ingredient.lstrip("#")
        products = set(self.reverse.get(clean, set()))
        # Also check if this item is part of a tag
        for tag_name, tag_items in self.tags.items():
            if clean in tag_items:
                products.update(self.reverse.get(tag_name, set()))
        return products
    
    def get_mob_for_item(self, item):
        """Get the mob that drops this item, or None."""
        return self.item_to_mob.get(item, None)
    
    def get_tool_required(self, item):
        """Get the minimum tool required to mine/obtain this item."""
        info = self.items.get(item, {})
        return info.get("tool_required", None)
    
    def get_mine_skill(self, item):
        """Get the skill template to use for obtaining this item."""
        info = self.items.get(item, {})
        return info.get("mine_skill", None)
    
    def get_biomes(self, item):
        """Get biome info for an item."""
        info = self.items.get(item, {})
        return info.get("biomes", None)
    
    def is_raw_material(self, item):
        """Check if item must be mined, killed, or gathered.
        
        Returns True if:
        - Item has no recipe, OR
        - Item is in force_raw set (has recipe but primarily obtained by mining)
        """
        if item in self.force_raw:
            return True
        return item not in self.recipes
    
    # ============================================================
    # RECURSIVE QUERIES
    # ============================================================
    
    def get_raw_materials(self, item, qty=1, visited=None):
        """Recursively find all raw materials needed.
        
        Raw = items that must be mined/gathered/killed (no useful recipe,
        or in force_raw set).
        Returns dict: {raw_material_name: total_quantity_needed}
        """
        if visited is None:
            visited = set()
        if item in visited:
            return {}
        visited.add(item)
        
        # If no recipe or force_raw, this IS a raw material
        if item not in self.recipes or item in self.force_raw:
            return {item: qty}
        
        recipe = self.recipes[item][0]  # Use primary recipe
        output_qty = recipe.get("output_qty", 1)
        
        # How many times we need to run this recipe
        batches = -(-qty // output_qty)  # Ceiling division
        
        raw = defaultdict(int)
        for ingredient, ing_qty in recipe.get("ingredients", {}).items():
            clean = ingredient.lstrip("#")
            needed = ing_qty * batches
            sub_raw = self.get_raw_materials(clean, needed, visited.copy())
            for mat, mat_qty in sub_raw.items():
                raw[mat] += mat_qty
        
        return dict(raw)
    
    def get_dependency_tree(self, item, visited=None):
        """Get the full crafting dependency tree (all intermediate recipes).
        
        Returns dict: {item: recipe_dict} for each craftable item in the chain.
        Respects force_raw: items like diamond won't have their decomposition recipe included.
        """
        if visited is None:
            visited = set()
        if item in visited:
            return {}
        visited.add(item)
        
        tree = {}
        if item in self.recipes and item not in self.force_raw:
            recipe = self.recipes[item][0]
            tree[item] = {
                "type": recipe.get("type", "unknown"),
                "ingredients": recipe.get("ingredients", {}),
                "output_qty": recipe.get("output_qty", 1),
                "requires_station": recipe.get("requires_station"),
            }
            for ingredient in recipe.get("ingredients", {}):
                clean = ingredient.lstrip("#")
                sub_tree = self.get_dependency_tree(clean, visited.copy())
                tree.update(sub_tree)
        
        return tree
    
    def get_crafting_chain(self, item, qty=1):
        """Topologically sorted step-by-step crafting plan.
        
        Returns list of steps from raw materials to target item.
        Each step: {"step": N, "action": "mine/craft/smelt", "item": name, "qty": N}
        """
        # Collect all items in the dependency tree
        deps = self._collect_deps(item, qty)
        
        # Topological sort
        order = self._topo_sort(deps)
        
        # Build step list
        steps = []
        for i, item_name in enumerate(order):
            info = deps[item_name]
            action = self._infer_action(item_name)
            steps.append({
                "step": i + 1,
                "action": action,
                "item": item_name,
                "qty": info["qty"],
            })
        
        return steps
    
    def _collect_deps(self, item, qty, collected=None):
        """Collect all items needed with quantities. Respects force_raw."""
        if collected is None:
            collected = {}
        
        if item in collected:
            collected[item]["qty"] += qty
            return collected
        
        collected[item] = {"qty": qty, "deps": []}
        
        # Only expand recipe if item is craftable and NOT force_raw
        if item in self.recipes and item not in self.force_raw:
            recipe = self.recipes[item][0]
            output_qty = recipe.get("output_qty", 1)
            batches = -(-qty // output_qty)
            
            for ingredient, ing_qty in recipe.get("ingredients", {}).items():
                clean = ingredient.lstrip("#")
                needed = ing_qty * batches
                collected[item]["deps"].append(clean)
                self._collect_deps(clean, needed, collected)
        
        return collected
    
    def _topo_sort(self, deps):
        """Topological sort: raw materials first, target item last."""
        in_degree = defaultdict(int)
        for item, info in deps.items():
            if item not in in_degree:
                in_degree[item] = 0
            for dep in info["deps"]:
                in_degree[item] += 1  # item depends on dep
        
        # Start with items that have no dependencies (raw materials)
        queue = deque([item for item in deps if in_degree[item] == 0])
        order = []
        
        while queue:
            current = queue.popleft()
            order.append(current)
            
            # Find items that depend on current
            for item, info in deps.items():
                if current in info["deps"]:
                    in_degree[item] -= 1
                    if in_degree[item] == 0:
                        queue.append(item)
        
        # Add any remaining items (handles cycles gracefully)
        for item in deps:
            if item not in order:
                order.append(item)
        
        return order
    
    def _infer_action(self, item):
        """Infer the action type for obtaining an item."""
        # Force raw items are always mined/gathered, even if they have recipes
        if item in self.force_raw or item not in self.recipes:
            info = self.items.get(item, {})
            skill = info.get("mine_skill", "")
            if skill == "chop_tree":
                return "chop"
            if skill == "dig":
                return "dig"
            if item in self.item_to_mob:
                return "kill"
            return "mine"
        
        # Craftable items
        recipe = self.recipes[item][0]
        rtype = recipe.get("type", "")
        if "smelting" in rtype or "blasting" in rtype or "smoking" in rtype:
            return "smelt"
        return "craft"
    
    # ============================================================
    # TOOL PREREQUISITES
    # ============================================================
    
    def infer_required_tools(self, raw_materials):
        """Given raw materials, figure out what tools are needed.
        
        Returns list of tool names in tier order.
        e.g., {"iron_ore": 3} -> ["wooden_pickaxe", "stone_pickaxe"]
              {"diamond": 1} -> ["wooden_pickaxe", "stone_pickaxe", "iron_pickaxe"]
        """
        max_tier = -1
        
        for material in raw_materials:
            tool = self.get_tool_required(material)
            
            # If no tool found, check the ore variant
            # e.g., "diamond" might not have tool_required, but "diamond_ore" does
            if not tool and not material.endswith("_ore"):
                ore_name = material + "_ore"
                tool = self.get_tool_required(ore_name)
            
            if tool:
                for i, (tool_name, tier_prefix) in enumerate(self.tool_tiers):
                    if tool == tool_name:
                        max_tier = max(max_tier, i)
                        break
        
        if max_tier < 0:
            return []
        
        # Need all tools up to and including the required tier
        tools_needed = []
        for i in range(max_tier + 1):
            tools_needed.append(self.tool_tiers[i][0])
        
        return tools_needed
    
    def get_full_plan(self, item, qty=1):
        """Get complete plan including tool prerequisites.
        
        This merges the crafting chain with tool sub-chains.
        Returns a flat list of steps.
        """
        # Get raw materials for target item
        raw = self.get_raw_materials(item, qty)
        
        # Figure out what tools are needed
        tools = self.infer_required_tools(raw)
        
        # Build plan: first craft tools, then craft target
        all_steps = []
        crafted = set()
        
        # Add tool crafting chains
        for tool in tools:
            if tool not in crafted:
                tool_chain = self.get_crafting_chain(tool)
                for step in tool_chain:
                    if step["item"] not in crafted:
                        all_steps.append(step)
                        crafted.add(step["item"])
        
        # Add target item chain
        target_chain = self.get_crafting_chain(item, qty)
        for step in target_chain:
            if step["item"] not in crafted:
                all_steps.append(step)
                crafted.add(step["item"])
        
        # Renumber steps
        for i, step in enumerate(all_steps):
            step["step"] = i + 1
        
        return all_steps
    
    # ============================================================
    # PLANNER INTEGRATION
    # ============================================================
    
    def compile_for_planner(self, item, qty=1):
        """Human-readable summary for LLM planning prompts.
        
        Matches Optimus-1's HDKG output format.
        """
        plan = self.get_full_plan(item, qty)
        
        lines = [f"Plan to obtain {qty}x {item}:"]
        for step in plan:
            action = step["action"]
            item_name = step["item"]
            step_qty = step["qty"]
            
            # Add context
            extra = ""
            tool = self.get_tool_required(item_name)
            if tool and action in ("mine", "dig", "chop"):
                extra = f" (needs {tool})"
            
            biomes = self.get_biomes(item_name)
            if biomes and action in ("mine", "dig", "chop", "kill"):
                biome_str = ", ".join(biomes[:3])
                extra += f" [found in: {biome_str}]"
            
            mob = self.get_mob_for_item(item_name)
            if mob:
                extra += f" (from {mob})"
            
            station = ""
            recipe = self.get_primary_recipe(item_name)
            if recipe and recipe.get("requires_station"):
                station = f" @ {recipe['requires_station']}"
            
            lines.append(f"  {step['step']}. {action} {step_qty}x {item_name}{station}{extra}")
        
        return "\n".join(lines)
    
    def compile_item_knowledge(self, item):
        """Compile item knowledge for the memory bank entry."""
        info = self.items.get(item, {})
        mob = self.get_mob_for_item(item)
        
        knowledge = {
            "tool_required": info.get("tool_required"),
            "mine_skill": info.get("mine_skill"),
            "biomes": info.get("biomes"),
            "obtain_methods": info.get("obtain_methods", []),
            "source_mob": mob,
            "hardness": info.get("hardness"),
        }
        
        return knowledge
    
    # ============================================================
    # MEMORY BANK EXPORT
    # ============================================================
    
    def export_item_knowledge_for_plan(self, plan_steps):
        """Given plan steps, export item_knowledge for all mineable items."""
        knowledge = {}
        for step in plan_steps:
            if step.get("type") == "mine":
                item = step.get("text", "")
                if item:
                    knowledge[item] = self.compile_item_knowledge(item)
        return knowledge
    
    def export_dependencies(self, item):
        """Export dependency tree in memory bank format."""
        return self.get_dependency_tree(item)
    
    # ============================================================
    # STATS
    # ============================================================
    
    def stats(self):
        """Print graph statistics."""
        print(f"Recipes:    {len(self.recipes)} items with recipes")
        print(f"Items:      {len(self.items)} items with properties")
        print(f"Mob drops:  {len(self.mob_drops)} mobs")
        print(f"Tags:       {len(self.tags)} tag groups")
        print(f"Edges:      {sum(len(v) for v in self.forward.values())} ingredient edges")
        print(f"Force raw:  {len(self.force_raw)} items treated as raw despite having recipes")
        if self.force_raw:
            print(f"            {sorted(self.force_raw)}")
        
        # Items with biomes
        biome_count = sum(1 for i in self.items.values() if i.get("biomes"))
        print(f"With biomes: {biome_count} items")
        
        # Most used ingredients
        if self.reverse:
            top = sorted(self.reverse.items(), key=lambda x: len(x[1]), reverse=True)[:5]
            print(f"Top ingredients: {', '.join(f'{k} ({len(v)} uses)' for k, v in top)}")


# ============================================================
# DEMO / TEST
# ============================================================

if __name__ == "__main__":
    import sys
    
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "knowledge_graph/data"
    
    print(f"Loading graph from {data_dir}...\n")
    graph = MinecraftKnowledgeGraph(data_dir)
    graph.stats()
    
    # Test basic queries
    print("\n" + "="*60)
    print("BASIC QUERIES")
    print("="*60)
    
    print(f"\nIngredients for diamond_sword: {graph.get_ingredients('diamond_sword')}")
    print(f"Ingredients for iron_pickaxe: {graph.get_ingredients('iron_pickaxe')}")
    print(f"What uses diamond? {sorted(list(graph.get_products('diamond')))[:10]}")
    print(f"Tool for iron_ore: {graph.get_tool_required('iron_ore')}")
    print(f"Tool for diamond_ore: {graph.get_tool_required('diamond_ore')}")
    print(f"Mob for leather: {graph.get_mob_for_item('leather')}")
    print(f"Biomes for oak_log: {graph.get_biomes('oak_log')}")
    
    # Test raw materials
    print("\n" + "="*60)
    print("RAW MATERIALS")
    print("="*60)
    
    for item in ["diamond_sword", "iron_pickaxe", "golden_apple", "white_bed"]:
        raw = graph.get_raw_materials(item)
        print(f"\n{item} needs: {raw}")
    
    # Test crafting chain
    print("\n" + "="*60)
    print("CRAFTING CHAINS")
    print("="*60)
    
    for item in ["diamond_sword", "iron_pickaxe"]:
        chain = graph.get_crafting_chain(item)
        print(f"\n{item}:")
        for step in chain:
            print(f"  {step['step']}. {step['action']} {step['qty']}x {step['item']}")
    
    # Test full plan with tools
    print("\n" + "="*60)
    print("FULL PLAN (with tool prerequisites)")
    print("="*60)
    
    for item in ["diamond_sword", "iron_pickaxe"]:
        print(f"\n{graph.compile_for_planner(item)}")
    
    # Test tag resolution
    print("\n" + "="*60)
    print("TAG RESOLUTION")
    print("="*60)
    
    for tag in ["planks", "logs", "coals", "wool"]:
        print(f"  {tag} -> {graph.resolve_tag(tag)[:5]}...")
    
    # Test dependency tree
    print("\n" + "="*60)
    print("DEPENDENCY TREE")
    print("="*60)
    
    tree = graph.get_dependency_tree("diamond_sword")
    for item, recipe in tree.items():
        print(f"  {item}: {recipe['ingredients']} @ {recipe.get('requires_station', 'N/A')}")