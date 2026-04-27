"""Deterministic world-delta computation for Minecraft observations.

Replaces Wenyi's compute_window_delta (a11y/URL diff). Pure Python, no LLM.
Inputs are Optimus-1 status fields: inventory, location_stats, equipment.
"""
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional


@dataclass
class WorldDelta:
    inventory_added: Dict[str, int] = field(default_factory=dict)
    inventory_removed: Dict[str, int] = field(default_factory=dict)
    position_before: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    position_after: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    position_delta: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dimension_before: str = "overworld"
    dimension_after: str = "overworld"
    dimension_changed: bool = False
    equipped_before: str = "none"
    equipped_after: str = "none"
    equipment_changed: bool = False

    @property
    def is_empty(self) -> bool:
        return (
            not self.inventory_added
            and not self.inventory_removed
            and not self.dimension_changed
            and not self.equipment_changed
            and abs(self.position_delta[1]) < 0.5  # vertical movement matters most
            and (self.position_delta[0] ** 2 + self.position_delta[2] ** 2) < 4.0
        )

    def to_prompt_block(self) -> str:
        if self.is_empty:
            return "[World Delta]\n  (no significant change)"
        lines = ["[World Delta — computed from env observations, not interpretation]"]
        if self.inventory_added:
            adds = ", ".join(f"+{c} {k}" for k, c in self.inventory_added.items())
            lines.append(f"  inventory gained: {adds}")
        if self.inventory_removed:
            rems = ", ".join(f"-{c} {k}" for k, c in self.inventory_removed.items())
            lines.append(f"  inventory lost: {rems}")
        if self.dimension_changed:
            lines.append(f"  dimension: {self.dimension_before} → {self.dimension_after}")
        if self.equipment_changed:
            lines.append(f"  equipped: {self.equipped_before} → {self.equipped_after}")
        dx, dy, dz = self.position_delta
        if abs(dy) >= 0.5 or (dx ** 2 + dz ** 2) >= 4.0:
            lines.append(f"  position: {self.position_before} → {self.position_after} (Δ=({dx:+.1f},{dy:+.1f},{dz:+.1f}))")
        return "\n".join(lines)


def _to_xyz(loc) -> Tuple[float, float, float]:
    """Read x/y/z from a location_stats dict that may contain tensors."""
    if loc is None:
        return (0.0, 0.0, 0.0)
    def _v(k):
        v = loc.get(k, 0.0)
        try:
            return float(v.item())
        except AttributeError:
            return float(v)
    return (_v("xpos"), _v("ypos"), _v("zpos"))


def _inv_diff(before: Dict[str, int], after: Dict[str, int]) -> Tuple[Dict[str, int], Dict[str, int]]:
    added: Dict[str, int] = {}
    removed: Dict[str, int] = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        b = before.get(k, 0)
        a = after.get(k, 0)
        if a > b:
            added[k] = a - b
        elif b > a:
            removed[k] = b - a
    return added, removed


def compute_world_delta(
    *,
    inv_before: Dict[str, int],
    inv_after: Dict[str, int],
    loc_before: Optional[Dict] = None,
    loc_after: Optional[Dict] = None,
    dim_before: str = "overworld",
    dim_after: str = "overworld",
    equipped_before: str = "none",
    equipped_after: str = "none",
) -> WorldDelta:
    added, removed = _inv_diff(inv_before, inv_after)
    pb = _to_xyz(loc_before)
    pa = _to_xyz(loc_after)
    pd = (pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2])
    return WorldDelta(
        inventory_added=added,
        inventory_removed=removed,
        position_before=pb,
        position_after=pa,
        position_delta=pd,
        dimension_before=dim_before,
        dimension_after=dim_after,
        dimension_changed=(dim_before != dim_after),
        equipped_before=equipped_before,
        equipped_after=equipped_after,
        equipment_changed=(equipped_before != equipped_after),
    )
