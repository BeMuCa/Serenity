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
    tick,
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

    def test_700_nearest_is_60(self):
        """700: distance to 60 is 640, to 1440 is 740 -> 60 is nearer."""
        # 700 - 60 = 640, 1440 - 700 = 740 -> 60 is closer
        assert snap_to_rung(700) == 60

    def test_small_value_snaps_to_5(self):
        """3 is closer to 5 (distance 2) than to 30 (distance 27)."""
        assert snap_to_rung(3) == 5

    def test_very_large_value_snaps_to_largest(self):
        """999999 is closest to 10080 (the largest rung)."""
        assert snap_to_rung(999999) == 10080

    def test_45_midpoint_ties_to_60(self):
        """45 is equidistant from 30 and 60 (distance 15 each); ties favor larger 60."""
        assert snap_to_rung(45) == 60

    def test_750_midpoint_ties_to_1440(self):
        """750 is equidistant from 60 and 1440 (distance 690 each); ties favor larger 1440."""
        assert snap_to_rung(750) == 1440

    def test_5760_midpoint_ties_to_10080(self):
        """5760 is equidistant from 1440 and 10080 (distance 4320 each); ties favor larger 10080."""
        assert snap_to_rung(5760) == 10080


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

    def test_exact_boundary_rung_excluded(self):
        """When due - offset·min == now exactly, that rung is EXCLUDED (strict future)."""
        # Set up so that exactly 60 min before due is now: due = now + 60 min
        due = NOW + timedelta(minutes=60)
        # Fire time for offset=60 is exactly NOW (not future), so excluded
        todo = mk_todo(due=due, reminder_offsets=[60])
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

    def test_en_sub_minute_future_rounds_up(self):
        """English: 30 seconds future rounds up to 1 min."""
        due = NOW + timedelta(seconds=30)
        result = relative_phrase(due, NOW, "en")
        assert result == "in 1 min"

    def test_de_sub_minute_future_rounds_up(self):
        """German: 30 seconds future rounds up to 1 Min."""
        due = NOW + timedelta(seconds=30)
        result = relative_phrase(due, NOW, "de")
        assert result == "in 1 Min"

    def test_en_sub_minute_overdue_rounds_down(self):
        """English: 89 seconds overdue rounds down to 1 min."""
        due = NOW - timedelta(seconds=89)
        result = relative_phrase(due, NOW, "en")
        assert result == "overdue 1 min"

    def test_de_sub_minute_overdue_rounds_down(self):
        """German: 89 seconds overdue rounds down to 1 Min."""
        due = NOW - timedelta(seconds=89)
        result = relative_phrase(due, NOW, "de")
        assert result == "seit 1 Min überfällig"


class TestConstants:
    """Verify constants are defined and have expected values."""

    def test_rung_minutes_order(self):
        """RUNG_MINUTES should be [10080, 1440, 60, 30, 5] in descending order."""
        assert RUNG_MINUTES == [10080, 1440, 60, 30, 5]

    def test_rung_labels_dict_keys_match_rungs(self):
        """RUNG_LABELS should be a dict mapping rung minutes to labels."""
        assert RUNG_LABELS[10080] == "1 week"
        assert RUNG_LABELS[1440] == "1 day"
        assert RUNG_LABELS[60] == "1 hour"
        assert RUNG_LABELS[30] == "30 min"
        assert RUNG_LABELS[5] == "5 min"
        assert set(RUNG_LABELS) == set(RUNG_MINUTES)

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


