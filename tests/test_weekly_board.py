"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the Weekly Performance Board stats (this week vs last + hints).
Role:    Guards core.weekly_board.build_board: ranked categories, week-over-week deltas,
         totals and the deterministic optimization hints (spec sec 10 Wochen-Board).

Test classes:
- TestBuildBoard - ranking, deltas vs last week, totals, top category, empty week
- TestHints - the plain optimization hints (dominant category, rising category, momentum)
============================================================
"""

from datetime import datetime, timedelta

from serenity.core.activity import ActivityEntry
from serenity.core.weekly_board import build_board

# A Friday "now" so this-week = Mon 2026-06-15 .. ; last week = Mon 2026-06-08 ..
NOW = datetime(2026, 6, 19, 17, 30)
THIS_MON = datetime(2026, 6, 15, 9, 0)
LAST_MON = datetime(2026, 6, 8, 9, 0)


def hrs(n):
    return timedelta(hours=n)


class TestBuildBoard:
    def test_ranks_categories_busiest_first(self):
        entries = [
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(3)),
            ActivityEntry("Meeting", THIS_MON, THIS_MON + hrs(1)),
        ]
        board = build_board(entries, NOW)
        assert [c.category for c in board.categories] == ["Coding", "Meeting"]
        assert board.top_category == "Coding"

    def test_delta_vs_last_week(self):
        entries = [
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(3)),     # this week 3h
            ActivityEntry("Coding", LAST_MON, LAST_MON + hrs(1)),     # last week 1h
        ]
        board = build_board(entries, NOW)
        coding = board.categories[0]
        assert coding.seconds == 3 * 3600
        assert coding.prev_seconds == 1 * 3600
        assert coding.delta == 2 * 3600

    def test_totals_this_and_last_week(self):
        entries = [
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(2)),
            ActivityEntry("Meeting", THIS_MON, THIS_MON + hrs(1)),
            ActivityEntry("Coding", LAST_MON, LAST_MON + hrs(1)),
        ]
        board = build_board(entries, NOW)
        assert board.total_seconds == 3 * 3600
        assert board.prev_total_seconds == 1 * 3600
        assert board.total_delta == 2 * 3600

    def test_completed_count_passed_through(self):
        board = build_board([], NOW, completed_this_week=7)
        assert board.completed == 7

    def test_empty_week_has_no_categories(self):
        board = build_board([], NOW)
        assert board.categories == []
        assert board.top_category == ""
        assert board.total_seconds == 0

    def test_last_week_only_does_not_appear_this_week(self):
        entries = [ActivityEntry("Coding", LAST_MON, LAST_MON + hrs(2))]
        board = build_board(entries, NOW)
        # all time was last week -> nothing this week
        assert board.categories == []
        assert board.total_seconds == 0


class TestHints:
    def test_empty_week_hint(self):
        board = build_board([], NOW)
        assert any("No time tracked" in h for h in board.hints)

    def test_dominant_category_hint(self):
        # Coding is >60% of tracked time
        entries = [
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(5)),
            ActivityEntry("Meeting", THIS_MON, THIS_MON + hrs(1)),
        ]
        board = build_board(entries, NOW)
        assert any("most of your week" in h for h in board.hints)

    def test_rising_category_hint(self):
        entries = [
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(3)),     # +3h vs 0 last week
        ]
        board = build_board(entries, NOW)
        assert any("up 3h vs last week" in h for h in board.hints)

    def test_momentum_hint_counts_completed(self):
        board = build_board([], NOW, completed_this_week=4)
        assert any("completed 4 todos" in h for h in board.hints)

    def test_hints_use_single_hyphen_no_em_dash(self):
        entries = [ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(5)),
                   ActivityEntry("Meeting", THIS_MON, THIS_MON + hrs(1))]
        board = build_board(entries, NOW, completed_this_week=2)
        joined = " ".join(board.hints)
        assert "--" not in joined and "—" not in joined and "–" not in joined
