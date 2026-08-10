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
- pre_mark_past(todo, now) — union past-due offsets into reminder_fired; no-op if due is None
- silence(todo) — clear reminder_active and reminder_nudge_at
- acknowledge_snooze(todo, now) — snooze to next lower rung or schedule nudge; no-op if active is None
- acknowledge_dismiss(todo) — mark all offsets fired; clear active and nudge
- arm(todo, offsets, now) — set reminder_offsets with delta-semantics preservation of fired state
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


def pre_mark_past(todo: Todo, now: datetime) -> None:
    """Union offsets already past their fire time into reminder_fired.

    For each offset in reminder_offsets whose fire time (due - offset·min) has
    already passed, add it to reminder_fired. Maintains the file's convention:
    known ints, deduplicated, descending order. No-op if todo.due is None.

    Mutates todo's reminder_fired field.
    """
    if todo.due is None:
        return

    # Collect offsets that are already past their fire time
    newly_past = []
    for offset in todo.reminder_offsets:
        fire_time = todo.due - timedelta(minutes=offset)
        if fire_time <= now:
            newly_past.append(offset)

    # Union with existing fired; deduplicate and maintain descending order
    union_set = set(todo.reminder_fired) | set(newly_past)
    # Sort descending (RUNG_MINUTES is already descending, so filter by membership),
    # then append sentinel 0 if present (0 is not in RUNG_MINUTES)
    todo.reminder_fired = (
        [o for o in RUNG_MINUTES if o in union_set] +
        ([0] if 0 in union_set else [])
    )


def silence(todo: Todo) -> None:
    """Clear reminder_active and reminder_nudge_at (silence the ring).

    Does NOT touch reminder_offsets or reminder_fired.

    Mutates todo's reminder_active and reminder_nudge_at fields.
    """
    todo.reminder_active = None
    todo.reminder_nudge_at = None


def acknowledge_snooze(todo: Todo, now: datetime) -> None:
    """Snooze: defer to the next armed-unfired rung or schedule a nudge.

    If reminder_active is None, no-op (nothing ringing to snooze).

    Otherwise:
    - If a smaller armed-unfired offset exists (< reminder_active, not in
      reminder_fired, and reminder_active != NUDGE_SENTINEL), just clear
      reminder_active. The ladder self-walks; that lower rung fires on its
      own schedule via tick (even if already past—escalation is intended).
    - Otherwise (bottom armed rung, or a nudge, or no smaller rung), schedule
      a +NUDGE_MINUTES nudge: set reminder_nudge_at = now + NUDGE_MINUTES·min,
      clear reminder_active.

    Mutates todo's reminder_active and reminder_nudge_at fields.
    """
    if todo.reminder_active is None:
        return

    # Check if a smaller armed-unfired rung exists
    if todo.reminder_active != NUDGE_SENTINEL:
        for offset in todo.reminder_offsets:
            if (
                offset < todo.reminder_active
                and offset not in todo.reminder_fired
            ):
                # Found a smaller unfired rung; ladder walks via tick
                todo.reminder_active = None
                return

    # No smaller unfired rung (or active is nudge): schedule nudge
    todo.reminder_active = None
    todo.reminder_nudge_at = now + timedelta(minutes=NUDGE_MINUTES)


def acknowledge_dismiss(todo: Todo) -> None:
    """Dismiss: mark all armed offsets as fired and silence the ring.

    Sets reminder_fired = list(reminder_offsets), clears reminder_active and
    reminder_nudge_at. Silent forever unless re-armed.

    Mutates todo's reminder_fired, reminder_active, and reminder_nudge_at fields.
    """
    todo.reminder_fired = list(todo.reminder_offsets)
    todo.reminder_active = None
    todo.reminder_nudge_at = None


def arm(todo: Todo, offsets: list[int], now: datetime) -> None:
    """Set reminder_offsets while preserving prior fired state (delta semantics).

    Implements the delta pattern: dropped rungs are removed from reminder_fired,
    added rungs are pre-marked fired iff already past, unchanged rungs keep
    their current fired status (a dismissed rung stays dismissed).

    Constraints:
    - Sanitize input: drop unknown offsets (not in RUNG_MINUTES), deduplicate,
      sort descending (file convention).
    - Guard: if todo.due is None, set offsets, fired=[], no fire-time math.
    - Invariant: reminder_fired ⊆ reminder_offsets (except sentinel 0, which
      may sit in fired; only drop 0 when offsets becomes empty).
    - Clear reminder_active/reminder_nudge_at if they reference a dropped rung.
      Sentinel 0 (NUDGE_SENTINEL) is NOT a rung reference—a pending nudge
      survives re-arm if ≥1 rung is kept.
    - Empty offsets (offsets == []) clears every reminder field.

    Mutates todo's reminder_offsets, reminder_fired, reminder_active, and
    reminder_nudge_at fields.
    """
    # Sanitize: keep only known offsets
    sanitized = [o for o in offsets if o in RUNG_MINUTES]
    # Deduplicate and sort descending (file convention)
    sanitized = sorted(set(sanitized), reverse=True)

    # Identify dropped and added offsets (delta)
    old_offsets_set = set(todo.reminder_offsets)
    new_offsets_set = set(sanitized)
    dropped = old_offsets_set - new_offsets_set
    added = new_offsets_set - old_offsets_set

    # Set the new offsets
    todo.reminder_offsets = sanitized

    # ===== GUARD: due is None =====
    if todo.due is None:
        todo.reminder_fired = []
        todo.reminder_active = None
        todo.reminder_nudge_at = None
        return

    # ===== GUARD: empty offsets =====
    if not sanitized:
        todo.reminder_fired = []
        todo.reminder_active = None
        todo.reminder_nudge_at = None
        return

    # ===== Delta: apply to reminder_fired =====
    # Remove dropped offsets from fired
    for dropped_offset in dropped:
        if dropped_offset in todo.reminder_fired:
            todo.reminder_fired.remove(dropped_offset)

    # Add newly-past offsets to fired
    for added_offset in added:
        fire_time = todo.due - timedelta(minutes=added_offset)
        if fire_time <= now:
            if added_offset not in todo.reminder_fired:
                todo.reminder_fired.append(added_offset)

    # ===== Clear active/nudge if they reference a dropped rung =====
    # active != NUDGE_SENTINEL means it's a rung reference
    if (
        todo.reminder_active is not None
        and todo.reminder_active != NUDGE_SENTINEL
        and todo.reminder_active in dropped
    ):
        todo.reminder_active = None
        todo.reminder_nudge_at = None

    # ===== Maintain fired as deduplicated, descending order =====
    # Sort descending using RUNG_MINUTES order, plus allow sentinel 0
    fired_set = set(todo.reminder_fired)
    todo.reminder_fired = (
        [o for o in RUNG_MINUTES if o in fired_set] +
        ([0] if 0 in fired_set else [])
    )