class TestTick:
    """tick(todo, now) returns Fire or None; mutates reminder_* fields."""

    # ===== GUARD TESTS =====
    def test_guard_done_returns_none_no_mutation(self):
        """Done todo: return None, no mutation of reminder_* fields."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
            done=True,
        )
        nudge_before = todo.reminder_nudge_at
        result = tick(todo, NOW)
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_fired == []
        assert todo.reminder_nudge_at == nudge_before

    def test_guard_deleted_returns_none_no_mutation(self):
        """Deleted todo: return None, no mutation of reminder_* fields."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
            deleted=True,
        )
        nudge_before = todo.reminder_nudge_at
        result = tick(todo, NOW)
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_fired == []
        assert todo.reminder_nudge_at == nudge_before

    def test_guard_no_due_returns_none_no_mutation(self):
        """No due: return None, no mutation."""
        todo = mk_todo(
            id="t1",
            due=None,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        nudge_before = todo.reminder_nudge_at
        result = tick(todo, NOW)
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_fired == []
        assert todo.reminder_nudge_at == nudge_before

    def test_guard_no_offsets_returns_none_no_mutation(self):
        """No reminder_offsets: return None, no mutation."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        nudge_before = todo.reminder_nudge_at
        result = tick(todo, NOW)
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_fired == []
        assert todo.reminder_nudge_at == nudge_before

    # ===== STEP 1: ACTIVE ALREADY SET =====
    def test_step1_active_set_returns_none(self):
        """Step 1: reminder_active is not None → return None (never stack)."""
        due = NOW + timedelta(minutes=10)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[30, 5],
            reminder_fired=[],
            reminder_active=5,  # already active
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        assert result is None
        # active should remain 5 (no change)
        assert todo.reminder_active == 5

    def test_step1_active_nudge_sentinel_returns_none(self):
        """Step 1: reminder_active is NUDGE_SENTINEL (0) → return None."""
        due = NOW + timedelta(minutes=10)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[30, 5],
            reminder_fired=[0],
            reminder_active=NUDGE_SENTINEL,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        assert result is None
        assert todo.reminder_active == NUDGE_SENTINEL

    # ===== STEP 2: NUDGE DUE =====
    def test_step2_nudge_due_fires(self):
        """Step 2: nudge_at in past → fire nudge, set active=0, clear nudge_at."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW - timedelta(minutes=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=nudge_at,
        )
        result = tick(todo, NOW)
        assert result == Fire(todo_id="t1", offset=0, is_nudge=True)
        assert todo.reminder_active == NUDGE_SENTINEL
        assert todo.reminder_nudge_at is None

    def test_step2_nudge_exactly_now_fires(self):
        """Step 2: nudge_at == now (boundary) → fire nudge."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=nudge_at,
        )
        result = tick(todo, NOW)
        assert result == Fire(todo_id="t1", offset=0, is_nudge=True)
        assert todo.reminder_active == NUDGE_SENTINEL
        assert todo.reminder_nudge_at is None

    def test_step2_nudge_future_does_not_fire(self):
        """Step 2: nudge_at in future → don't fire (skip to step 3)."""
        due = NOW + timedelta(hours=2)
        nudge_at = NOW + timedelta(minutes=30)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=nudge_at,
        )
        result = tick(todo, NOW)
        # Nudge is not due yet, so no fire; and 60 is not due yet either
        assert result is None

    def test_guard_beats_pending_nudge_no_offsets(self):
        """Guard beats pending nudge: empty reminder_offsets → return None, nudge_at unchanged.

        When reminder_offsets is empty, the guard fires (line 161) BEFORE step 2 can fire the
        nudge. Result: None, nudge_at untouched.
        """
        due = NOW + timedelta(hours=1)
        nudge_at = NOW - timedelta(minutes=1)  # nudge is due
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[],  # guard fires here
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=nudge_at,
        )
        result = tick(todo, NOW)
        # Guard prevents step 2 from firing
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at == nudge_at  # unchanged

    def test_guard_beats_pending_nudge_no_due(self):
        """Guard beats pending nudge: no due → return None, nudge_at unchanged.

        When due is None, the guard fires BEFORE step 2. Result: None, nudge_at untouched.
        """
        nudge_at = NOW - timedelta(minutes=1)  # nudge is due
        todo = mk_todo(
            id="t1",
            due=None,  # guard fires here
            reminder_offsets=[60],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=nudge_at,
        )
        result = tick(todo, NOW)
        # Guard prevents step 2 from firing
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at == nudge_at  # unchanged

    # ===== STEP 3: COLLAPSE =====
    def test_step3_single_rung_fires_exactly_at_time(self):
        """Step 3: single rung fires exactly at its fire time (not 1s before)."""
        # 5 min rung fires at due - 5 min
        due = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # NOW == due - 5 min, so it fires
        assert result == Fire(todo_id="t1", offset=5, is_nudge=False)
        assert todo.reminder_active == 5
        assert todo.reminder_fired == [5]

    def test_step3_single_rung_does_not_fire_before_time(self):
        """Step 3: rung does not fire 1s before its time."""
        # 5 min rung fires at due - 5 min; we're 1s before that
        due = NOW + timedelta(minutes=5, seconds=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # NOW is 1s before fire time
        assert result is None

    def test_step3_collapse_multiple_past_rungs(self):
        """Step 3: collapse armed [1440,60,5] all past → ONE Fire(offset=5), fired=[1440,60,5], active=5."""
        # All three rungs are past (fire times have passed)
        due = NOW + timedelta(minutes=4)  # due very soon
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[1440, 60, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # Fire times: 1440 min before = NOW - 1436 min (past)
        # 60 min before = NOW - 56 min (past), 5 min before = NOW - 1 min (past)
        assert result == Fire(todo_id="t1", offset=5, is_nudge=False)
        assert todo.reminder_active == 5
        # All three should be marked as fired, deduplicated, in known-rungs order
        assert set(todo.reminder_fired) == {1440, 60, 5}

    def test_step3_collapse_marks_all_fired_only_once(self):
        """Step 3: collapse marks each rung as fired exactly once (no duplicates)."""
        due = NOW + timedelta(minutes=3)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        assert result == Fire(todo_id="t1", offset=5, is_nudge=False)
        # Each offset appears exactly once in fired (deduplicated)
        assert todo.reminder_fired.count(60) == 1
        assert todo.reminder_fired.count(30) == 1
        assert todo.reminder_fired.count(5) == 1

    def test_step3_collapse_fires_minimum_offset(self):
        """Step 3: collapse fires the minimum (closest to due) offset."""
        due = NOW + timedelta(minutes=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[1440, 60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # All four are past; min is 5
        assert result.offset == 5
        assert todo.reminder_active == 5

    def test_step3_only_future_rungs_no_collapse(self):
        """Step 3: no armed-unfired rungs in past → return None."""
        # Use due = NOW + 90 min so 60-min offset fires at NOW+30 (future)
        due = NOW + timedelta(minutes=90)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # Fire times: 60 = NOW + 30 (future), 30 = NOW + 60 (future), 5 = NOW + 85 (future)
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_fired == []

    def test_step3_partial_collapse_only_past_rungs(self):
        """Step 3: collapse only includes rungs that are past."""
        due = NOW + timedelta(minutes=50)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[1440, 60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # Fire times: 1440 = NOW - 1390 (past), 60 = NOW - 10 (past),
        # 30 = NOW + 20 (future), 5 = NOW + 45 (future)
        # Only 1440 and 60 are past; collapse on those
        assert result == Fire(todo_id="t1", offset=60, is_nudge=False)
        assert todo.reminder_active == 60
        # Only past rungs marked as fired
        assert set(todo.reminder_fired) == {1440, 60}

    def test_step3_already_fired_offset_not_collected(self):
        """Step 3: CRITICAL — collect only armed-UNFIRED offsets; skip already-fired.

        Reproducer: due=now+10min, reminder_offsets=[60,5], reminder_fired=[60]
        → 60 is past but already fired; 5 is future
        → Result should be None (nothing to collect)
        → reminder_fired unchanged, reminder_active unchanged
        """
        due = NOW + timedelta(minutes=10)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60],  # 60 already fired
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        # Fire time for 60: NOW + 10 - 60 = NOW - 50 (past, but already fired)
        # Fire time for 5: NOW + 10 - 5 = NOW + 5 (future)
        # Only armed-UNFIRED offsets should be collected; 60 is out, 5 not due yet
        # Result: no collection, return None
        assert result is None
        assert todo.reminder_active is None
        assert todo.reminder_fired == [60]  # unchanged

    # ===== NUDGE WINS OVER STEP 3 =====
    def test_nudge_wins_over_step3(self):
        """Nudge due takes precedence over step 3 (even if rungs are past)."""
        due = NOW + timedelta(minutes=2)
        nudge_at = NOW - timedelta(minutes=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=nudge_at,
        )
        result = tick(todo, NOW)
        # Both nudge and step 3 could fire, but nudge wins
        assert result == Fire(todo_id="t1", offset=0, is_nudge=True)
        assert todo.reminder_active == NUDGE_SENTINEL
        assert todo.reminder_nudge_at is None
        # Prove that rungs were NOT marked as fired when nudge took precedence
        assert todo.reminder_fired == []

    # ===== MUTATION CHECKS =====
    def test_fire_mutates_fired_and_active_never_due(self):
        """Fire mutates reminder_fired and reminder_active but NEVER touches due."""
        due = NOW + timedelta(minutes=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        due_before = todo.due
        result = tick(todo, NOW)
        # Verify due was never touched
        assert todo.due == due_before
        assert result is not None

    def test_no_mutation_on_none_return(self):
        """When tick returns None (guards/step1), no fields mutate."""
        # Use due far in future so 60-min offset doesn't fire
        due = NOW + timedelta(hours=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        result = tick(todo, NOW)
        assert result is None
        # All fields should be unchanged
        assert todo.reminder_active is None
        assert todo.reminder_fired == []
        assert todo.reminder_nudge_at is None

    def test_sequential_flow_fire_then_step1_blocks_second_tick(self):
        """Sequential: first tick() fires (collapse), immediately-following tick() returns None via step-1.

        After the first tick fires and sets reminder_active, the second tick should
        return None (step 1 blocks stacking) even if rungs are still past.
        """
        due = NOW + timedelta(minutes=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # First tick: collapse fires (all rungs past)
        result1 = tick(todo, NOW)
        assert result1 == Fire(todo_id="t1", offset=5, is_nudge=False)
        assert todo.reminder_active == 5
        assert 5 in todo.reminder_fired

        # Second tick at same NOW: step 1 blocks (reminder_active is set)
        result2 = tick(todo, NOW)
        assert result2 is None
        # Active should remain unchanged, fired should not grow
        assert todo.reminder_active == 5
        assert todo.reminder_fired.count(5) == 1  # still just one instance
