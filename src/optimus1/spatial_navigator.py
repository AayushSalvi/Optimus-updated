"""Spatial Navigation (Component 2c): scripted waypoint nav toward a target (x,y,z)
using camera+forward, then hand back to STEVE-1. Intra-episode only. Surface case."""
from __future__ import annotations
import math
from typing import Optional, Tuple
import numpy as np


def _heading_to_target(cur_xz, tgt_xz) -> float:
    dx = tgt_xz[0] - cur_xz[0]
    dz = tgt_xz[1] - cur_xz[1]
    return math.degrees(math.atan2(-dx, dz))


def _yaw_delta(current_yaw, target_yaw) -> float:
    return (target_yaw - current_yaw + 180.0) % 360.0 - 180.0


def _xz(pos): return (pos[0], pos[2])
def _dist_xz(a, b): return math.hypot(a[0] - b[0], a[2] - b[2])


class SpatialNavigator:
    def __init__(self, arrive_radius=5.0, max_nav_steps=200, turn_tolerance=15.0,
                 max_turn_per_step=60.0, progress_window=90, progress_eps=1.0):
        self.arrive_radius = arrive_radius
        self.max_nav_steps = max_nav_steps
        self.turn_tolerance = turn_tolerance
        self.max_turn_per_step = max_turn_per_step
        self.progress_window = progress_window
        self.progress_eps = progress_eps

    def _read_yaw(self, status_mod) -> Optional[float]:
        try:
            loc = getattr(status_mod, "location_stats", {}) or {}
            for k in ("yaw", "Yaw"):
                if k in loc:
                    v = loc[k]
                    return float(v.item() if hasattr(v, "item") else v)
        except Exception:
            pass
        return None

    def navigate(self, env, target_pos, logger=None) -> dict:
        result = {"arrived": False, "steps": 0, "reason": "", "start_dist": None, "end_dist": None}
        try:
            start_pos = env.status_mod.get_position()
            start_dist = _dist_xz(start_pos, target_pos)
            result["start_dist"] = round(start_dist, 1)
            if start_dist <= self.arrive_radius:
                result.update(arrived=True, reason="already_within_radius", end_dist=round(start_dist, 1))
                if logger: logger.info(f"[blue][NAV] already within radius (dist={start_dist:.1f})[/blue]")
                return result
            best_dist = start_dist; best_step = 0
            for step in range(self.max_nav_steps):
                cur = env.status_mod.get_position()
                cur_dist = _dist_xz(cur, target_pos)
                if cur_dist <= self.arrive_radius:
                    result.update(arrived=True, steps=step, reason="arrived", end_dist=round(cur_dist, 1))
                    if logger: logger.info(f"[blue][NAV] arrived in {step} steps (dist={cur_dist:.1f})[/blue]")
                    return result
                if cur_dist < best_dist - 0.1:
                    best_dist = cur_dist; best_step = step
                elif step - best_step > self.progress_window:
                    result.update(arrived=False, steps=step, reason="no_progress_blocked", end_dist=round(cur_dist, 1))
                    if logger: logger.warning(f"[red][NAV] no progress {self.progress_window} steps (dist~{cur_dist:.1f}); bail[/red]")
                    return result
                tgt_yaw = _heading_to_target(_xz(cur), _xz(target_pos))
                cur_yaw = self._read_yaw(env.status_mod)
                action = env.noop_action()
                if cur_yaw is not None:
                    dyaw = _yaw_delta(cur_yaw, tgt_yaw)
                    turn = max(-self.max_turn_per_step, min(self.max_turn_per_step, dyaw))
                    if abs(dyaw) > self.turn_tolerance:
                        action["camera"] = np.array([0.0, turn])
                    action["forward"] = 1
                    if abs(dyaw) < 30.0:
                        action["sprint"] = 1
                else:
                    action["forward"] = 1
                # jump continuously to climb slopes/hills (Minecraft auto-step is only 1 block)
                action["jump"] = 1
                obs, _, done, _ = env.step(action, ["nav", 1])
                result["steps"] = step + 1
                if done:
                    result.update(arrived=False, reason="env_done_during_nav", end_dist=round(cur_dist, 1))
                    if logger: logger.warning("[red][NAV] env ended during nav[/red]")
                    return result
            final = env.status_mod.get_position()
            fd = _dist_xz(final, target_pos)
            result.update(arrived=(fd <= self.arrive_radius), reason="max_steps", end_dist=round(fd, 1))
            if logger: logger.warning(f"[red][NAV] hit max_steps (dist={fd:.1f})[/red]")
            return result
        except Exception as e:
            result["reason"] = f"exception:{e}"
            if logger: logger.warning(f"[NAV] error: {e}")
            return result
