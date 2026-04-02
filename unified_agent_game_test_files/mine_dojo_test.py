# # test_minedojo_data.py
# try:
#     from minedojo.data import WikiDataset
#     print("WikiDataset imported successfully!")
    
#     # Try loading a small sample first
#     wiki = WikiDataset(full=False, download=True)
#     print(f"Loaded {len(wiki)} wiki pages")
    
#     # Look at the first item
#     item = wiki[0]
#     print(f"Keys: {item.keys()}")
#     print(f"Title: {item['metadata']['title']}")
#     print(f"URL: {item['metadata']['url']}")
    
#     # Print first few text entries
#     for t in item['texts'][:5]:
#         print(f"  Text: {t['text'][:100]}")
    
# except ImportError as e:
#     print(f"Import failed: {e}")
#     print("MineDojo might need Java/Minecraft for full install")
#     print("Try: pip install minedojo --no-deps")
    
# except Exception as e:
#     print(f"Error: {e}")

# explore_minedojo_wiki.py

# explore_minedojo_wiki.py
# from minedojo.data import WikiDataset
# import json
# import os

# # Load the raw JSON files directly instead of using WikiDataset
# # This avoids the image loading crash
# wiki_dir = os.path.expanduser("~/.minedojo/wiki_samples")

# # Find all JSON files
# json_files = []
# for root, dirs, files in os.walk(wiki_dir):
#     for f in files:
#         if f == "data.json":
#             json_files.append(os.path.join(root, f))

# print(f"Found {len(json_files)} data.json files\n")

# # List all pages
# for jf in json_files:
#     with open(jf, encoding='utf-8') as f:
#         data = json.load(f)
#     title = data['metadata']['title']
#     print(f"  {title} - {data['metadata']['url']}")

# # Deep dive into Diamond page
# print("\n" + "="*60)
# print("LOOKING FOR DIAMOND PAGE")
# print("="*60)

# for jf in json_files:
#     with open(jf, encoding='utf-8') as f:
#         data = json.load(f)
#     if data['metadata']['title'] == 'Diamond':
#         # Print useful texts
#         print("\n--- TEXTS (non-trivial) ---")
#         for t in data['texts']:
#             text = t['text'].strip()
#             if len(text) > 20:
#                 print(f"  {text[:200]}")
        
#         # Print tables
#         print("\n--- TABLES ---")
#         for ti, table in enumerate(data['tables']):
#             headers = table['headers']['text']
#             cells = table['cells']['text']
#             # Filter out empty cells
#             non_empty_cells = [c for c in cells if c.strip()]
#             if non_empty_cells:
#                 print(f"\nTable {ti}:")
#                 if headers:
#                     print(f"  Headers: {headers[:10]}")
#                 print(f"  Cells: {non_empty_cells[:20]}")
#         break


# from minedojo.data import WikiDataset

# wiki = WikiDataset(
#     full=True, 
#     download=True, 
#     download_dir="C:/Data_science_projects/research_task/unified_memory/minedojo_data"
# )
# print(f"Loaded {len(wiki)} wiki pages")


# import json
# import os

# wiki_dir = "C:/Data_science_projects/research_task/unified_memory/minedojo_data"

# # Find all data.json files
# pages = []
# for root, dirs, files in os.walk(wiki_dir):
#     for f in files:
#         if f == "data.json":
#             filepath = os.path.join(root, f)
#             with open(filepath, encoding='utf-8') as file:
#                 data = json.load(file)
#             pages.append(data['metadata']['title'])

# print(f"Total pages: {len(pages)}")

# # Search for our 29 items
# targets = [
#     'Iron Ore', 'Iron', 'Diamond', 'Gold Ore', 'Gold',
#     'Cobblestone', 'Stone', 'Sand', 'Redstone',
#     'Oak Log', 'Oak', 'Birch', 'Jungle', 'Acacia', 'Log',
#     'Sheep', 'Cow', 'Pig', 'Chicken', 'Spider',
#     'Wool', 'Leather', 'Sugar Cane',
#     'Crafting', 'Smelting', 'Mining', 'Furnace'
# ]

# print("\nRelevant pages found:")
# for title in sorted(pages):
#     for target in targets:
#         if target.lower() in title.lower():
#             print(f"  {title}")
#             break


# import os

# wiki_dir = "C:/Data_science_projects/research_task/unified_memory/minedojo_data"
# print("Contents:", os.listdir(wiki_dir))

# # Count data.json files
# count = 0
# for root, dirs, files in os.walk(wiki_dir):
#     for f in files:
#         if f == "data.json":
#             count += 1
# print(f"Total data.json files: {count}")


# import json
# import os

# wiki_dir = "C:/Data_science_projects/research_task/unified_memory/minedojo_data/wiki_full"

