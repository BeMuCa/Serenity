"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for activity-time aggregation + the Friday auto-open board trigger.
Role:    Guards core.activity: per-category second aggregation over a window, the
         single-running-span log, week-totals, and the once-per-day Friday 17-18h rule
         that auto-opens the Weekly Performance Board (spec sec 10).

Test classes:
- TestActivityEntry - span duration, running span, non-negative clamp
- TestAggregateSeconds - per-category totals, window filtering, top categories
- TestActivityLog - start closes the open span, week_totals, total_seconds
- TestAutoOpenTrigger - the Friday 17-18h once-a-day board rule
============================================================
"""

from datetime import datetime, timedelta

from serenity.core.activity import (
    ActivityEntry,
    ActivityLog,
    aggregate_seconds,
    should_auto_open_board,
    top_categories,
    week_start,
)

# A known Friday and the following days for the trigger tests.
FRI = datetime(2026, 6, 19, 9, 0, 0)        # Friday
WED = datetime(2026, 6, 17, 9, 0, 0)        # Wednesday (mid-week, for week math)


class TestActivityEntry:
    def test_closed_span_seconds(self):
        e = ActivityEntry("Coding", FRI, FRI + timedelta(minutes=30))
        assert e.seconds() == 1800

    def test_running_span_counts_to_now(self):
        e = ActivityEntry("Coding", FRI)            # no end -> running
        assert e.seconds(now=FRI + timedelta(minutes=10)) == 600

    def test_negative_span_clamps_to_zero(self):
        # end before start (clock skew) must never log negative time
        e = ActivityEntry("Coding", FRI, FRI - timedelta(minutes=5))
        assert e.seconds() == 0


class TestAggregateSeconds:
    def test_sums_per_category(self):
        entries = [
            ActivityEntry("Coding", FRI, FRI + timedelta(minutes=30)),
            ActivityEntry("Coding", FRI + timedelta(hours=1), FRI + timedelta(hours=1, minutes=30)),
            ActivityEntry("Meeting", FRI + timedelta(hours=2), FRI + timedelta(hours=3)),
        ]
        out = aggregate_seconds(entries)
        assert out == {"Coding": 3600, "Meeting": 3600}

    def test_zero_length_categories_omitted(self):
        entries = [ActivityEntry("Idle", FRI, FRI)]     # 0 seconds
        assert aggregate_seconds(entries) == {}

    def test_window_filters_by_start(self):
        entries = [
            ActivityEntry("Old", FRI - timedelta(days=2), FRI - timedelta(days=2) + timedelta(minutes=10)),
            ActivityEntry("New", FRI, FRI + timedelta(minutes=10)),
        ]
        out = aggregate_seconds(entries, since=FRI - timedelta(hours=1))
        assert out == {"New": 600}

    def test_span_crossing_a_bound_is_clipped_to_window(self):
        # a span that starts before `since` is counted only for its in-window portion,
        # not all-or-nothing on its start time.
        e = ActivityEntry("Coding", FRI - timedelta(hours=1), FRI + timedelta(hours=1))
        # window [FRI, ...) -> only the hour after FRI counts
        assert aggregate_seconds([e], since=FRI) == {"Coding": 3600}
        # window [..., FRI) -> only the hour before FRI counts
        assert aggregate_seconds([e], until=FRI) == {"Coding": 3600}

    def test_running_span_split_across_week_boundary(self):
        # a running span started last week, still open this week, must split between
        # the weeks (not be bucketed entirely into the start's week).
        prev_mon = datetime(2026, 6, 8, 0, 0)       # Monday of FRI's prior week
        this_mon = datetime(2026, 6, 15, 0, 0)      # Monday of FRI's week
        now = FRI + timedelta(hours=3)              # Friday 12:00, span still running
        span = ActivityEntry("Coding", this_mon - timedelta(hours=2))   # started prev week
        last_week = aggregate_seconds([span], since=prev_mon, until=this_mon, now=now)
        this_week = aggregate_seconds([span], since=this_mon, now=now)
        assert last_week == {"Coding": 2 * 3600}                         # the 2h before Monday
        assert this_week == {"Coding": int((now - this_mon).total_seconds())}

    def test_top_categories_busiest_first(self):
        entries = [
            ActivityEntry("Coding", FRI, FRI + timedelta(hours=2)),
            ActivityEntry("Meeting", FRI, FRI + timedelta(hours=1)),
            ActivityEntry("Email", FRI, FRI + timedelta(minutes=30)),
        ]
        ranked = top_categories(entries, limit=2)
        assert ranked == [("Coding", 7200), ("Meeting", 3600)]

    def test_top_categories_ties_broken_by_name(self):
        entries = [
            ActivityEntry("Zebra", FRI, FRI + timedelta(minutes=10)),
            ActivityEntry("Apple", FRI, FRI + timedelta(minutes=10)),
        ]
        ranked = top_categories(entries)
        assert ranked == [("Apple", 600), ("Zebra", 600)]


class TestActivityLog:
    def test_start_closes_previous_span(self):
        log = ActivityLog()
        log.start("Coding", FRI)
        log.start("Meeting", FRI + timedelta(minutes=30))    # closes Coding at +30
        coding = log.entries()[0]
        assert coding.end == FRI + timedelta(minutes=30)
        assert log.running().category == "Meeting"

    def test_stop_closes_running(self):
        log = ActivityLog()
        log.start("Coding", FRI)
        closed = log.stop(FRI + timedelta(minutes=15))
        assert closed.end == FRI + timedelta(minutes=15)
        assert log.running() is None

    def test_running_span_in_week_totals(self):
        log = ActivityLog()
        log.start("Coding", FRI)                 # still running
        totals = log.week_totals(now=FRI + timedelta(minutes=20))
        assert totals == {"Coding": 1200}

    def test_total_seconds_across_categories(self):
        log = ActivityLog()
        log.start("Coding", FRI)
        log.start("Meeting", FRI + timedelta(minutes=10))
        log.stop(FRI + timedelta(minutes=25))
        # Coding 10min + Meeting 15min = 1500s
        assert log.total_seconds(now=FRI + timedelta(minutes=25)) == 1500

    def test_week_totals_excludes_last_week(self):
        log = ActivityLog([
            ActivityEntry("Old", FRI - timedelta(days=8), FRI - timedelta(days=8) + timedelta(hours=1)),
            ActivityEntry("New", WED, WED + timedelta(hours=1)),
        ])
        # WED is in FRI's week; the 8-days-ago entry is the prior week and excluded
        assert log.week_totals(now=FRI) == {"New": 3600}


class TestWeekStart:
    def test_friday_week_starts_monday(self):
        # Friday 2026-06-19 -> Monday 2026-06-15
        assert week_start(FRI) == datetime(2026, 6, 15).date()

    def test_monday_is_its_own_week_start(self):
        mon = datetime(2026, 6, 15, 23, 0)
        assert week_start(mon) == datetime(2026, 6, 15).date()


class TestAutoOpenTrigger:
    def test_opens_friday_in_window(self):
        assert should_auto_open_board(datetime(2026, 6, 19, 17, 30), None) is True

    def test_opens_at_window_start_1700(self):
        assert should_auto_open_board(datetime(2026, 6, 19, 17, 0), None) is True

    def test_not_at_window_end_1800(self):
        # 18:00 is exclusive -> the window is [17, 18)
        assert should_auto_open_board(datetime(2026, 6, 19, 18, 0), None) is False

    def test_not_before_window(self):
        assert should_auto_open_board(datetime(2026, 6, 19, 16, 59), None) is False

    def test_not_on_thursday(self):
        assert should_auto_open_board(datetime(2026, 6, 18, 17, 30), None) is False

    def test_not_on_saturday(self):
        assert should_auto_open_board(datetime(2026, 6, 20, 17, 30), None) is False

    def test_only_once_per_day(self):
        now = datetime(2026, 6, 19, 17, 45)
        opened_earlier = datetime(2026, 6, 19, 17, 5)
        assert should_auto_open_board(now, opened_earlier) is False

    def test_opens_again_next_friday(self):
        now = datetime(2026, 6, 26, 17, 30)             # next Friday
        last = datetime(2026, 6, 19, 17, 5)             # last week
        assert should_auto_open_board(now, last) is True
