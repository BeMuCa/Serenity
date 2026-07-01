"""
============================================================
Author:  Berk
Created: 2026-07-01
Purpose: Single editable registry of Serenity's activity + reaction states.
Role:    The one source of truth for the activity selector, the running-activity
         chip color and the state->pose map. Pure logic - no Qt - so the seed,
         projections and consumers are unit-tested headless. Foundation of the
         States & Contexts milestone (Phase A).

Models:
- ActivityState{key,label,color,poses,category,context} - one activity or reaction.

Functions:
- default_states() -> list[ActivityState] - a fresh copy of the seed.
- activities(states) -> list[ActivityState] - the trackable (category=="activity") rows.
- is_protected(s) -> bool - reaction rows + Idle (undeletable; data marker for Phase E).
- color_for_label(label, states=None, default=ACCENT) -> str - registry color, else default.
- selector_rows(states, context=None) -> list[(label,key,color)] - selector projection,
  optionally filtered to one context (+ the context-neutral Idle).
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ACCENT = "#a78bfa"
IDLE_POSES = ("idle_1", "idle_2", "chilling", "idle_3", "silent")
# per-context "mood" pose-state played on a flip when nothing is being tracked (Phase B)
CONTEXT_DEFAULT_POSE = {"business": "idle", "private": "chilling"}


@dataclass(frozen=True)
class ActivityState:
    key: str
    label: str
    color: str = ACCENT
    poses: tuple[str, ...] = IDLE_POSES
    category: str = "activity"   # "activity" (trackable) | "reaction" (pose-only)
    context: str = "any"         # "business" | "private" | "any"


DEFAULT_STATES: list[ActivityState] = [
    ActivityState("working", "Working", "#a78bfa", ("work_1", "work_2", "concentrating"), "activity", "business"),
    ActivityState("coding", "Coding", "#ff8ad0", ("mission", "work_2", "concentrating"), "activity", "business"),
    ActivityState("meeting", "Meeting", "#5cc8ff", ("time", "aufmerksam", "come"), "activity", "business"),
    ActivityState("planning", "Planning", "#8fd36a", ("nachdenklich", "examining", "detektive", "searching"), "activity", "business"),
    ActivityState("focus", "Focus", "#19e3ff", ("mission", "work_2", "glasses_off"), "activity", "business"),
    ActivityState("entertainment", "Entertainment", "#e3b341", ("chilling", "fun", "dj", "cheering", "giggeling", "amused"), "activity", "business"),
    ActivityState("idle", "Idle", "#19e3ff", ("idle_1", "idle_2", "chilling", "idle_3", "silent"), "activity", "any"),
    ActivityState("alert", "Alert", ACCENT, ("hinweis", "aufmerksam"), "reaction", "any"),
    ActivityState("thinking", "Thinking", ACCENT, ("nachdenklich", "examining", "concentrating"), "reaction", "any"),
    ActivityState("success", "Success", ACCENT, ("happy", "fun", "happy_2", "relieved", "cheering"), "reaction", "any"),
    ActivityState("error", "Error", ACCENT, ("mad", "mad_2", "ups", "ups_2", "annoyed", "überhitzt", "frozen", "spilled_coffee"), "reaction", "any"),
    # Phase B - Private context activity set.
    ActivityState("chilling", "Chilling", "#8fd36a", ("chilling", "silent"), "activity", "private"),
    ActivityState("friends", "Friends", "#ff8ad0", ("cheering", "giggeling", "come"), "activity", "private"),
    ActivityState("girlfriend", "Girlfriend", "#fb7185", ("amused", "giggeling", "verlegen"), "activity", "private"),
    ActivityState("music", "Music", "#19e3ff", ("dj",), "activity", "private"),
    ActivityState("learning", "Learning", "#5cc8ff", ("examining", "nachdenklich", "detektive", "searching"), "activity", "private"),
    ActivityState("code", "Code", "#a78bfa", ("mission", "work_2"), "activity", "private"),
    ActivityState("eat", "Eat", "#e3b341", ("idle_1", "idle_2"), "activity", "private"),
    ActivityState("gaming", "Gaming", "#2dd4bf", ("concentrating", "mission"), "activity", "private"),
]


def default_states() -> list[ActivityState]:
    return list(DEFAULT_STATES)


def activities(states: list[ActivityState]) -> list[ActivityState]:
    return [s for s in states if s.category == "activity"]


def is_protected(s: ActivityState) -> bool:
    return s.category == "reaction" or s.key == "idle"


def color_for_label(label: str, states: Optional[list[ActivityState]] = None,
                    default: str = ACCENT) -> str:
    for s in (states if states is not None else default_states()):
        if s.label == label:
            return s.color
    return default


def selector_rows(states: list[ActivityState],
                  context: Optional[str] = None) -> list[tuple[str, str, str]]:
    rows = activities(states)
    if context is not None:
        rows = [s for s in rows if s.context in (context, "any")]   # "any" (Idle) shows in both
    return [(s.label, s.key, s.color) for s in rows]
