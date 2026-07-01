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
- TestPoseWiring - every seeded pose has a file; reserved poses present but unseeded
- TestSettingsRegistry - untrusted activity_states deserializer + state_map overlay
- TestConsumers - chip color miss-default + selector focus-key projection
============================================================
"""
from serenity.core import states
from serenity.core.states import ACCENT, ActivityState, default_states


class TestSeed:
    def test_keys_are_unique(self):
        keys = [s.key for s in default_states()]
        assert len(keys) == len(set(keys))

    def test_activity_and_reaction_counts(self):
        acts = [s for s in default_states() if s.category == "activity"]
        reacts = [s for s in default_states() if s.category == "reaction"]
        assert len(acts) == 15 and len(reacts) == 4   # 6 business + 8 private + Idle; 4 reactions

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


class TestContext:
    def test_eight_private_activities_seeded(self):
        priv = [s for s in default_states() if s.context == "private"]
        assert {s.key for s in priv} == {"chilling", "friends", "girlfriend", "music",
                                         "learning", "code", "eat", "gaming"}

    def test_selector_rows_business_excludes_private_includes_idle(self):
        labels = {l for (l, _k, _c) in states.selector_rows(default_states(), "business")}
        assert "Coding" in labels and "Idle" in labels
        assert "Chilling" not in labels and "Friends" not in labels

    def test_selector_rows_private_excludes_business_includes_idle(self):
        labels = {l for (l, _k, _c) in states.selector_rows(default_states(), "private")}
        assert "Chilling" in labels and "Idle" in labels
        assert "Coding" not in labels and "Meeting" not in labels

    def test_selector_rows_no_context_returns_all(self):
        assert len(states.selector_rows(default_states())) == 15   # Phase-A behaviour preserved

    def test_context_default_pose_keys_resolve(self):
        keys = {s.key for s in default_states()}
        for pose_state in states.CONTEXT_DEFAULT_POSE.values():
            assert pose_state in keys   # "idle","chilling" are real state keys


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


class TestPoseWiring:
    def test_every_seeded_pose_has_a_file(self):
        from serenity.core.poses import POSE_FILES
        for s in default_states():
            for key in s.poses:
                assert key in POSE_FILES, f"{key} (state {s.key}) has no file"

    def test_reserved_poses_present_but_not_seeded(self):
        # promoted greeting/event poses are available in POSE_FILES but wired to NO
        # state yet (their triggers are Phase F / event wiring, per the spec).
        # (Phase B claimed "verlegen" for the Girlfriend activity, so it left the reserved set.)
        from serenity.core.poses import POSE_FILES
        reserved = {"hi", "leaving", "next_task", "ripped_note", "trash", "hand_disappearing"}
        seeded = {k for s in default_states() for k in s.poses}
        assert reserved <= set(POSE_FILES)   # promoted + available
        assert reserved.isdisjoint(seeded)   # but seeded into no state


class TestSettingsRegistry:
    def _mk(self, tmp_path, **kw):
        from serenity.core.settings import Settings
        s = Settings(**kw)
        s._path = tmp_path / "settings.json"
        return s

    def test_empty_override_uses_default(self, tmp_path):
        s = self._mk(tmp_path)
        assert [x.key for x in s.states()] == [x.key for x in default_states()]

    def test_roundtrip_preserves_registry(self, tmp_path):
        from dataclasses import asdict
        from serenity.core.settings import Settings
        rows = [asdict(x) for x in default_states()]
        s = self._mk(tmp_path, activity_states=rows)
        s.save()
        back = Settings.load(s._path)
        assert [x.key for x in back.states()] == [x.key for x in default_states()]
        assert all(isinstance(x.poses, tuple) for x in back.states())  # coerced back to tuple

    def test_valid_custom_override_is_honored(self, tmp_path):
        # a DISTINCT (non-default) override must be read back verbatim - guards against
        # states() vacuously ignoring activity_states and always returning the default.
        from dataclasses import asdict
        from serenity.core.settings import Settings
        custom = asdict(ActivityState("solo", "Solo", "#abcdef", ("idle_1",), "activity", "private"))
        s = self._mk(tmp_path, activity_states=[custom])
        got = s.states()
        assert [x.key for x in got] == ["solo"]              # override honored, NOT the default
        assert got[0].label == "Solo" and got[0].poses == ("idle_1",)
        s.save()
        back = Settings.load(s._path)
        assert [x.key for x in back.states()] == ["solo"]    # survives the JSON round-trip

    def test_malformed_row_falls_back_to_default(self, tmp_path):
        for bad in ([{"label": "X", "color": "#fff"}],           # missing key
                    [{"key": "k", "label": "L", "bogus": 1}],     # extra key
                    ["not-a-dict"],                               # non-dict row
                    "not-a-list",                                 # non-list container
                    [{"key": "k", "label": "L", "poses": "mission"}],   # poses not a seq
                    [{"key": "k", "label": "L", "poses": [1, 2]}],      # poses not str elems
                    [{"key": 5, "label": "L"}],                         # non-str key
                    [{"key": "k", "label": None}]):                     # non-str label
            s = self._mk(tmp_path, activity_states=bad)
            got = s.states()
            assert [x.key for x in got] == [x.key for x in default_states()]

    def test_duplicate_key_falls_back_to_default(self, tmp_path):
        row = {"key": "dup", "label": "Dup", "color": "#fff", "poses": ["idle_1"]}
        s = self._mk(tmp_path, activity_states=[row, dict(row)])
        assert [x.key for x in s.states()] == [x.key for x in default_states()]

    def test_state_map_overlay_keeps_focus_and_applies_legacy(self, tmp_path):
        # a legacy 10-state override (no "focus") must NOT hide the new focus key
        legacy = {"coding": ["work_1"]}
        s = self._mk(tmp_path, state_pose_map=legacy)
        m = s.state_map()
        assert m["focus"] == ["mission", "work_2", "glasses_off"]      # focus's seeded poses survive
        assert m["coding"] == ["work_1"]                               # legacy per-key override applied
        assert m["working"] == ["work_1", "work_2", "concentrating"]   # untouched key keeps registry poses

    def test_state_map_derives_from_effective_registry(self, tmp_path):
        # state_map()'s base is self.states() (the override), NOT default_states() -
        # kills a mutant that derives the pose map from the code default and ignores activity_states.
        from dataclasses import asdict
        custom = asdict(ActivityState("solo", "Solo", "#abcdef", ("mission",), "activity", "private"))
        s = self._mk(tmp_path, activity_states=[custom])
        assert s.state_map() == {"solo": ["mission"]}


class TestConsumers:
    def test_chip_color_uses_registry_with_accent_miss_default(self):
        from serenity.ui import activity_chip
        from serenity.ui.theme import COLORS
        # __new__ avoids Qt init; _color_for is pure registry lookup
        chip = activity_chip.ActivityChip.__new__(activity_chip.ActivityChip)
        assert chip._color_for("Coding") == "#ff8ad0"   # registered label -> registry color
        assert chip._color_for("Ghost") == COLORS["accent"]  # unknown -> accent miss-default

    def test_selector_pick_maps_focus_to_its_own_key(self):
        # the mascot selector projection: picking "Focus" resolves to key "focus" (not "coding")
        rows = states.selector_rows(default_states())
        key = next((k for (l, k, _c) in rows if l == "Focus"), "idle")
        assert key == "focus"


class TestContextPersistence:
    def _mk(self, tmp_path, **kw):
        from serenity.core.settings import Settings
        s = Settings(**kw)
        s._path = tmp_path / "settings.json"
        return s

    def test_default_is_business(self, tmp_path):
        assert self._mk(tmp_path).context() == "business"

    def test_roundtrip_private(self, tmp_path):
        from serenity.core.settings import Settings
        s = self._mk(tmp_path, current_context="private")
        s.save()
        assert Settings.load(s._path).context() == "private"

    def test_invalid_value_coerced_and_healed(self, tmp_path):
        from serenity.core.settings import Settings
        s = self._mk(tmp_path, current_context="Business")
        s.save()
        back = Settings.load(s._path)
        assert back.context() == "business"          # read guard
        assert back.current_context == "business"    # load-time heal (raw field fixed)
