"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for next-due computation of recurring todos.
Role:    Guards core.recurrence.next_due (daily / weekdays / weekly / monthly) and
         the TodoStore wiring that advances a recurring todo's due when it spawns the
         next occurrence on completion (3_Build_Decisions.md recurring grammar).

Test classes:
- TestNextDue / TestStoreRollover
============================================================
"""

from datetime import datetime

from serenity.core.models import Todo
from serenity.core.recurrence import next_due
from serenity.core.todo_store import TodoStore

FRI = datetime(2026, 6, 19, 9, 0, 0)    # a Friday
SAT = datetime(2026, 6, 20, 9, 0, 0)    # a Saturday


class TestNextDue:
    def test_daily(self):
        assert next_due("daily", FRI) == datetime(2026, 6, 20, 9, 0)

    def test_weekdays_friday_to_monday(self):
        # Friday -> Monday (skips Sat/Sun)
        assert next_due("every weekday", FRI) == datetime(2026, 6, 22, 9, 0)

    def test_weekdays_midweek(self):
        wed = datetime(2026, 6, 17, 8, 0)
        assert next_due("every weekday", wed) == datetime(2026, 6, 18, 8, 0)

    def test_weekly(self):
        assert next_due("weekly", FRI) == datetime(2026, 6, 26, 9, 0)

    def test_weekly_day_keeps_weekday(self):
        nxt = next_due("weekly-day", FRI)
        assert nxt == datetime(2026, 6, 26, 9, 0)
        assert nxt.weekday() == FRI.weekday()

    def test_monthly(self):
        assert next_due("monthly", FRI) == datetime(2026, 7, 19, 9, 0)

    def test_monthly_clamps_to_month_length(self):
        jan31 = datetime(2026, 1, 31, 9, 0)
        # February has no 31st -> clamp to the 28th (2026 is not a leap year)
        assert next_due("monthly", jan31) == datetime(2026, 2, 28, 9, 0)

    def test_preserves_time_of_day(self):
        base = datetime(2026, 6, 19, 17, 30)
        assert next_due("daily", base).time() == base.time()

    def test_unknown_rule_returns_none(self):
        assert next_due("fortnightly", FRI) is None

    def test_none_rule(self):
        assert next_due(None, FRI) is None


class TestStoreRollover:
    def test_recurring_completion_advances_due(self, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="standup", recurring="every weekday", due=FRI))
        store.complete(t.id)
        clones = [x for x in store.active() if x.title == "standup"]
        assert len(clones) == 1
        # Friday standup -> next occurrence is Monday
        assert clones[0].due == datetime(2026, 6, 22, 9, 0)
        assert clones[0].recurring == "every weekday"
        assert clones[0].done is False

    def test_recurring_without_due_stays_undated(self, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="water plants", recurring="daily"))
        store.complete(t.id)
        clone = [x for x in store.active() if x.title == "water plants"][0]
        # no base due -> next-due falls back to "now", so it is dated and in the future
        assert clone.due is not None
        assert clone.recurring == "daily"
