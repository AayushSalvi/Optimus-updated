# Unified Memory Bank for Minecraft Agents

Memory bank and knowledge graph for the JARVIS-1 Minecraft agent. Replaces the static plan lookup with a rich, queryable knowledge base built from multiple data sources.

## Overview

The system has two main components:

**Knowledge Graph** — A directed graph storing Minecraft crafting recipes, item properties, mob drops, and item tags. Auto-populated from three sources: JARVIS-1 recipe files, minecraft-data package, and MineDojo wiki.

**Memory Bank** — A per-task JSON structure with multiple plan variants, item-level knowledge, and crafting dependency trees. Built incrementally from JARVIS-1 and Optimus-1 data, enriched by the knowledge graph.

## Project Structure

```
unified_memory/
├── knowledge_graph/
│   ├── graph.py                     # MinecraftKnowledgeGraph class
│   ├── data/
│   │   ├── recipes.json             # 613 items, 848 recipes
│   │   ├── items.json               # 975 items with tool/skill/biome info
│   │   ├── mob_drops.json           # 53 mobs with loot tables
│   │   └── tags.json                # 25 item group aliases
│   ├── builders/
│   │   ├── from_vanilla.py          # Parse JARVIS-1 recipe JSONs
│   │   ├── from_minecraft_data.py   # Extract from minecraft-data package
│   │   └── from_minedojo_wiki.py    # Enrich with biome data from MineDojo wiki
│   └── tests/
│       └── test_graph.py
├── memory_bank/
│   ├── convert_jarvis_memory.py     # JARVIS-1 memory.json → v1
│   ├── merge_optimus_data.py        # + Optimus-1 experience pool → v2
│   ├── fill_from_graph.py           # + knowledge graph → v3
│   └── outputs/
│       └── memory_bank_v3.json      # Final output
```

## Setup

```bash
pip install minecraft-data
```

MineDojo wiki data (optional, for biome enrichment):
```bash
pip install minedojo
```

### External Data (not in repo, download separately)

**JARVIS-1 repo** (for recipe files and base memory.json):
```bash
git clone https://github.com/CraftJarvis/JARVIS-1
```

**Optimus-1 experience pool** (for alternative plan variants in v2):
Download from [HuggingFace](https://huggingface.co/datasets/MinecraftOptimus/Optimus1_Memory/).
The `merge_optimus_data.py` script reads from the `plan/success/` folder.

**MineDojo wiki** (optional, for biome enrichment):
Downloaded via `WikiDataset(full=True, download=True)` — ~6,738 pages.

## Build Pipeline

### Step 1: Build Knowledge Graph Data

```bash
# Parse JARVIS-1 recipes
python knowledge_graph/builders/from_vanilla.py --recipe_dir path/to/JARVIS-1/jarvis/assets/recipes

# Extract items, mob drops, tags from minecraft-data
python knowledge_graph/builders/from_minecraft_data.py --output_dir knowledge_graph/data

# Enrich with biome data from MineDojo wiki
python knowledge_graph/builders/from_minedojo_wiki.py --wiki_dir path/to/minedojo_data/wiki_full --items_path knowledge_graph/data/items.json
```

### Step 2: Build Memory Bank

```bash
# v1: Convert JARVIS-1 memory
python memory_bank/convert_jarvis_memory.py

# v2: Merge Optimus-1 plans
python memory_bank/merge_optimus_data.py

# v3: Fill with knowledge graph data
python memory_bank/fill_from_graph.py --data_dir knowledge_graph/data --memory_bank memory_bank_v2.json --output memory_bank/outputs/memory_bank_v3.json
```

### Test the Graph

```bash
python knowledge_graph/graph.py knowledge_graph/data
```

## Numbers

- 188 tasks in the memory bank
- 1,125 total plans (188 from JARVIS-1, 937 from Optimus-1)
- 636 item knowledge entries with tool requirements, biomes, mob sources
- 181 crafting dependency trees
- 613 unique items with recipes in the knowledge graph
- 975 items with properties
- 53 mobs with loot tables

## Data Sources

| Source | What it provides |
|--------|-----------------|
| JARVIS-1 recipes (860 files) | Crafting/smelting recipes in vanilla Minecraft format |
| minecraft-data package | Item properties, tool requirements, mob loot tables, item tags |
| MineDojo wiki (6,738 pages) | Biome info for trees, mobs, ores |
| JARVIS-1 memory.json | 188 baseline task plans |
| Optimus-1 experience pool | 937 alternative plan variants |

## Related Papers

- JARVIS-1 (Wang et al., 2023) — Base agent framework
- Optimus-1 (Li et al., 2024) — Hybrid multimodal memory, NeurIPS 2024
- HYMEM (Anonymous) — Graph-based hybrid memory for GUI agents
- Planner Matters (Wu et al., 2026) — Planner-centric multi-agent framework
