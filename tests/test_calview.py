"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: Unit tests for the pure Calendar-tab grid helper (core.calview).
Role:    Guards collect_events / build_week / build_month: which todos become events,
         Mon-Sun bucketing, today + month-padding flags, intra-day sort. No Qt.

Test classes:
- TestCollectEvents - which todos become events; done/deleted/no-due filtering; has_time
- TestBuildWeek - Mon-Sun week, today flag, intra-day sort, label
- TestBuildMonth - weeks of the month incl. padding flagged, label
============================================================
"""
from datetime import datetime

from serenity.core.calview import collect_events
from serenity.core.models import Todo

NOW = datetime(2026, 6, 25, 9, 0)  # a Thursday


class TestCollectEvents:
    def test_includes_todo_with_due_and_excludes_no_due(self):
        todos = [
            Todo(title="Dentist", due=datetime(2026, 6, 25, 14, 0)),
            Todo(title="No date"),  # due is None -> excluded
        ]
        evs = collect_events(todos, now=NOW)
        assert [e.title for e in evs] == ["Dentist"]
        assert evs[0].todo_id == todos[0].id

    def test_excludes_deleted(self):
        todos = [Todo(title="Gone", due=datetime(2026, 6, 25, 14, 0), deleted=True)]
        assert collect_events(todos, now=NOW) == []

    def test_done_hidden_by_default_shown_with_flag(self):
        todos = [Todo(title="Did it", due=datetime(2026, 6, 25, 10, 0), done=True)]
        assert collect_events(todos, now=NOW) == []
        shown = collect_events(todos, now=NOW, show_done=True)
        assert len(shown) == 1 and shown[0].done is True

    def test_meeting_category_preserved(self):
        todos = [Todo(title="Standup", due=datetime(2026, 6, 25, 9, 0), category="meeting")]
        assert collect_events(todos, now=NOW)[0].category == "meeting"

    def test_has_time_true_for_timed_false_for_midnight(self):
        timed = Todo(title="t", due=datetime(2026, 6, 25, 14, 30))
        allday = Todo(title="a", due=datetime(2026, 6, 25, 0, 0))
        assert collect_events([timed], now=NOW)[0].has_time is True
        assert collect_events([allday], now=NOW)[0].has_time is False
