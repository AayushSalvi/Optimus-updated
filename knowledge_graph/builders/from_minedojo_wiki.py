"""
from_minedojo_wiki.py — Extract biome info from MineDojo wiki pages to enrich items.json

Input:  MineDojo wiki_full directory (6,738 data.json files)
Output: Updates items.json with biome fields for raw materials and mobs

Parsing strategy:
  - Trees: Extract from Table 0 "Biomes" header (clean structured data)
  - Mobs: Extract from opening text paragraph (mentions biomes/spawn locations)
  - Ores/blocks: Extract from text or use known defaults

Usage:
  python from_minedojo_wiki.py --wiki_dir path/to/minedojo_data/wiki_full --items_path knowledge_graph/data/items.json
"""

import json
import os
import re
import argparse


def load_wiki_page(wiki_dir, page_name):
    """Load a specific wiki page's data.json."""
    for root, dirs, files in os.walk(wiki_dir):
        if "data.json" in files and os.path.basename(root) == page_name:
            filepath = os.path.join(root, "data.json")
            with open(filepath, encoding='utf-8') as f:
                return json.load(f)
    return None


def extract_biome_from_table(data):
    """Extract biome list from Table 0's 'Biomes' header (works for tree pages)."""
    if not data.get('tables'):
        return None
    
    table = data['tables'][0]
    headers = table.get('headers', {}).get('text', [])
    cells = table.get('cells', {}).get('text', [])
    
    for i, header in enumerate(headers):
        if 'biome' in header.lower():
            if i < len(cells):
                raw = cells[i]
                # Parse biome list: split by newlines, clean up parenthetical notes
                biomes = []
                for line in raw.split('\n'):
                    line = line.strip()
                    if line:
                        # Remove parenthetical notes like "(fancy oak)"
                        clean = re.sub(r'\s*\(.*?\)', '', line).strip()
                        if clean:
                            biomes.append(clean)
                return biomes
    return None


def extract_biome_from_text(data):
    """Extract biome mentions from text paragraphs."""
    biome_keywords = [
        'plains', 'forest', 'desert', 'beach', 'savanna', 'swamp',
        'jungle', 'taiga', 'river', 'ocean', 'mountain', 'meadow',
        'badlands', 'birch forest', 'dark forest', 'overworld',
        'grassy biome', 'grass biome', 'grassy'
    ]
    
    biome_mentions = set()
    
    for t in data.get('texts', []):
        text = t.get('text', '').strip().lower()
        if len(text) < 20:
            continue
        
        for kw in biome_keywords:
            if kw in text:
                biome_mentions.add(kw)
    
    return list(biome_mentions) if biome_mentions else None


def get_opening_description(data):
    """Get the first meaningful paragraph as a description."""
    for t in data.get('texts', []):
        text = t.get('text', '').strip()
        # Skip short, TOC, disambiguation, and redirect texts
        if len(text) < 40:
            continue
        lower = text.lower()
        if any(skip in lower for skip in ['contents', 'redirect', 'article is about',
                                            'for other uses', 'for the ']):
            continue
        # Skip numbered lists (table of contents)
        if re.match(r'^\d+\s', text):
            continue
        return text[:300]
    return None


# ============================================================
# BIOME MAPPINGS
# Maps wiki page names to the items they provide biome info for
# ============================================================

# Wiki page -> list of (item_name, biome_info) tuples
TREE_PAGES = {
    "Oak": ["oak_log"],
    "Birch": ["birch_log"],
    "Acacia": ["acacia_log"],
    "Dark_oak": ["dark_oak_log"],
    "Jungle": ["jungle_log"],
}

MOB_PAGES = {
    "Sheep": ["white_wool", "wool", "mutton"],
    "Cow": ["leather", "beef"],
    "Pig": ["porkchop"],
    "Chicken": ["chicken"],
    "Spider": ["string", "spider_eye"],
}

# Items where biome info is well-known and text parsing is unreliable
KNOWN_BIOMES = {
    "cobblestone": ["any (underground)"],
    "iron_ore": ["any (underground)"],
    "diamond": ["any (deep underground)"],
    "diamond_ore": ["any (deep underground)"],
    "gold_ore": ["any (underground)", "badlands (extra common)"],
    "redstone": ["any (deep underground)"],
    "redstone_ore": ["any (deep underground)"],
    "coal_ore": ["any (underground)"],
    "sand": ["desert", "beach", "river banks", "ocean floors"],
    "sugar_cane": ["any (near water)", "swamp (common)", "desert (very common)"],
    "apple": ["any biome with oak trees"],
    "logs": ["any biome with trees"],
}


