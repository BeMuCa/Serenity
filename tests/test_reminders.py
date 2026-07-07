"""
============================================================
Author:  Berk
Created: 2026-07-07
Purpose: Unit tests for the reminders module (ladder, rung-snapping, armable offsets, relative phrases).
Role:    Guards core.reminders: snap_to_rung boundaries, armable_offsets future-only filtering,
         relative_phrase localization (en/de), Fire dataclass structure. Pure, injected clock.

Test classes:
- TestSnapToRung - boundary rounding to nearest rung, ties toward LARGER/earlier
- TestArmableOffsets - future-only offset filtering, due=None returns []
- TestRelativePhrase - en/de localization, overdue detection, no colon times
============================================================
"""

from datetime import datetime, timedelta

from serenity.core.models import Todo
from serenity.core.reminders import (
    NUDGE_MINUTES,
    NUDGE_SENTINEL,
    RUNG_LABELS,
    RUNG_MINUTES,
    Fire,
    armable_offsets,
    relative_phrase,
    snap_to_rung,
)

NOW = datetime(2026, 7, 7, 12, 0, 0)


def mk_todo(due=None, reminder_offsets=None, **kw):
    """Helper to make a Todo with optional due and reminder_offsets."""
    return Todo(due=due, reminder_offsets=reminder_offsets or [], **kw)


class TestSnapToRung:
    """snap_to_rung(minutes) rounds to nearest rung; ties favor LARGER/earlier rungs."""

    def test_exact_match(self):
        """Exact rung value returns unchanged."""
        assert snap_to_rung(10080) == 10080
        assert snap_to_rung(1440) == 1440
        assert snap_to_rung(60) == 60
        assert snap_to_rung(30) == 30
        assert snap_to_rung(5) == 5

    def test_1440_boundary_ties_to_larger(self):
        """1440 ± 60 (midpoint between 1440 and 60 by distance) ties to 1440."""
        # Distance to 1440: 0, to 60: 1380 -> 1440 wins
        assert snap_to_rung(1440) == 1440
        # 750 is equidistant from 60 and 1440 (690 and 690), tie goes to larger 1440
        # Actually 750 - 60 = 690, 1440 - 750 = 690, so ties go to 1440
        assert snap_to_rung(750) == 1440

    def test_700_ties_to_1440(self):
        """700: distance to 60 is 640, to 1440 is 740 -> 60 is nearer."""
        # 700 - 60 = 640, 1440 - 700 = 740 -> 60 is closer
        assert snap_to_rung(700) == 60

    def test_small_value_snaps_to_5(self):
        """3 is closer to 5 (distance 2) than to 30 (distance 27)."""
        assert snap_to_rung(3) == 5

    def test_very_large_value_snaps_to_largest(self):
        """999999 is closest to 10080 (the largest rung)."""
        assert snap_to_rung(999999) == 10080


class TestArmableOffsets:
    """armable_offsets(todo, now) returns rungs whose fire time is still in the future."""

    def test_no_due_returns_empty(self):
        """No due date -> no armable offsets."""
        todo = mk_todo(due=None)
        assert armable_offsets(todo, NOW) == []

    def test_due_2_hours_away_returns_60_30_5(self):
        """Due in 2 hours (120 min): 60, 30, 5 are future; 1440, 10080 are past."""
        due = NOW + timedelta(minutes=120)
        todo = mk_todo(due=due, reminder_offsets=[10080, 1440, 60, 30, 5])
        result = armable_offsets(todo, NOW)
        # Fire times: 10080 min before = NOW - 9960 min (past), 1440 = NOW - 1320 (past),
        # 60 = NOW + 60 (future), 30 = NOW + 90 (future), 5 = NOW + 115 (future)
        assert result == [60, 30, 5]

    def test_due_at_now_plus_50_min_returns_30_and_5(self):
        """Due in 50 min: 30 and 5 are future (fire at +20m and +45m); 60 is past (fires at -10m)."""
        due = NOW + timedelta(minutes=50)
        todo = mk_todo(due=due, reminder_offsets=[1440, 60, 30, 5])
        result = armable_offsets(todo, NOW)
        assert result == [30, 5]

    def test_due_past_returns_empty(self):
        """Due in the past: all offsets are past -> empty."""
        due = NOW - timedelta(hours=1)
        todo = mk_todo(due=due, reminder_offsets=[60, 30, 5])
        result = armable_offsets(todo, NOW)
        assert result == []

    def test_empty_reminder_offsets_returns_empty(self):
        """No armed offsets -> empty result."""
        due = NOW + timedelta(hours=2)
        todo = mk_todo(due=due, reminder_offsets=[])
        result = armable_offsets(todo, NOW)
        assert result == []


