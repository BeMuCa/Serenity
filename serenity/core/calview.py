"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: Pure logic for the Calendar tab - turn todos-with-a-due into a Mon-Sun grid.
Role:    The headless, Qt-free helper the ui.calendar_view renders. Mirrors core.weekly_board:
         the view holds no calendar logic, it only draws the CalGrid this module builds.
         Named 'calview' (not 'calendar') so it never shadows the stdlib calendar module,
         which build_month uses for the month layout.

Functions:
- collect_events(todos, now, show_done) -> [CalEvent] - todos with a due become events
- build_week(events, anchor, now) -> CalGrid - the Mon-Sun week containing anchor
- build_month(events, anchor, now) -> CalGrid - the weeks of anchor's month

Classes:
- CalEvent - one dated todo on the calendar (when, title, category, done, has_time, todo_id)
- DayCell - one grid day (day, in_period, is_today, sorted events)
- CalGrid - weeks of DayCells + a label + the mode ("week"/"month")
============================================================
"""

from __future__ import annotations

import calendar as _stdlib_calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass
class CalEvent:
    """One todo-with-a-deadline placed on the calendar."""

    when: datetime
    title: str
    category: str | None
    done: bool
    has_time: bool
    todo_id: str


def _has_time(due: datetime) -> bool:
    """A due exactly at midnight reads as all-day; any clock time means it is timed.

    Todo only stores `due: datetime` (no has_time flag), so a date-only capture lands at
    00:00 and shows without a time; a parsed clock time ("17 Uhr") shows HH:MM."""
    return not (due.hour == 0 and due.minute == 0 and due.second == 0)


def collect_events(todos, now: datetime | None = None, show_done: bool = False) -> list[CalEvent]:
    """Map the todos that belong on a calendar (a due date, not trashed) to CalEvents.

    Done todos are dropped unless show_done, so the default view is not overcrowded."""
    out: list[CalEvent] = []
    for t in todos:
        if t.deleted or t.due is None:
            continue
        if t.done and not show_done:
            continue
        out.append(
            CalEvent(
                when=t.due,
                title=t.title,
                category=t.category,
                done=t.done,
                has_time=_has_time(t.due),
                todo_id=t.id,
            )
        )
    return out


@dataclass
class DayCell:
    """One day in the grid: its date, whether it belongs to the focused period, today, events."""

    day: date
    in_period: bool
    is_today: bool
    events: list[CalEvent] = field(default_factory=list)


@dataclass
class CalGrid:
    """A laid-out calendar: rows of 7 DayCells (Mon..Sun), a header label, and the mode."""

    weeks: list[list[DayCell]]
    label: str
    mode: str


def _week_start(d: date) -> date:
    """The Monday of d's week (Monday=0)."""
    return d - timedelta(days=d.weekday())


def _day_cell(d: date, events: list[CalEvent], now: datetime, in_period: bool = True) -> DayCell:
    """Bucket the events that fall on day d, sorted timed-first then by time, then title."""
    todays = [e for e in events if e.when.date() == d]
    todays.sort(key=lambda e: (not e.has_time, e.when, e.title))
    return DayCell(day=d, in_period=in_period, is_today=(d == now.date()), events=todays)


def _week_label(start: date, end: date) -> str:
    """e.g. 'Jun 22 - 28' within a month, 'Jun 29 - Jul 5' across one. No %-d (Windows-safe)."""
    if start.month == end.month:
        return f"{start.strftime('%b')} {start.day} - {end.day}"
    return f"{start.strftime('%b')} {start.day} - {end.strftime('%b')} {end.day}"


def build_week(events: list[CalEvent], anchor: date, now: datetime | None = None) -> CalGrid:
    """Lay out the single Mon-Sun week that contains the anchor date."""
    now = now or datetime.now()
    start = _week_start(anchor)
    days = [start + timedelta(days=i) for i in range(7)]
    week = [_day_cell(d, events, now) for d in days]
    return CalGrid(weeks=[week], label=_week_label(start, days[-1]), mode="week")


def build_month(events: list[CalEvent], anchor: date, now: datetime | None = None) -> CalGrid:
    """Lay out the weeks of the anchor's month (Mon-Sun rows).

    Uses the stdlib calendar's monthdatescalendar, which returns whole Mon..Sun weeks padded
    with the adjacent months' days; those padding days are flagged in_period=False so the view
    can dim them."""
    now = now or datetime.now()
    cal = _stdlib_calendar.Calendar(firstweekday=0)  # 0 = Monday
    weeks = [
        [_day_cell(d, events, now, in_period=(d.month == anchor.month)) for d in wk]
        for wk in cal.monthdatescalendar(anchor.year, anchor.month)
    ]
    return CalGrid(weeks=weeks, label=f"{anchor.strftime('%B %Y')}", mode="month")