# # Find specific pages we need
# targets = ["Iron_Ore", "Diamond_Ore", "Gold_Ore", "Redstone_Dust", 
#            "Coal_Ore", "Sand", "Sheep", "Cow", "Spider", "Oak"]

# for root, dirs, files in os.walk(wiki_dir):
#     if "data.json" in files:
#         folder_name = os.path.basename(root)
#         if folder_name in targets:
#             filepath = os.path.join(root, "data.json")
#             with open(filepath, encoding='utf-8') as f:
#                 data = json.load(f)
            
#             title = data['metadata']['title']
#             print(f"\n{'='*60}")
#             print(f"PAGE: {title}")
#             print(f"{'='*60}")
            
#             # Print non-trivial text entries
#             print("\n--- KEY TEXTS ---")
#             for t in data['texts']:
#                 text = t['text'].strip()
#                 if len(text) > 30 and len(text) < 500:
#                     # Look for useful info
#                     lower = text.lower()
#                     if any(kw in lower for kw in ['level', 'y=', 'spawn', 'biome', 
#                            'obtain', 'mine', 'drop', 'found', 'generate',
#                            'pickaxe', 'tool', 'require']):
#                         print(f"  {text[:300]}")
            
#             # Print first 2 tables with non-empty cells
#             tables_shown = 0
#             for ti, table in enumerate(data.get('tables', [])):
#                 non_empty = [c for c in table['cells']['text'] if c.strip()]
#                 if non_empty and tables_shown < 2:
#                     print(f"\n--- TABLE {ti} ---")
#                     headers = [h for h in table['headers']['text'] if h.strip()]
#                     if headers:
#                         print(f"  Headers: {headers[:8]}")
#                     print(f"  Cells (first 15): {non_empty[:15]}")
#                     tables_shown += 1


# import json
# import os

# wiki_dir = "C:/Data_science_projects/research_task/unified_memory/minedojo_data/wiki_full"

# # Pages we need biome info for (our raw materials + mobs)
# targets = {
#     # Ores
#     "Iron_Ore", "Diamond_Ore", "Gold_Ore", "Coal_Ore", "Redstone_Ore",
#     # Blocks
#     "Sand", "Cobblestone", "Sugar_Cane",
#     # Trees
#     "Oak", "Birch", "Acacia", "Jungle", "Dark_oak",
#     # Mobs
#     "Sheep", "Cow", "Pig", "Chicken", "Spider",
# }

# found = {}
# for root, dirs, files in os.walk(wiki_dir):
#     if "data.json" in files:
#         folder_name = os.path.basename(root)
#         if folder_name in targets:
#             filepath = os.path.join(root, "data.json")
#             with open(filepath, encoding='utf-8') as f:
#                 data = json.load(f)
            
#             title = data['metadata']['title']
            
#             # Get first paragraph (usually has biome info)
#             first_text = ""
#             for t in data['texts']:
#                 text = t['text'].strip()
#                 if len(text) > 40 and "contents" not in text.lower() and "redirect" not in text.lower() and "article is about" not in text.lower():
#                     first_text = text[:300]
#                     break
            
#             # Get Table 0 first cell texts (sometimes has biome list)
#             table0_info = ""
#             if data.get('tables'):
#                 cells = [c for c in data['tables'][0]['cells']['text'] if c.strip()]
#                 headers = [h for h in data['tables'][0]['headers']['text'] if h.strip()]
#                 # Check if any header mentions biome or spawn
#                 for i, h in enumerate(headers):
#                     if any(kw in h.lower() for kw in ['biome', 'spawn']):
#                         if i < len(cells):
#                             table0_info = f"Header '{h}': {cells[i][:200]}"
#                             break
            
#             print(f"\n--- {title} ---")
#             print(f"  Text: {first_text}")
#             if table0_info:
#                 print(f"  Table: {table0_info}")



import json
import os

wiki_dir = "C:/Data_science_projects/research_task/unified_memory/minedojo_data/wiki_full"

for target in ["Sheep", "Cow", "Pig", "Chicken", "Spider", "Sand", "Sugar_Cane", "Cobblestone"]:
    for root, dirs, files in os.walk(wiki_dir):
        if "data.json" in files and os.path.basename(root) == target:
            with open(os.path.join(root, "data.json"), encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"\n--- {target} ---")
            # Show all text entries that mention biome, spawn, grass, desert, forest, plains
            for t in data['texts']:
                text = t['text'].strip()
                lower = text.lower()
                if len(text) > 30 and any(kw in lower for kw in 
                    ['biome', 'spawn', 'grass', 'desert', 'forest', 'plains', 
                     'beach', 'savanna', 'swamp', 'river', 'ocean', 'near water',
                     'overworld', 'underground', 'surface']):
                    print(f"  {text[:250]}")
            break