def build_biome_enrichment(wiki_dir):
    """Extract biome data from wiki pages."""
    enrichment = {}  # item_name -> {"biomes": [...], "wiki_description": "..."}
    
    # 1. Parse tree pages (have clean table data)
    for page_name, item_names in TREE_PAGES.items():
        data = load_wiki_page(wiki_dir, page_name)
        if not data:
            print(f"  WARNING: Page not found: {page_name}")
            continue
        
        biomes = extract_biome_from_table(data)
        description = get_opening_description(data)
        
        if biomes:
            for item in item_names:
                enrichment[item] = {
                    "biomes": biomes,
                    "wiki_description": description,
                }
            print(f"  {page_name}: {biomes}")
        else:
            # Fallback to text
            biomes = extract_biome_from_text(data)
            if biomes:
                for item in item_names:
                    enrichment[item] = {"biomes": biomes, "wiki_description": description}
                print(f"  {page_name} (from text): {biomes}")
            else:
                print(f"  {page_name}: No biome data found")
    
    # 2. Parse mob pages (biome info in text)
    for page_name, item_names in MOB_PAGES.items():
        data = load_wiki_page(wiki_dir, page_name)
        if not data:
            print(f"  WARNING: Page not found: {page_name}")
            continue
        
        biomes = extract_biome_from_text(data)
        description = get_opening_description(data)
        
        if biomes:
            for item in item_names:
                enrichment[item] = {"biomes": biomes, "wiki_description": description}
            print(f"  {page_name}: {biomes}")
        else:
            print(f"  {page_name}: No biome data found")
    
    # 3. Add known biomes for ores/blocks
    for item, biomes in KNOWN_BIOMES.items():
        if item not in enrichment:
            enrichment[item] = {"biomes": biomes, "wiki_description": None}
    print(f"  Known biomes added for {len(KNOWN_BIOMES)} items")
    
    return enrichment


def enrich_items(items, enrichment):
    """Add biome data to items.json entries."""
    enriched_count = 0
    
    for item_name, biome_data in enrichment.items():
        if item_name in items:
            items[item_name]["biomes"] = biome_data["biomes"]
            if biome_data.get("wiki_description"):
                items[item_name]["wiki_description"] = biome_data["wiki_description"]
            enriched_count += 1
    
    return enriched_count


def main():
    parser = argparse.ArgumentParser(description="Enrich items.json with biome data from MineDojo wiki")
    parser.add_argument("--wiki_dir", required=True, help="Path to MineDojo wiki_full directory")
    parser.add_argument("--items_path", default="knowledge_graph/data/items.json", help="Path to items.json")
    args = parser.parse_args()
    
    if not os.path.exists(args.wiki_dir):
        print(f"ERROR: Wiki directory not found: {args.wiki_dir}")
        return
    
    if not os.path.exists(args.items_path):
        print(f"ERROR: items.json not found: {args.items_path}")
        return
    
    # Load items
    with open(args.items_path, encoding='utf-8') as f:
        items = json.load(f)
    print(f"Loaded {len(items)} items from {args.items_path}")
    
    # Extract biome data from wiki
    print(f"\nParsing wiki pages from {args.wiki_dir}...")
    enrichment = build_biome_enrichment(args.wiki_dir)
    
    # Enrich items
    print(f"\nEnriching items...")
    count = enrich_items(items, enrichment)
    
    # Save
    with open(args.items_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2)
    
    # Stats
    print(f"\n{'='*50}")
    print("RESULTS")
    print(f"{'='*50}")
    print(f"Items enriched with biomes: {count}")
    print(f"Total enrichment entries: {len(enrichment)}")
    
    # Show examples
    print(f"\nExamples:")
    for name in ["oak_log", "iron_ore", "diamond", "white_wool", "sand", "sugar_cane"]:
        if name in items and "biomes" in items[name]:
            print(f"  {name}: {items[name]['biomes']}")
    
    print(f"\nSaved to {args.items_path}")


if __name__ == "__main__":
    main()