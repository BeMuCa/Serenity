"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Order todos for display - the ranking rule from 3_Build_Decisions.md.
Role:    The Todos list asks rank_todos(...) for display order. Pure function so the
         rule ("new -> bottom; running timer / nearing deadline floats up; done ->
         trash") is unit-tested independent of the UI. Mirrors the mockup's
         urgencyTier / rankedTodos logic.

Functions:
- urgency_tier(todo, now) -> int - higher = more urgent (3 running/imminent .. 0 manual)
- seconds_until_due(todo, now) -> float | None
- is_due_soon(todo, now, soon_minutes) / is_due_warn(todo, now, warn_hours)
- due_heat(todo, now, window_hours=WARN_HOURS) -> float - deadline-proximity fill in [0,1] for the card heat bar
- peek_class(todo, context, state_key, now) -> show|peek_full|peek_blurred|hide (urgency-peek)
- format_time_left(due, now) -> str - relative-only time-left for the blurred peek surface
- rank_todos(todos, now=None, ...) -> list[Todo] - active todos in display order
============================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Todo
from .states import visible

SOON_MINUTES = 30      # deadline within this => "soon" (top urgency)
WARN_HOURS = 4         # deadline within this => "warn" (mid urgency)


def seconds_until_due(todo: Todo, now: datetime) -> Optional[float]:
    if todo.due is None:
        return None
    return (todo.due - now).total_seconds()


def is_due_soon(todo: Todo, now: datetime, soon_minutes: int = SOON_MINUTES) -> bool:
    secs = seconds_until_due(todo, now)
    if secs is None:
        return False
    return secs <= soon_minutes * 60        # includes overdue (negative)


def is_due_warn(todo: Todo, now: datetime, warn_hours: int = WARN_HOURS) -> bool:
    secs = seconds_until_due(todo, now)
    if secs is None:
        return False
    return 0 <= secs <= warn_hours * 3600


def due_heat(todo: Todo, now: datetime, window_hours: int = WARN_HOURS) -> float:
    """Deadline-proximity fill in [0,1] for the todo card "heat" bar.

    0 when the deadline is more than `window_hours` away (or there is none),
    rising to 1 at the deadline and staying 1 once overdue. Lets the UI animate
    a fill that grows as a deadline approaches."""
    secs = seconds_until_due(todo, now)
    if secs is None:
        return 0.0
    window = window_hours * 3600
    if secs <= 0:
        return 1.0
    if secs >= window:
        return 0.0
    return round(1.0 - secs / window, 4)


def urgency_tier(todo: Todo, now: datetime) -> int:
    """Higher tier sorts first. Done items are excluded by rank_todos, but score -1."""
    if todo.done:
        return -1
    if todo.in_progress or todo.timer_running or is_due_soon(todo, now):
        return 3
    if is_due_warn(todo, now):
        return 2
    return 0                                # manual order: new todos + far-off deadlines


def peek_class(todo: Todo, context: str, state_key: Optional[str],
               now: datetime) -> str:
    """Classify a ranked todo against the two-axis filter (urgency-peek).

    "show"         - passes states.visible (normal render);
    "hide"         - filtered out and NOT urgent (the plain Phase C behavior);
    "peek_full"    - filtered, urgent (tier >= 2), context matching or unstamped:
                     only the STATE axis rejected it -> render the full card;
    "peek_blurred" - filtered, urgent, the CONTEXT axis rejected it -> render the
                     privacy-blurred placeholder (title/details never shown)."""
    if visible(todo, context, state_key):
        return "show"
    if urgency_tier(todo, now) < 2:
        return "hide"
    # mirror visible()'s context semantics: only an exact-valid OTHER-context stamp
    # is a context rejection; anything else here means the state axis rejected it.
    if todo.context in ("business", "private") and todo.context != context:
        return "peek_blurred"
    return "peek_full"


def format_time_left(due: datetime, now: datetime) -> str:
    """Relative-only time-left for the blurred peek surface (R-F).

    "in 47 min" / "in 3 h 10 min" / "in 2 h" / "overdue 12 min" - NEVER an absolute
    clock time (the blurred placeholder must not leak WHEN a private item happens,
    only how soon). Sub-minute remainders round up so due-in-30s reads "in 1 min"."""
    secs = (due - now).total_seconds()
    prefix = "in" if secs > 0 else "overdue"
    mins = int((abs(secs) + 59) // 60) if secs > 0 else int(abs(secs) // 60)
    h, m = divmod(mins, 60)
    if h and m:
        return f"{prefix} {h} h {m} min"
    if h:
        return f"{prefix} {h} h"
    return f"{prefix} {m} min"


def rank_todos(todos: list[Todo], now: Optional[datetime] = None) -> list[Todo]:
    """Return non-deleted, non-done todos in display order.

    Order: urgency tier desc; within the urgent band, least time-to-deadline first
    (running timers ahead of equal), otherwise by `todo.order` (the persisted manual
    order) so new todos land at the bottom and drag-to-reorder is honored."""
    now = now or datetime.now()
    active = [t for t in todos if not t.deleted and not t.done]

    def key(t: Todo):
        tier = urgency_tier(t, now)
        secs = seconds_until_due(t, now)
        # sort ascending: lower key = earlier in list
        if tier > 0:
            # urgent band: by remaining seconds (None far away), running timer wins ties
            remaining = secs if secs is not None else float("inf")
            return (-tier, remaining, 0 if t.timer_running else 1, t.order)
        return (-tier, float("inf"), 1, t.order)   # manual band by manual order

    return sorted(active, key=key)
