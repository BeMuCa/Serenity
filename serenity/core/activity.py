"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Activity time-tracking log + the Friday Weekly-Board auto-open trigger (pure).
Role:    The mascot's activity bubbles append (category, start, end) entries; this
         module is the append-only log plus the read-side aggregation the dashboards
         ask for (spec sec 10: Heute / Woche, top categories). It also owns the
         once-per-day, Friday 17-18h rule that auto-opens the Weekly Performance Board.
         No Qt, no DB - an in-memory log (the store persists it) so it is unit-tested
         headless. Durations are clamped to >= 0 so a clock skew never logs negative time.

Functions:
- week_start(dt) -> date - the Monday (00:00) of dt's ISO week
- aggregate_seconds(entries, ...) -> dict[str, int] - seconds per category in a window
- top_categories(entries, ..., limit) -> list[(category, seconds)] - busiest first
- should_auto_open_board(now, last_open) -> bool - the Friday 17-18h once-a-day rule

Classes:
- ActivityEntry - one tracked span: category + start + end (pure dataclass)
- ActivityLog - append-only log; total/aggregate/top-category queries over a window
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

# The Friday window the Weekly Performance Board pops up in (local clock hour).
# 17 <= hour < 18 on a Friday, at most once per calendar day (spec sec 10 Wochen-Board).
BOARD_WEEKDAY = 4          # Mon=0 .. Fri=4
BOARD_HOUR_START = 17
BOARD_HOUR_END = 18


@dataclass
class ActivityEntry:
    """One tracked activity span. `end` is None while the span is still running."""

    category: str
    start: datetime
    end: Optional[datetime] = None

    def seconds(self, now: Optional[datetime] = None) -> int:
        """Span length in whole seconds; a running span counts up to `now`.

        Clamped to >= 0 so a backwards clock or a bad row never logs negative time."""
        finish = self.end or now or datetime.now()
        return max(0, int((finish - self.start).total_seconds()))


def week_start(dt: datetime) -> date:
    """The Monday (date) of the ISO week containing `dt`."""
    d = dt.date()
    return d - timedelta(days=d.weekday())


def _in_window(entry: ActivityEntry, since: Optional[datetime], until: Optional[datetime]) -> bool:
    """True if the entry's start falls in [since, until) (open-ended bounds allowed)."""
    if since is not None and entry.start < since:
        return False
    if until is not None and entry.start >= until:
        return False
    return True


def aggregate_seconds(
    entries: list[ActivityEntry],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Total seconds per category for entries started within [since, until).

    Categories with no time are omitted. A running span (end is None) counts up to
    `now`. Bounds are optional: with neither, the whole log is aggregated."""
    totals: dict[str, int] = {}
    for e in entries:
        if not _in_window(e, since, until):
            continue
        secs = e.seconds(now)
        if secs <= 0:
            continue
        totals[e.category] = totals.get(e.category, 0) + secs
    return totals


def top_categories(
    entries: list[ActivityEntry],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    now: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> list[tuple[str, int]]:
    """Categories busiest-first as (category, seconds), ties broken by name.

    `limit` caps the list (None = all)."""
    totals = aggregate_seconds(entries, since, until, now)
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:limit] if limit is not None else ranked


def should_auto_open_board(now: datetime, last_open: Optional[datetime]) -> bool:
    """True when the Weekly Performance Board should auto-open now.

    Rule (spec sec 10): on a Friday, when the local hour is in [17, 18), and the board
    has not already been auto-opened today. `last_open` is the last time it opened (or
    None if never)."""
    if now.weekday() != BOARD_WEEKDAY:
        return False
    if not (BOARD_HOUR_START <= now.hour < BOARD_HOUR_END):
        return False
    if last_open is not None and last_open.date() == now.date():
        return False
    return True


class ActivityLog:
    """Append-only log of tracked activity spans with read-side aggregation.

    Pure of Qt / DB; the time-tracking store persists the entries and hands them here
    for the Heute / Woche dashboards and the Weekly Board. Only one span runs at a
    time: starting a new category closes the open one (spec sec 10)."""

    def __init__(self, entries: Optional[list[ActivityEntry]] = None) -> None:
        self._entries: list[ActivityEntry] = list(entries) if entries else []

    def entries(self) -> list[ActivityEntry]:
        return list(self._entries)

    def start(self, category: str, when: datetime) -> ActivityEntry:
        """Begin tracking `category`, closing any still-running span at `when` first."""
        self.stop(when)
        entry = ActivityEntry(category=category, start=when)
        self._entries.append(entry)
        return entry

    def stop(self, when: datetime) -> Optional[ActivityEntry]:
        """Close the currently-running span (if any) at `when`. Returns it, or None."""
        for e in reversed(self._entries):
            if e.end is None:
                e.end = when
                return e
        return None

    def running(self) -> Optional[ActivityEntry]:
        """The open span, or None when nothing is being tracked."""
        for e in reversed(self._entries):
            if e.end is None:
                return e
        return None

    def total_seconds(self, since: Optional[datetime] = None,
                      until: Optional[datetime] = None,
                      now: Optional[datetime] = None) -> int:
        """Total tracked seconds across all categories in the window."""
        return sum(aggregate_seconds(self._entries, since, until, now).values())

    def week_totals(self, now: datetime) -> dict[str, int]:
        """Seconds per category for the current ISO week (Monday 00:00 -> now)."""
        start = datetime.combine(week_start(now), datetime.min.time())
        return aggregate_seconds(self._entries, since=start, until=None, now=now)
