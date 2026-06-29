"""
Spatial Memory for Optimus-1 agents.

Component 1: coordinate-keyed spatial memory store (write path + retrieval + persistence).

Motivation: STEVE-1 is spatially blind (no map, no location memory, ~6s frame memory),
so resource gathering degenerates into undirected wandering. MineRL exposes ground-truth
(x, y, z) every step (StatusMod.get_position()), so we can record WHERE each resource was
obtained and later retrieve the nearest known location of a needed resource.

This module is pure data + retrieval; it does not change agent behavior on its own.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, List, Optional, Tuple


def _region_key(pos: Tuple[float, float, float], chunk: int = 16) -> str:
    x, y, z = pos
    rx = int(math.floor(x / chunk))
    rz = int(math.floor(z / chunk))
    return f"{rx}_{rz}"


class SpatialMemory:
    def __init__(self, path: Optional[str] = None, chunk: int = 16):
        self.chunk = chunk
        self.path = path or os.path.expanduser(
            "~/Optimus-1/src/optimus1/memories/v1/spatial/spatial_memory.json"
        )
        self.store: Dict[str, List[dict]] = {}
        self._episode: str = "unknown"
        self.load()

    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path) as f:
                    self.store = json.load(f)
        except Exception:
            self.store = {}

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.store, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def set_episode(self, episode_id: str) -> None:
        self._episode = str(episode_id)

    def record(self, resource, pos, biome="unknown", step=-1, quantity=1, outcome="obtained"):
        if resource is None or pos is None:
            return
        entry = {
            "pos": [float(pos[0]), float(pos[1]), float(pos[2])],
            "region": _region_key(pos, self.chunk),
            "biome": biome,
            "step": int(step),
            "episode": self._episode,
            "ts": time.time(),
            "quantity": int(quantity),
            "outcome": outcome,
        }
        self.store.setdefault(resource, []).append(entry)

    def record_from_status(self, status_mod, step: int = -1) -> List[str]:
        recorded: List[str] = []
        try:
            gained = status_mod.inventory_change_what()
            if not gained:
                return recorded
            pos = status_mod.get_position()
            biome = "unknown"
            try:
                loc = getattr(status_mod, "location_stats", {}) or {}
                biome = str(loc.get("biome", loc.get("biome_name", "unknown")))
            except Exception:
                pass
            for item, delta in gained.items():
                self.record(item, pos, biome=biome, step=step, quantity=delta)
                recorded.append(item)
        except Exception:
            return recorded
        return recorded

    def query_nearest(self, resource, current_pos) -> Optional[dict]:
        sightings = self.store.get(resource, [])
        # generic->specific match: "logs" matches any "*_log"; "planks" any "*_planks"; etc.
        if not sightings:
            _cat = str(resource).rstrip("s")  # "logs"->"log"
            merged = []
            for _k, _v in self.store.items():
                if _k == resource or _k.endswith("_" + _cat) or _k.endswith(_cat):
                    merged.extend(_v)
            sightings = merged
        if not sightings:
            return None
        cx, cy, cz = current_pos
        best, best_d = None, float("inf")
        for s in sightings:
            x, y, z = s["pos"]
            d = (x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2
            if d < best_d:
                best_d, best = d, s
        if best is None:
            return None
        out = dict(best)
        out["distance"] = math.sqrt(best_d)
        return out

    def known_resources(self) -> List[str]:
        return sorted(self.store.keys())

    def summary(self) -> str:
        lines = []
        for r in self.known_resources():
            n = len(self.store[r])
            regions = sorted({s["region"] for s in self.store[r]})
            lines.append(f"{r}: {n} sightings across {len(regions)} regions")
        return "\n".join(lines) if lines else "(spatial memory empty)"


if __name__ == "__main__":
    sm = SpatialMemory(path="/tmp/spatial_test.json")
    sm.set_episode("test_ep")
    sm.record("oak_log", (412.3, 67.0, 331.6), biome="forest", step=1480, quantity=4)
    sm.record("oak_log", (380.1, 64.0, 350.8), biome="forest", step=1600, quantity=1)
    sm.record("cobblestone", (379.0, 12.0, 350.0), biome="forest", step=5689, quantity=3)
    print("Known resources:", sm.known_resources())
    print(sm.summary())
    print("Nearest oak_log to (400,65,340):", sm.query_nearest("oak_log", (400.0, 65.0, 340.0)))
    sm.save()
    print("Saved to", sm.path)
