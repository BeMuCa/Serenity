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
- TestBuildTimegrid - day x hour cells, all-day strip, week-membership, order, skeleton, label
============================================================
"""
from datetime import date, datetime

from serenity.core.calview import build_month, build_timegrid, build_week, collect_events
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

    def test_has_time_true_for_midnight_with_stray_microseconds(self):
        # 00:00:00.5 is not exactly midnight -> a timed due, not all-day.
        ev = collect_events([Todo(title="a", due=datetime(2026, 6, 25, 0, 0, 0, 500000))], now=NOW)[0]
        assert ev.has_time is True


class TestBuildWeek:
    def test_week_is_monday_to_sunday_containing_anchor(self):
        # anchor Thu 2026-06-25 -> week Mon 22 .. Sun 28
        grid = build_week([], date(2026, 6, 25), now=NOW)
        assert grid.mode == "week"
        assert len(grid.weeks) == 1 and len(grid.weeks[0]) == 7
        days = [c.day for c in grid.weeks[0]]
        assert days[0] == date(2026, 6, 22)
        assert days[-1] == date(2026, 6, 28)

    def test_event_lands_on_its_day_and_today_flagged(self):
        evs = collect_events([Todo(title="Dentist", due=datetime(2026, 6, 25, 14, 0))], now=NOW)
        grid = build_week(evs, date(2026, 6, 25), now=NOW)
        thu = grid.weeks[0][3]  # Mon..Sun -> Thu is index 3
        assert thu.day == date(2026, 6, 25)
        assert thu.is_today is True
        assert [e.title for e in thu.events] == ["Dentist"]
        assert grid.weeks[0][0].is_today is False

    def test_intraday_sort_timed_before_untimed(self):
        evs = collect_events([
            Todo(title="Late", due=datetime(2026, 6, 25, 16, 0)),
            Todo(title="AllDay", due=datetime(2026, 6, 25, 0, 0)),
            Todo(title="Early", due=datetime(2026, 6, 25, 9, 0)),
        ], now=NOW)
        thu = build_week(evs, date(2026, 6, 25), now=NOW).weeks[0][3]
        assert [e.title for e in thu.events] == ["Early", "Late", "AllDay"]

    def test_week_boundary_anchors_monday_and_sunday(self):
        # the riskiest weekday() cases: a Monday (0) and a Sunday (6) anchor both
        # resolve to the same Mon 22 .. Sun 28 week (guards a _week_start off-by-one).
        for anchor in (date(2026, 6, 22), date(2026, 6, 28)):
            days = [c.day for c in build_week([], anchor, now=NOW).weeks[0]]
            assert days[0] == date(2026, 6, 22)
            assert days[-1] == date(2026, 6, 28)

    def test_cross_month_week_spans_two_months_and_places_event(self):
        # week Mon 2026-06-29 .. Sun 2026-07-05 straddles the month boundary.
        evs = collect_events([Todo(title="JulTask", due=datetime(2026, 7, 2, 10, 0))], now=NOW)
        week = build_week(evs, date(2026, 6, 30), now=NOW).weeks[0]
        assert week[0].day == date(2026, 6, 29)    # Monday in June
        assert week[-1].day == date(2026, 7, 5)     # Sunday in July
        assert week[3].day == date(2026, 7, 2)      # Thursday, in July
        assert [e.title for e in week[3].events] == ["JulTask"]

    def test_intraday_tiebreak_by_title(self):
        # same time -> sort by title; multiple all-day events -> also by title.
        evs = collect_events([
            Todo(title="B", due=datetime(2026, 6, 25, 9, 0)),
            Todo(title="A", due=datetime(2026, 6, 25, 9, 0)),
            Todo(title="Zeta", due=datetime(2026, 6, 25, 0, 0)),
            Todo(title="Alpha", due=datetime(2026, 6, 25, 0, 0)),
        ], now=NOW)
        thu = build_week(evs, date(2026, 6, 25), now=NOW).weeks[0][3]
        assert [e.title for e in thu.events] == ["A", "B", "Alpha", "Zeta"]

    def test_label_same_month(self):
        assert build_week([], date(2026, 6, 25), now=NOW).label == "Jun 22 - 28"

    def test_label_crosses_month(self):
        # week of Mon 2026-06-29 .. Sun 2026-07-05
        assert build_week([], date(2026, 6, 30), now=NOW).label == "Jun 29 - Jul 5"


class TestBuildMonth:
    def test_weeks_are_full_mon_sun_rows_with_padding_flagged(self):
        # June 2026: Jun 1 is a Monday, so the grid starts exactly on Jun 1 (no leading pad),
        # and the last week (Jun 29, 30, then Jul 1..5) has trailing padding from July.
        grid = build_month([], date(2026, 6, 15), now=NOW)
        assert grid.mode == "month"
        assert all(len(w) == 7 for w in grid.weeks)
        first = grid.weeks[0][0]
        assert first.day == date(2026, 6, 1) and first.in_period is True
        last = grid.weeks[-1][-1]
        assert last.day.month == 7        # trailing pad from July
        assert last.in_period is False

    def test_leading_pad_when_month_starts_midweek(self):
        # May 2026: May 1 is a Friday, so weeks[0] leads with Apr 27..30 (prev month, dimmed).
        grid = build_month([], date(2026, 5, 15), now=NOW)
        first = grid.weeks[0][0]
        assert first.day == date(2026, 4, 27) and first.in_period is False
        in_period = [c for w in grid.weeks for c in w if c.in_period]
        assert in_period[0].day == date(2026, 5, 1)

    def test_label_is_month_year(self):
        assert build_month([], date(2026, 6, 15), now=NOW).label == "June 2026"

    def test_event_placed_in_month_grid(self):
        evs = collect_events([Todo(title="Ship", due=datetime(2026, 6, 25, 0, 0))], now=NOW)
        grid = build_month(evs, date(2026, 6, 1), now=NOW)
        hits = [c for w in grid.weeks for c in w if c.events]
        assert len(hits) == 1 and hits[0].day == date(2026, 6, 25)


class TestBuildTimegrid:
    def test_places_timed_event_in_day_hour_cell(self):
        evs = collect_events([Todo(title="Standup", due=datetime(2026, 6, 30, 9, 0))], now=NOW)
        g = build_timegrid(evs, date(2026, 7, 1), now=NOW)  # week Mon 2026-06-29..Sun 07-05
        assert [e.title for e in g.cells[(date(2026, 6, 30), 9)]] == ["Standup"]

    def test_midnight_goes_to_all_day_but_0030_is_timed(self):  # C2
        evs = collect_events([Todo(title="AD", due=datetime(2026, 6, 30, 0, 0)),
                              Todo(title="Early", due=datetime(2026, 6, 30, 0, 30))], now=NOW)
        g = build_timegrid(evs, date(2026, 6, 30), now=NOW)
        assert [e.title for e in g.all_day[date(2026, 6, 30)]] == ["AD"]
        assert [e.title for e in g.cells[(date(2026, 6, 30), 0)]] == ["Early"]

    def test_strict_all_day_vs_timed_partition(self):  # C3
        evs = collect_events([Todo(title="AD", due=datetime(2026, 6, 30, 0, 0)),
                              Todo(title="Early", due=datetime(2026, 6, 30, 0, 30))], now=NOW)
        g = build_timegrid(evs, date(2026, 6, 30), now=NOW)
        all_day_titles = [e.title for v in g.all_day.values() for e in v]
        cell_titles = [e.title for v in g.cells.values() for e in v]
        assert set(all_day_titles).isdisjoint(cell_titles)

    def test_adjacent_week_event_not_placed(self):  # C1
        evs = collect_events([Todo(title="NextWk", due=datetime(2026, 7, 8, 9, 0))], now=NOW)
        g = build_timegrid(evs, date(2026, 7, 1), now=NOW)
        assert all("NextWk" not in [e.title for e in v] for v in g.cells.values())
        assert all("NextWk" not in [e.title for e in v] for v in g.all_day.values())

    def test_deterministic_cell_order(self):  # C4
        evs = collect_events([Todo(title="B", due=datetime(2026, 6, 30, 9, 0)),
                              Todo(title="A", due=datetime(2026, 6, 30, 9, 0)),
                              Todo(title="Zeta", due=datetime(2026, 6, 30, 0, 0)),
                              Todo(title="Alpha", due=datetime(2026, 6, 30, 0, 0))], now=NOW)
        g = build_timegrid(evs, date(2026, 6, 30), now=NOW)
        assert [e.title for e in g.cells[(date(2026, 6, 30), 9)]] == ["A", "B"]
        assert [e.title for e in g.all_day[date(2026, 6, 30)]] == ["Alpha", "Zeta"]

    def test_empty_week_full_skeleton(self):  # C5
        g = build_timegrid([], date(2026, 6, 30), now=NOW)
        assert len(g.days) == 7 and g.hours == list(range(24))
        assert g.all_day == {} and g.cells == {}

    def test_cross_year_label(self):  # C6
        g = build_timegrid([], date(2026, 12, 30), now=NOW)
        assert g.label == "Dec 28 - Jan 3"

    def test_today_is_now_date(self):
        g = build_timegrid([], date(2026, 6, 30), now=NOW)
        assert g.today == NOW.date()
