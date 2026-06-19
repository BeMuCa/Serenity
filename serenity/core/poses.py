"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Map mascot states to pose images and pick one at random per transition.
Role:    The MascotController (UI) asks this module "which pose file for state X?".
         Pure logic - no Qt - so the random-no-immediate-repeat rule is unit-tested.

Functions:
- pose_files() -> dict[str, str] - basename -> on-disk webp filename
- default_state_map() -> dict[str, list[str]] - state -> list of pose keys (decisions doc)
- PoseSelector.pick(state) -> str - random pose key for state, never the immediate repeat
- PoseSelector.filename(key) -> str | None - webp filename for a pose key
============================================================
"""

from __future__ import annotations

import random
from typing import Optional

# Pose key -> shipped webp filename. Keys match the decisions-doc table.
POSE_FILES: dict[str, str] = {
    "idle_1": "serenity_idle_1.webp",
    "idle_2": "serenity_idle_2.webp",
    "chilling": "serenity_chilling.webp",
    "work_1": "serenity_work_1.webp",
    "work_2": "serenity_work_2.webp",
    "mission": "serenity_mission.webp",
    "time": "serenity_time.webp",
    "aufmerksam": "serenity_aufmerksam.webp",
    "nachdenklich": "serenity_nachdenklich.webp",
    "examining": "serenity_examining.webp",
    "fun": "serenity_fun.webp",
    "hinweis": "serenity_hinweis.webp",
    "happy": "serenity_happy.webp",
    "mad": "serenity_mad.webp",
}

# State -> candidate pose keys (random pick per transition). From 3_Build_Decisions.md.
DEFAULT_STATE_MAP: dict[str, list[str]] = {
    "idle": ["idle_1", "idle_2", "chilling"],
    "working": ["work_1", "work_2"],
    "coding": ["mission", "work_2"],
    "meeting": ["time", "aufmerksam"],
    "planning": ["nachdenklich", "examining"],
    "entertainment": ["chilling", "fun"],
    "alert": ["hinweis", "aufmerksam"],
    "thinking": ["nachdenklich", "examining"],
    "success": ["happy", "fun"],
    "error": ["mad"],
}


def pose_files() -> dict[str, str]:
    return dict(POSE_FILES)


def default_state_map() -> dict[str, list[str]]:
    return {k: list(v) for k, v in DEFAULT_STATE_MAP.items()}


class PoseSelector:
    """Picks a pose for a state at random, avoiding an immediate repeat per state."""

    def __init__(
        self,
        state_map: Optional[dict[str, list[str]]] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._map = state_map if state_map is not None else default_state_map()
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}

    def states(self) -> list[str]:
        return list(self._map.keys())

    def poses_for(self, state: str) -> list[str]:
        return list(self._map.get(state, []))

    def pick(self, state: str) -> Optional[str]:
        """Return a pose key for `state`. Never repeats the previous pick for that
        state unless the state has only one pose. Returns None for unknown states."""
        candidates = self._map.get(state)
        if not candidates:
            return None
        if len(candidates) == 1:
            chosen = candidates[0]
            self._last[state] = chosen
            return chosen
        prev = self._last.get(state)
        pool = [p for p in candidates if p != prev] or candidates
        chosen = self._rng.choice(pool)
        self._last[state] = chosen
        return chosen

    def filename(self, key: str) -> Optional[str]:
        return POSE_FILES.get(key)
