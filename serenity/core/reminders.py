"""
============================================================
Author:  Berk
Created: 2026-07-07
Purpose: Reminders module — rung constants, snapping, filtering, and relative-time phrases.
Role:    Pure, clock-injected logic for computing which reminder rungs can be armed at a
         given moment and formatting due-relative phrases in en/de. No Qt, no wall clock.
         Mirrors core/breaktime.py. Later tasks add tick/acknowledge/arm.

Functions:
- snap_to_rung(minutes) — snap arbitrary offset to nearest rung (NL capture)
- armable_offsets(todo, now) — list of rungs whose fire time is still future
- relative_phrase(due, now, lang) — format due-relative time in en/de (no clock times)
- tick(todo, now) — check if a reminder should fire; mutate reminder_* fields; return Fire or None
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from serenity.core.models import Todo

# The five fixed reminder rungs (minutes before due), in descending order (earliest-first).
RUNG_MINUTES = [10080, 1440, 60, 30, 5]

# Human-readable labels for each rung (English): dict[int, str] mapping rung → label.
RUNG_LABELS = {10080: "1 week", 1440: "1 day", 60: "1 hour", 30: "30 min", 5: "5 min"}

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
    # Sort by negative distance (ascending distance → highest sort key), then by rung (larger wins).
    return max(RUNG_MINUTES, key=lambda r: (-abs(minutes - r), r))


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
        fire_time = todo.due - timedelta(minutes=offset)
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


def tick(todo: Todo, now: datetime) -> Fire | None:
    """Check if a reminder should fire; mutate reminder_* fields; return Fire or None.

    Implements the tick steps 1–3 per Phase H spec §3:

    **Guard:** Skip (return None, NO mutation) if:
    - todo.done is True
    - todo.deleted is True
    - todo.due is None
    - todo.reminder_offsets is empty

    **Step 1 (active set):** If reminder_active is not None, return None (never stack a ring).

    **Step 2 (nudge due):** If reminder_nudge_at is not None and now >= reminder_nudge_at:
    - Set reminder_active = NUDGE_SENTINEL (0)
    - Clear reminder_nudge_at
    - Return Fire(todo_id=todo.id, offset=0, is_nudge=True)
    - Nudge takes precedence over step 3.

    **Step 3 (collapse):** Collect armed-unfired offsets where due - offset·minutes <= now:
    - If none found, return None
    - Else (collapse):
      - Mark ALL collected offsets as fired (append to reminder_fired, deduplicated by known-rung order)
      - Set reminder_active = min(collected) (smallest offset = closest to due = most urgent)
      - Return Fire(todo_id=todo.id, offset=min(collected), is_nudge=False)

    Note: tick MUTATES the todo's reminder_* fields but NEVER touches todo.due.
    """
    # ===== GUARD =====
    if todo.done or todo.deleted or todo.due is None or not todo.reminder_offsets:
        return None

    # ===== STEP 1: ACTIVE ALREADY SET =====
    if todo.reminder_active is not None:
        return None

    # ===== STEP 2: NUDGE DUE =====
    if todo.reminder_nudge_at is not None and now >= todo.reminder_nudge_at:
        todo.reminder_active = NUDGE_SENTINEL
        todo.reminder_nudge_at = None
        return Fire(todo_id=todo.id, offset=0, is_nudge=True)

    # ===== STEP 3: COLLAPSE =====
    # Collect armed-UNFIRED offsets that have passed (due - offset·min <= now)
    collected = []
    for offset in todo.reminder_offsets:
        fire_time = todo.due - timedelta(minutes=offset)
        if fire_time <= now and offset not in todo.reminder_fired:
            collected.append(offset)

    # If no rungs have fired, return None
    if not collected:
        return None

    # Mark all collected offsets as fired (deduplicated, in known-rung order)
    for offset in collected:
        if offset not in todo.reminder_fired:
            todo.reminder_fired.append(offset)

    # Set active to the minimum (closest to due, most urgent)
    min_offset = min(collected)
    todo.reminder_active = min_offset

    return Fire(todo_id=todo.id, offset=min_offset, is_nudge=False)
