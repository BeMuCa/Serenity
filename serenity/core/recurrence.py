"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Compute the next due date for a recurring todo (pure logic).
Role:    When a recurring todo is completed, TodoStore spawns the next occurrence;
         this module decides when that occurrence is due. No Qt, no I/O - unit-tested
         in isolation. Rules mirror the parser labels (3_Build_Decisions.md voice
         grammar: daily / weekdays / weekly / monthly).

Functions:
- next_due(rule, base) -> datetime | None - the next occurrence after `base`
============================================================
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Optional

# Recurrence rule labels the parser emits (see core.parser._RECURRING_PATTERNS).
DAILY = {"daily"}
WEEKDAYS = {"every weekday", "weekdays", "every workday"}
WEEKLY = {"weekly", "weekly-day"}     # weekly-day keeps the same weekday as `base`
MONTHLY = {"monthly"}


def _next_weekday(base: datetime) -> datetime:
    """The next Mon-Fri strictly after `base` (skips Sat/Sun)."""
    nxt = base + timedelta(days=1)
    while nxt.weekday() >= 5:          # 5 = Sat, 6 = Sun
        nxt += timedelta(days=1)
    return nxt


def _add_month(base: datetime) -> datetime:
    """Same day next month, clamped to the target month's length."""
    month = base.month + 1
    year = base.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(base.day, last_day)
    return base.replace(year=year, month=month, day=day)


def next_due(rule: Optional[str], base: datetime) -> Optional[datetime]:
    """Return the next occurrence strictly after `base` for `rule`.

    The clock time-of-day from `base` is preserved. Returns None for an unknown
    or missing rule (caller leaves the new occurrence undated)."""
    if not rule or base is None:
        return None
    key = rule.strip().lower()
    if key in DAILY:
        return base + timedelta(days=1)
    if key in WEEKDAYS:
        return _next_weekday(base)
    if key in WEEKLY:
        return base + timedelta(days=7)
    if key in MONTHLY:
        return _add_month(base)
    return None