class TestRelativePhrase:
    """relative_phrase(due, now, lang) formats relative time in en/de without colons."""

    def test_en_in_the_future(self):
        """English: 'in X min' or 'in X h' or 'in X h Y min'."""
        due = NOW + timedelta(minutes=47)
        result = relative_phrase(due, NOW, "en")
        assert "in 47 min" == result

    def test_en_future_hours_and_minutes(self):
        """English: 'in X h Y min' when both hours and minutes."""
        due = NOW + timedelta(hours=3, minutes=10)
        result = relative_phrase(due, NOW, "en")
        assert result == "in 3 h 10 min"

    def test_en_future_hours_only(self):
        """English: 'in X h' when no remainder minutes."""
        due = NOW + timedelta(hours=2)
        result = relative_phrase(due, NOW, "en")
        assert result == "in 2 h"

    def test_en_overdue(self):
        """English: 'overdue X min' when past due."""
        due = NOW - timedelta(minutes=12)
        result = relative_phrase(due, NOW, "en")
        assert result == "overdue 12 min"

    def test_de_future_minutes_only(self):
        """German: 'in X Min' when only minutes."""
        due = NOW + timedelta(minutes=30)
        result = relative_phrase(due, NOW, "de")
        assert result == "in 30 Min"

    def test_de_future_hours_and_minutes(self):
        """German: 'in X Std Y Min' with hours and minutes."""
        due = NOW + timedelta(hours=3, minutes=10)
        result = relative_phrase(due, NOW, "de")
        assert result == "in 3 Std 10 Min"

    def test_de_future_hours_only(self):
        """German: 'in X Std' with no remainder."""
        due = NOW + timedelta(hours=2)
        result = relative_phrase(due, NOW, "de")
        assert result == "in 2 Std"

    def test_de_overdue(self):
        """German: 'seit X Min überfällig' when past due."""
        due = NOW - timedelta(minutes=12)
        result = relative_phrase(due, NOW, "de")
        assert result == "seit 12 Min überfällig"

    def test_no_colon_in_output(self):
        """Ensure no `:` character in any output (wall-clock time format banned)."""
        test_cases = [
            (NOW + timedelta(minutes=5), "en"),
            (NOW + timedelta(hours=1), "en"),
            (NOW + timedelta(hours=1, minutes=30), "en"),
            (NOW - timedelta(minutes=5), "en"),
            (NOW + timedelta(minutes=5), "de"),
            (NOW + timedelta(hours=1), "de"),
            (NOW + timedelta(hours=1, minutes=30), "de"),
            (NOW - timedelta(minutes=5), "de"),
        ]
        for due, lang in test_cases:
            result = relative_phrase(due, NOW, lang)
            assert ":" not in result, f"Colon found in '{result}' (due={due}, lang={lang})"


class TestConstants:
    """Verify constants are defined and have expected values."""

    def test_rung_minutes_order(self):
        """RUNG_MINUTES should be [10080, 1440, 60, 30, 5] in descending order."""
        assert RUNG_MINUTES == [10080, 1440, 60, 30, 5]

    def test_rung_labels_count_and_content(self):
        """RUNG_LABELS should have 5 labels matching the rungs."""
        assert len(RUNG_LABELS) == 5
        expected = ["1 week", "1 day", "1 hour", "30 min", "5 min"]
        assert RUNG_LABELS == expected

    def test_nudge_minutes(self):
        """NUDGE_MINUTES should be 5."""
        assert NUDGE_MINUTES == 5

    def test_nudge_sentinel(self):
        """NUDGE_SENTINEL should be 0."""
        assert NUDGE_SENTINEL == 0


class TestFireDataclass:
    """Fire dataclass should have todo_id, offset, is_nudge fields."""

    def test_fire_creation(self):
        """Create a Fire instance with all fields."""
        fire = Fire(todo_id="abc123", offset=60, is_nudge=False)
        assert fire.todo_id == "abc123"
        assert fire.offset == 60
        assert fire.is_nudge is False

    def test_fire_nudge(self):
        """Create a nudge Fire (offset=0, is_nudge=True)."""
        fire = Fire(todo_id="xyz789", offset=0, is_nudge=True)
        assert fire.todo_id == "xyz789"
        assert fire.offset == 0
        assert fire.is_nudge is True
