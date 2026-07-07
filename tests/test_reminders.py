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
- TestConstants - verify RUNG_MINUTES, RUNG_LABELS, NUDGE_MINUTES, NUDGE_SENTINEL
- TestFireDataclass - Fire(todo_id, offset, is_nudge) structure
- TestTick - guards, step 1 (active set), step 2 (nudge due), step 3 (collapse)
- TestPreMarkPast - union past-due offsets into reminder_fired, preserve sentinel 0
- TestSilence - clear reminder_active and reminder_nudge_at
- TestAcknowledgeSnooze - snooze to next lower rung or schedule nudge
- TestAcknowledgeDismiss - mark all offsets fired, clear active and nudge
- TestArm - set reminder_offsets with delta-semantics, preserve fired state
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
    acknowledge_dismiss,
    acknowledge_snooze,
    armable_offsets,
    arm,
    pre_mark_past,
    relative_phrase,
    silence,
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


class TestPreMarkPast:
    """pre_mark_past(todo, now) adds offsets already past to reminder_fired."""

    def test_no_op_when_due_none(self):
        """Guard: due is None → no-op, no mutation."""
        todo = mk_todo(
            id="t1",
            due=None,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
        )
        pre_mark_past(todo, NOW)
        assert todo.reminder_fired == []

    def test_marks_past_offsets_fired(self):
        """Offsets whose fire time is already past are added to reminder_fired."""
        # Due in 10 min: 60 and 30 are past, 5 is future
        due = NOW + timedelta(minutes=10)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
        )
        pre_mark_past(todo, NOW)
        # 60: fire at NOW + 10 - 60 = NOW - 50 (past)
        # 30: fire at NOW + 10 - 30 = NOW - 20 (past)
        # 5: fire at NOW + 10 - 5 = NOW + 5 (future)
        assert 60 in todo.reminder_fired
        assert 30 in todo.reminder_fired
        assert 5 not in todo.reminder_fired

    def test_preserves_existing_fired(self):
        """New past offsets are UNIONED with existing fired, no duplicates."""
        due = NOW + timedelta(minutes=10)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[60],  # 60 already fired
        )
        pre_mark_past(todo, NOW)
        # 60 and 30 are past; 60 is already in fired, 30 is new
        assert set(todo.reminder_fired) == {60, 30}

    def test_maintains_dedup_and_order(self):
        """reminder_fired maintains descending order, no duplicates."""
        due = NOW + timedelta(minutes=10)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
        )
        pre_mark_past(todo, NOW)
        # 60 and 30 are past; should be in descending order
        assert todo.reminder_fired == [60, 30]

    def test_preserves_sentinel_0_in_fired(self):
        """CRITICAL: pre_mark_past preserves sentinel 0 in reminder_fired.

        When 0 (nudge sentinel) is present in reminder_fired before pre_mark_past,
        it must survive the union + filter operation. Reproducer:
        - offsets=[60], fired=[60, 0], due=far future (no new past offsets)
        - pre_mark_past should keep both 60 and 0 in fired
        """
        due = NOW + timedelta(hours=2)  # far future: 60 won't become past
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60],
            reminder_fired=[60, 0],  # nudge sentinel present
        )
        pre_mark_past(todo, NOW)
        # Even though nothing new becomes past, the 0 should survive
        assert set(todo.reminder_fired) == {60, 0}
        # AND it should maintain the order: rungs descending, then 0
        assert todo.reminder_fired == [60, 0]


