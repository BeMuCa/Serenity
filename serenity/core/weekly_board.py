"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Weekly Performance Board stats (pure) - this week vs last, hints.
Role:    Friday's Wochen-Board (spec sec 10, replaces the dropped Resurfacer): turns the
         activity time-log + completed todos into top categories, the delta vs last week
         and a couple of plain optimization hints. No Qt, no DB - reads the ActivityLog
         and a count of completed todos, so it is unit-tested headless. The trigger that
         decides WHEN this board opens lives in core.activity.should_auto_open_board.

Functions:
- build_board(log, now, completed_this_week=0) -> WeeklyBoard - the full board stats

Classes:
- CategoryStat - one row: category, seconds this week, seconds last week, delta seconds
- WeeklyBoard - top categories, total focus seconds, completed count, hints
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .activity import ActivityEntry, aggregate_seconds, week_start


@dataclass
class CategoryStat:
    """One category's week-over-week time: this week, last week, and the delta."""

    category: str
    seconds: int
    prev_seconds: int

    @property
    def delta(self) -> int:
        """Change in seconds vs last week (positive = more time this week)."""
        return self.seconds - self.prev_seconds


@dataclass
class WeeklyBoard:
    """The Friday board: ranked categories, totals, and optimization hints."""

    week_start: datetime
    categories: list[CategoryStat] = field(default_factory=list)
    total_seconds: int = 0
    prev_total_seconds: int = 0
    completed: int = 0
    hints: list[str] = field(default_factory=list)

    @property
    def top_category(self) -> str:
        """The busiest category this week, or "" when nothing was tracked."""
        return self.categories[0].category if self.categories else ""

    @property
    def total_delta(self) -> int:
        return self.total_seconds - self.prev_total_seconds


def _window(now: datetime) -> tuple[datetime, datetime]:
    """(this-week-start, last-week-start) as datetimes at 00:00 Monday."""
    this_start = datetime.combine(week_start(now), datetime.min.time())
    last_start = this_start - timedelta(days=7)
    return this_start, last_start


def _hints(board: WeeklyBoard) -> list[str]:
    """A couple of plain, deterministic optimization hints from the stats.

    Single-hyphen copy only, no emojis (house style)."""
    out: list[str] = []
    if not board.categories:
        out.append("No time tracked this week - pick an activity to start logging.")
    else:
        top = board.categories[0]
        # A category eating more than 60% of tracked time -> suggest rebalancing.
        if board.total_seconds and top.seconds / board.total_seconds > 0.6:
            out.append(f"{top.category} took most of your week - consider spreading focus.")
        # Largest week-over-week jump worth calling out (>= 1h more than last week).
        rising = max(board.categories, key=lambda c: c.delta)
        if rising.delta >= 3600:
            out.append(f"{rising.category} is up {rising.delta // 3600}h vs last week.")
    # Completed todos are momentum regardless of whether any time was tracked.
    if board.completed:
        out.append(f"You completed {board.completed} todos this week - nice momentum.")
    return out


def build_board(
    entries: list[ActivityEntry],
    now: datetime,
    completed_this_week: int = 0,
) -> WeeklyBoard:
    """Build the Weekly Performance Board from the activity log + a completed count.

    Categories are ranked busiest-first (ties by name), each carrying its last-week
    seconds and delta. Totals and a couple of hints round it out."""
    this_start, last_start = _window(now)
    this = aggregate_seconds(entries, since=this_start, until=None, now=now)
    prev = aggregate_seconds(entries, since=last_start, until=this_start, now=now)

    cats = [
        CategoryStat(category=c, seconds=s, prev_seconds=prev.get(c, 0))
        for c, s in this.items()
    ]
    cats.sort(key=lambda c: (-c.seconds, c.category))

    board = WeeklyBoard(
        week_start=this_start,
        categories=cats,
        total_seconds=sum(this.values()),
        prev_total_seconds=sum(prev.values()),
        completed=completed_this_week,
    )
    board.hints = _hints(board)
    return board
