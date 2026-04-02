import json
with open("outputs/memory_bank_v3.json") as f:
    data = json.load(f)

entry = data["painting"]
print("item_knowledge:")
for item, info in entry["item_knowledge"].items():
    print(f"  {item}: {info}")