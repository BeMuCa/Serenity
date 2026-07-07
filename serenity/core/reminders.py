"""
============================================================
Author:  Berk
Created: 2026-07-07
Purpose: The reminders module — ladder constants, rung-snapping, armable-offset filtering,
         and relative-time phrase generation for mascot bubbles.
Role:    Pure, clock-injected logic (mirrors core/breaktime.py) for computing which reminder
         rungs can be armed at a given moment and formatting due-relative phrases in en/de.
         No Qt, no wall clock — `now` is always injected. Task 1 (models.py) added the data
         fields; this module owns the pure rules for snap_to_rung, armable_offsets, and
         relative_phrase. Later tasks add tick/acknowledge/arm (T3/T4).

Constants:
- RUNG_MINUTES - the five fixed reminder rungs (minutes before due): [10080, 1440, 60, 30, 5]
- RUNG_LABELS - human labels for the rungs (en): ["1 week", "1 day", ...]
- NUDGE_MINUTES - the re-nudge interval (minutes): 5
- NUDGE_SENTINEL - the marker for a +5min nudge active rung: 0

Functions:
- snap_to_rung(minutes) — snap arbitrary offset to nearest rung (NL capture)
- armable_offsets(todo, now) — list of rungs whose fire time is still future
- relative_phrase(due, now, lang) — format due-relative time in en/de (no clock times)

Classes:
- Fire - one reminder ring event: todo_id, offset, is_nudge
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from serenity.core.models import Todo

# The five fixed reminder rungs (minutes before due), in descending order (earliest-first).
RUNG_MINUTES = [10080, 1440, 60, 30, 5]

# Human-readable labels for each rung (English).
RUNG_LABELS = ["1 week", "1 day", "1 hour", "30 min", "5 min"]

# The fixed re-nudge interval when snoozing past the last armed rung.
NUDGE_MINUTES = 5

# Sentinel value for a +5 min nudge active reminder (reminder_active = 0).
NUDGE_SENTINEL = 0


@dataclass(frozen=True)
class Fire:
    """One reminder ring event: which todo, which offset, and whether it's a nudge.

    `todo_id` is the id of the todo to ring for. `offset` is the armed offset (minutes
    before due) that just fired, or 0 if this is a +5 min nudge. `is_nudge` marks this as
    a re-nudge (offset=0) vs. a regular rung fire."""

    todo_id: str
    offset: int
    is_nudge: bool


def snap_to_rung(minutes: int) -> int:
    """Snap an arbitrary offset to the nearest rung, breaking ties toward LARGER/earlier rungs.

    Used by NL capture to convert a free-form "remind me X minutes before" into a known rung.
    When two rungs are equidistant, prefer the larger minute value (earlier absolute time).
    Examples:
    - snap_to_rung(3) → 5 (3 is closer to 5 than 30)
    - snap_to_rung(700) → 60 (700-60=640 < 1440-700=740)
    - snap_to_rung(750) → 1440 (equidistant from 60 and 1440; ties favor larger 1440)
    - snap_to_rung(999999) → 10080 (closest to the largest rung)
    """
    best_rung = RUNG_MINUTES[0]
    best_distance = abs(minutes - best_rung)

    for rung in RUNG_MINUTES[1:]:
        distance = abs(minutes - rung)
        # Prefer the new rung if it's strictly closer, or if it's equidistant and larger.
        if distance < best_distance or (distance == best_distance and rung > best_rung):
            best_rung = rung
            best_distance = distance

    return best_rung


def armable_offsets(todo: Todo, now: datetime) -> list[int]:
    """Return the subset of todo's reminder_offsets whose fire time is still in the future.

    A rung is "armable" if `now < due - offset·minutes`; rungs already past (whose fire time
    would be retroactive) are excluded. Used by the picker UI to grey out past rungs, and to
    guard `arm()` from retroactively ringing.

    Returns the armed offsets in descending order, preserving the todo's original order.
    If todo has no `due` or no `reminder_offsets`, returns [].
    """
    if todo.due is None or not todo.reminder_offsets:
        return []

    result = []
    for offset in todo.reminder_offsets:
        fire_time = todo.due - __import__("datetime").timedelta(minutes=offset)
        if now < fire_time:
            result.append(offset)

    return result


def relative_phrase(due: datetime, now: datetime, lang: str) -> str:
    """Format a due-relative time phrase in the requested language (en/de only).

    Returns strings like "in 47 min", "in 3 h 10 min", "in 2 h", "overdue 12 min",
    "seit 12 Min überfällig", etc. — NEVER wall-clock times (no colons). Mimics
    ranking.format_time_left's rounding: sub-minute future remainders round up
    (30s → "in 1 min"), overdue remainders round down.

    For en: delegates to ranking.format_time_left.
    For de: applies the same logic with German labels and phrasing.
    """
    if lang == "en":
        # Delegate to the existing English formatter.
        from serenity.core.ranking import format_time_left
        return format_time_left(due, now)

    # German: "in X Std Y Min", "seit X Min überfällig", etc.
    secs = (due - now).total_seconds()
    if secs > 0:
        prefix = "in"
        # Round up: add 59 seconds (so 30s → 1 min)
        mins = int((secs + 59) // 60)
    else:
        prefix = "seit"
        # Round down: floor divide without rounding up
        mins = int((-secs) // 60)
        suffix = "überfällig"

    h, m = divmod(mins, 60)

    if secs > 0:
        if h and m:
            return f"{prefix} {h} Std {m} Min"
        if h:
            return f"{prefix} {h} Std"
        return f"{prefix} {m} Min"
    else:
        if h and m:
            return f"{prefix} {h} Std {m} Min {suffix}"
        if h:
            return f"{prefix} {h} Std {suffix}"
        return f"{prefix} {m} Min {suffix}"
