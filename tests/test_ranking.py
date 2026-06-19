"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for todo ranking (new->bottom, urgent floats up, done->out).
Role:    Guards the display-order rule from 3_Build_Decisions.md so the Todos list
         behaves predictably regardless of the UI.

Test classes:
- TestRanking - tier ordering, time-left ordering, done/deleted exclusion, new->bottom
============================================================
"""

from datetime import datetime, timedelta

from serenity.core.models import Todo
from serenity.core.ranking import rank_todos, urgency_tier

NOW = datetime(2026, 6, 19, 12, 0, 0)


def mk(title, order, **kw):
    return Todo(title=title, order=order, **kw)


class TestRanking:
    def test_done_and_deleted_excluded(self):
        todos = [
            mk("a", 0),
            mk("done", 1, done=True),
            mk("del", 2, deleted=True),
        ]
        out = rank_todos(todos, now=NOW)
        titles = [t.title for t in out]
        assert titles == ["a"]

    def test_new_todo_sinks_to_bottom(self):
        # two plain todos, manual order preserved -> newest (higher order) last
        todos = [mk("old", 0), mk("new", 5)]
        out = rank_todos(todos, now=NOW)
        assert [t.title for t in out] == ["old", "new"]

    def test_running_timer_floats_up(self):
        plain = mk("plain", 0)
        running = mk("running", 5, timer_running_since=NOW)
        out = rank_todos([plain, running], now=NOW)
        assert out[0].title == "running"

    def test_in_progress_floats_up(self):
        plain = mk("plain", 0)
        active = mk("active", 9, in_progress=True)
        out = rank_todos([plain, active], now=NOW)
        assert out[0].title == "active"

    def test_imminent_deadline_floats_up(self):
        far = mk("far", 0, due=NOW + timedelta(days=3))
        soon = mk("soon", 9, due=NOW + timedelta(minutes=10))
        out = rank_todos([far, soon], now=NOW)
        assert out[0].title == "soon"

    def test_urgent_band_least_time_left_first(self):
        a = mk("25min", 0, due=NOW + timedelta(minutes=25))
        b = mk("5min", 1, due=NOW + timedelta(minutes=5))
        out = rank_todos([a, b], now=NOW)
        assert [t.title for t in out] == ["5min", "25min"]

    def test_tiers(self):
        assert urgency_tier(mk("d", 0, done=True), NOW) == -1
        assert urgency_tier(mk("p", 0), NOW) == 0
        assert urgency_tier(mk("w", 0, due=NOW + timedelta(hours=2)), NOW) == 2
        assert urgency_tier(mk("s", 0, due=NOW + timedelta(minutes=10)), NOW) == 3

    def test_warn_below_soon(self):
        warn = mk("warn", 0, due=NOW + timedelta(hours=2))
        soon = mk("soon", 1, due=NOW + timedelta(minutes=10))
        plain = mk("plain", 2)
        out = rank_todos([plain, warn, soon], now=NOW)
        assert [t.title for t in out] == ["soon", "warn", "plain"]