class TestSilence:
    """silence(todo) clears reminder_active and reminder_nudge_at."""

    def test_silence_clears_active_and_nudge(self):
        """Silence clears both active and nudge_at."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=nudge_at,
        )
        silence(todo)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_silence_leaves_offsets_and_fired(self):
        """Silence does NOT touch reminder_offsets or reminder_fired."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=None,
        )
        silence(todo)
        assert todo.reminder_offsets == [60, 30, 5]
        assert todo.reminder_fired == [60]

    def test_silence_when_already_silent(self):
        """Silence is idempotent (already silent → stays silent)."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        silence(todo)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None


class TestAcknowledgeSnooze:
    """acknowledge_snooze(todo, now) escalates or nudges."""

    def test_snooze_no_op_when_active_none(self):
        """Snooze when active is None → no-op."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        acknowledge_snooze(todo, NOW)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_snooze_with_smaller_armed_unfired_rung_clears_active(self):
        """Snooze 60 when smaller armed-unfired 5 exists → just clear active (ladder walks)."""
        due = NOW + timedelta(minutes=80)
        # Armed [60, 5]; 60 is ringing (fired + active), 5 is unfired and future
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=None,
        )
        acknowledge_snooze(todo, NOW)
        # Only active cleared; everything else unchanged
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None
        assert todo.reminder_offsets == [60, 5]
        assert todo.reminder_fired == [60]

    def test_snooze_bottom_rung_sets_nudge(self):
        """Snooze the bottom rung (5) → set nudge_at = now + 5 min, clear active."""
        due = NOW + timedelta(minutes=80)
        # Armed [60, 5]; 5 is ringing and the last rung
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60, 5],
            reminder_active=5,
            reminder_nudge_at=None,
        )
        acknowledge_snooze(todo, NOW)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at == NOW + timedelta(minutes=NUDGE_MINUTES)

    def test_snooze_nudge_sets_new_nudge(self):
        """Snooze a nudge (active=0) → schedule another nudge."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[5],
            reminder_fired=[5, 0],
            reminder_active=NUDGE_SENTINEL,
            reminder_nudge_at=None,
        )
        acknowledge_snooze(todo, NOW)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at == NOW + timedelta(minutes=NUDGE_MINUTES)

    def test_snooze_single_armed_rung_sets_nudge(self):
        """Snooze the only armed rung [30] when active=30 → nudge branch (no smaller rung)."""
        due = NOW + timedelta(minutes=80)
        # Armed [30]; 30 is ringing and the only (thus bottom) rung
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[30],
            reminder_fired=[30],
            reminder_active=30,
            reminder_nudge_at=None,
        )
        acknowledge_snooze(todo, NOW)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at == NOW + timedelta(minutes=NUDGE_MINUTES)
        assert todo.reminder_offsets == [30]  # Unchanged
        assert todo.reminder_fired == [30]  # Unchanged

    def test_escalation_snooze_upper_rung_fires_lower_immediately(self):
        """[C-1] Escalation: snooze 60 when lower 5's fire time already past → next tick fires 5.

        Sequence:
        1. Armed [60, 5]; 60 is ringing (active=60, fired=[60])
        2. 5's fire time is already past (due=now+2min → 5 fires at now-3min)
        3. Snooze → just clear active (ladder walks; no nudge because 5 is unfired)
        4. Next tick → 5 is now collected and fires immediately
        """
        # Due in 2 min; 60 fires at NOW-58 (past), 5 fires at NOW-3 (past)
        due = NOW + timedelta(minutes=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=None,
        )
        # Snooze (just clears active, ladder walks; 5 is armed-unfired but past)
        acknowledge_snooze(todo, NOW)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None  # No nudge; 5 is lower rung
        assert todo.reminder_fired == [60]  # 60 still fired, 5 unfired

        # Next tick fires 5 immediately (escalation intended)
        fire = tick(todo, NOW)
        assert fire == Fire(todo_id="t1", offset=5, is_nudge=False)
        assert todo.reminder_active == 5
        assert 5 in todo.reminder_fired


class TestAcknowledgeDismiss:
    """acknowledge_dismiss(todo) marks all offsets fired and clears active/nudge."""

    def test_dismiss_marks_all_offsets_fired(self):
        """Dismiss marks every offset as fired."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=60,
            reminder_nudge_at=None,
        )
        acknowledge_dismiss(todo)
        assert set(todo.reminder_fired) == {60, 30, 5}

    def test_dismiss_clears_active_and_nudge(self):
        """Dismiss clears active and nudge_at."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=nudge_at,
        )
        acknowledge_dismiss(todo)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_dismiss_no_op_on_future_tick(self):
        """After dismiss, a later tick with unfired rungs past returns None."""
        due = NOW + timedelta(minutes=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Dismiss (all offsets now fired)
        acknowledge_dismiss(todo)
        assert set(todo.reminder_fired) == {60, 30, 5}

        # Later tick: no armed-unfired offsets (all already fired)
        fire = tick(todo, NOW)
        assert fire is None
        assert todo.reminder_active is None


class TestArm:
    """arm(todo, offsets, now) sets reminder_offsets with delta semantics on reminder_fired."""

    def test_arm_preserves_future_unfired_rung(self):
        """arm preserves fired status: unfired unfired-future rung stays unfired."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Re-arm same offsets; 30 should stay unfired
        arm(todo, [60, 30], NOW)
        assert todo.reminder_offsets == [60, 30]
        assert todo.reminder_fired == []

    def test_arm_delta_drops_rung_removes_from_fired(self):
        """Dropping a rung from offsets removes it from fired too."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[60],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Drop 60
        arm(todo, [30, 5], NOW)
        assert todo.reminder_offsets == [30, 5]
        assert 60 not in todo.reminder_fired  # dropped from fired too
        assert todo.reminder_fired == []

    def test_arm_delta_adds_rung_pre_marks_if_past(self):
        """Adding a rung that's already past → pre-marked fired."""
        due = NOW + timedelta(minutes=10)  # 60 min rung fires at NOW - 50 (past)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Add 60 (past)
        arm(todo, [60, 30, 5], NOW)
        assert todo.reminder_offsets == [60, 30, 5]
        assert 60 in todo.reminder_fired  # pre-marked because past

    def test_arm_delta_adds_rung_unfired_if_future(self):
        """Adding a rung whose fire time is future → stays unfired."""
        due = NOW + timedelta(hours=2)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Add 60 (future)
        arm(todo, [60, 30, 5], NOW)
        assert todo.reminder_offsets == [60, 30, 5]
        assert 60 not in todo.reminder_fired  # not pre-marked because future

    def test_arm_delta_preserves_dismissed_rung_stays_fired(self):
        """[R-3] Arm with same offsets keeps fired status: dismissed rung stays dismissed.

        This is the KEY requirement: if a user dismissed a rung (mark all fired),
        then later re-arms the same offsets, that rung should NOT re-fire.
        """
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Dismiss (all offsets marked fired)
        acknowledge_dismiss(todo)
        assert set(todo.reminder_fired) == {60, 30, 5}

        # Later: re-arm same offsets
        arm(todo, [60, 30, 5], NOW)

        # All offsets should still be marked fired (no re-ring)
        assert set(todo.reminder_fired) == {60, 30, 5}

        # Later tick with all offsets in past: nothing fires (all already fired)
        due_very_soon = NOW + timedelta(minutes=2)
        todo.due = due_very_soon
        fire = tick(todo, NOW)
        assert fire is None  # Nothing fires; all dismissed offsets stay dismissed

    def test_arm_empty_offsets_clears_all(self):
        """arm([]) clears reminder_offsets, reminder_fired, reminder_active, reminder_nudge_at."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=nudge_at,
        )
        # Clear reminders
        arm(todo, [], NOW)
        assert todo.reminder_offsets == []
        assert todo.reminder_fired == []
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_due_none_no_crash(self):
        """Guard: due is None → set offsets, fired=[], no fire-time math, no crash."""
        todo = mk_todo(
            id="t1",
            due=None,
            reminder_offsets=[],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Should not crash even though due is None
        arm(todo, [60, 30, 5], NOW)
        assert todo.reminder_offsets == [60, 30, 5]
        assert todo.reminder_fired == []  # No fire-time math
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_sanitizes_unknown_offsets(self):
        """Unknown offsets (not in RUNG_MINUTES) are dropped from the input."""
        due = NOW + timedelta(hours=2)  # Far future so offsets aren't pre-marked
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Try to arm with unknown offsets (999) mixed with known ones
        arm(todo, [60, 999, 30, 888, 5], NOW)
        # Only [60, 30, 5] should be stored (in descending order)
        assert todo.reminder_offsets == [60, 30, 5]
        assert todo.reminder_fired == []
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_deduplicates_offsets(self):
        """Duplicate offsets in input are deduplicated."""
        due = NOW + timedelta(hours=2)  # Far future so offsets aren't pre-marked
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Arm with duplicates
        arm(todo, [60, 60, 30, 30, 5], NOW)
        assert todo.reminder_offsets == [60, 30, 5]
        assert todo.reminder_fired == []
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_stores_descending_order(self):
        """Offsets stored in descending order (file convention)."""
        due = NOW + timedelta(hours=2)  # Far future so offsets aren't pre-marked
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[],
            reminder_fired=[],
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Arm with unsorted offsets
        arm(todo, [5, 60, 30], NOW)
        assert todo.reminder_offsets == [60, 30, 5]
        assert todo.reminder_fired == []
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_clears_active_if_dropped_rung(self):
        """If active rung is dropped, clear reminder_active."""
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30, 5],
            reminder_fired=[60],
            reminder_active=60,
            reminder_nudge_at=None,
        )
        # Drop 60 (which is active)
        arm(todo, [30, 5], NOW)
        assert todo.reminder_active is None  # Cleared because 60 dropped

    def test_arm_clears_nudge_if_dropped_rung_active(self):
        """If active rung is dropped and nudge_at set, clear nudge_at too."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60, 5],
            reminder_active=5,
            reminder_nudge_at=nudge_at,
        )
        # Drop 5 (which is active with a pending nudge)
        arm(todo, [60], NOW)
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_keeps_nudge_if_rung_kept_pending(self):
        """Nudge pending (active=None, nudge_at set) survives if ≥1 rung kept, even when offset is dropped.

        Reproducer: offsets [60, 5] with pending nudge (active=None, nudge_at set) →
        arm with [60] (drops 5) → nudge_at SURVIVES, active stays None, 5 gone from offsets/fired.
        """
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60, 5],
            reminder_active=None,
            reminder_nudge_at=nudge_at,  # Pending nudge
        )
        # Re-arm dropping 5, keeping 60; nudge should survive
        arm(todo, [60], NOW)
        assert todo.reminder_offsets == [60]
        assert 5 not in todo.reminder_fired
        assert 60 in todo.reminder_fired  # unchanged rung: fired status preserved by the delta
        assert todo.reminder_active is None  # Still None
        assert todo.reminder_nudge_at == nudge_at  # SURVIVES

    def test_arm_keeps_nudge_if_rung_kept_ringing(self):
        """Nudge ringing (active=NUDGE_SENTINEL) survives if ≥1 rung kept, even when offset is dropped."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60, 5, 0],
            reminder_active=NUDGE_SENTINEL,  # Nudge is ringing
            reminder_nudge_at=nudge_at,
        )
        # Re-arm dropping 5, keeping 60; ringing nudge should survive
        arm(todo, [60], NOW)
        assert todo.reminder_offsets == [60]
        assert 5 not in todo.reminder_fired
        assert todo.reminder_active == NUDGE_SENTINEL  # Still ringing
        assert todo.reminder_nudge_at == nudge_at  # SURVIVES

    def test_arm_clears_nudge_if_all_rungs_dropped(self):
        """If all rungs dropped, clear nudge too (no remaining rung to fire on)."""
        due = NOW + timedelta(hours=1)
        nudge_at = NOW + timedelta(minutes=5)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 5],
            reminder_fired=[60, 5, 0],
            reminder_active=NUDGE_SENTINEL,
            reminder_nudge_at=nudge_at,
        )
        # Drop all rungs
        arm(todo, [], NOW)
        assert todo.reminder_offsets == []
        assert todo.reminder_fired == []
        assert todo.reminder_active is None
        assert todo.reminder_nudge_at is None

    def test_arm_invariant_fired_subset_of_offsets(self):
        """Invariant: after arm, reminder_fired ⊆ reminder_offsets (except sentinel 0).

        Sentinel 0 is only dropped when all offsets are empty, not when some rungs remain.
        """
        due = NOW + timedelta(hours=1)
        todo = mk_todo(
            id="t1",
            due=due,
            reminder_offsets=[60, 30],
            reminder_fired=[60, 30, 0],  # 0 is allowed even if not in offsets
            reminder_active=None,
            reminder_nudge_at=None,
        )
        # Re-arm without 60; fired should drop 60 too, but keep 0 (rung still exists)
        arm(todo, [30], NOW)
        # 60 is dropped, 30 stays, 0 stays (only drop 0 when offsets empty)
        assert set(todo.reminder_fired) == {30, 0}
        assert all(o in todo.reminder_offsets or o == 0 for o in todo.reminder_fired)
