"""
Stagnation Guard (Component 3) for Optimus-1 gathering.
Detects when STEVE-1 wanders in a small area without gathering the target, and
signals the caller to trigger the existing "explore to find X" redirect.
Pure bookkeeping; never raises into the main loop.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Optional, Tuple


class StagnationGuard:
    def __init__(self, window=800, radius=6.0, min_samples=200, cooldown=600):
        self.window = window
        self.radius = radius
        self.min_samples = min_samples
        self.cooldown = cooldown
        self._positions: Deque[Tuple[int, Tuple[float, float, float]]] = deque(maxlen=window)
        self._last_target_count = 0
        self._cooldown_until = -1
        self._current_target: Optional[str] = None

    def reset_for_task(self, target_resource, target_count_now=0):
        self._positions.clear()
        self._current_target = target_resource
        self._last_target_count = target_count_now
        self._cooldown_until = -1

    def update(self, step, pos, target_count_now) -> bool:
        try:
            self._positions.append((step, pos))
            if target_count_now > self._last_target_count:
                self._last_target_count = target_count_now
                self._positions.clear()
                return False
            if step < self._cooldown_until:
                return False
            if len(self._positions) < max(self.min_samples, self.window // 2):
                return False
            span = self._positions[-1][0] - self._positions[0][0]
            if span < self.window // 2:
                return False
            xs = [p[1][0] for p in self._positions]
            zs = [p[1][2] for p in self._positions]
            cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
            max_d = 0.0
            for p in self._positions:
                dx, dz = p[1][0] - cx, p[1][2] - cz
                d = math.sqrt(dx * dx + dz * dz)
                if d > max_d:
                    max_d = d
            if max_d <= self.radius:
                self._cooldown_until = step + self.cooldown
                self._positions.clear()
                return True
            return False
        except Exception:
            return False
