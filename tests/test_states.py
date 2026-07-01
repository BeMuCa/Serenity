"""
============================================================
Author:  Berk
Created: 2026-07-01
Purpose: Unit tests for the pure activity/state registry (core/states.py).
Role:    Guards the seed integrity, the projections and the untrusted-input
         deserializer that the selector, chip and pose map depend on.

Test classes:
- TestSeed - seed integrity (unique keys, categories, protection, context)
- TestProjections - color_for_label + selector_rows
============================================================
"""
from serenity.core import states
from serenity.core.states import ACCENT, ActivityState, default_states


class TestSeed:
    def test_keys_are_unique(self):
        keys = [s.key for s in default_states()]
        assert len(keys) == len(set(keys))

    def test_seven_activities_four_reactions(self):
        acts = [s for s in default_states() if s.category == "activity"]
        reacts = [s for s in default_states() if s.category == "reaction"]
        assert len(acts) == 7 and len(reacts) == 4

    def test_every_state_has_nonempty_pose_tuple(self):
        for s in default_states():
            assert isinstance(s.poses, tuple) and s.poses

    def test_protected_is_reactions_plus_idle(self):
        protected = {s.key for s in default_states() if states.is_protected(s)}
        assert protected == {"idle", "alert", "thinking", "success", "error"}

    def test_focus_has_own_key_and_work_family_poses(self):
        focus = next(s for s in default_states() if s.key == "focus")
        assert focus.label == "Focus"
        assert "mission" in focus.poses and "work_2" in focus.poses

    def test_current_activities_are_seeded_business(self):
        biz = {s.key for s in default_states() if s.context == "business"}
        assert biz == {"working", "coding", "meeting", "planning", "focus", "entertainment"}


class TestProjections:
    def test_color_for_label_hit(self):
        assert states.color_for_label("Coding") == "#ff8ad0"

    def test_color_for_label_miss_returns_default(self):
        assert states.color_for_label("Nonexistent") == ACCENT
        assert states.color_for_label("Nonexistent", default="#123456") == "#123456"

    def test_selector_rows_are_activity_only_triples(self):
        rows = states.selector_rows(default_states())
        assert all(len(r) == 3 for r in rows)
        labels = [label for (label, _k, _c) in rows]
        assert "Idle" in labels and "Alert" not in labels  # reactions excluded
        # middle element is the row's own key (Focus is its own key, not "coding")
        focus_row = next(r for r in rows if r[0] == "Focus")
        assert focus_row[1] == "focus"
