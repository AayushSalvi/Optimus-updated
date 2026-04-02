# create_folder_structure.py
# Run this from your project root (e.g., unified_memory/)

import os

folders = [
    "knowledge_graph",
    "knowledge_graph/data",
    "knowledge_graph/builders",
    "knowledge_graph/tests",
    "memory_bank",
    "memory_bank/outputs",
]

files = [
    "knowledge_graph/__init__.py",
    "knowledge_graph/graph.py",
    "knowledge_graph/data/.gitkeep",
    "knowledge_graph/builders/__init__.py",
    "knowledge_graph/builders/from_vanilla.py",
    "knowledge_graph/builders/from_minecraft_data.py",
    "knowledge_graph/builders/from_minedojo_wiki.py",
    "knowledge_graph/builders/build_all.py",
    "knowledge_graph/tests/__init__.py",
    "knowledge_graph/tests/test_graph.py",
    "memory_bank/__init__.py",
    "memory_bank/convert_jarvis_memory.py",
    "memory_bank/merge_optimus_data.py",
    "memory_bank/fill_from_graph.py",
]

for folder in folders:
    os.makedirs(folder, exist_ok=True)
    print(f"Created folder: {folder}")

for filepath in files:
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            f.write("")
        print(f"Created file:   {filepath}")
    else:
        print(f"Already exists: {filepath}")

print("\nDone! Folder structure ready.")
