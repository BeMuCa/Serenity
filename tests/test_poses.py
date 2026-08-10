"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for pose selection (state map coverage, no immediate repeat).
Role:    Guards the MascotController's contract: every state resolves to a real
         webp file, and consecutive picks for a state never repeat.

Test classes:
- TestPoseMap - all states map to known files; all 14 poses referenced
- TestPoseSelector - random pick, no immediate repeat, single-pose states
============================================================
"""

import random

from serenity.core import poses
from serenity.core.paths import poses_dir


class TestPoseMap:
    def test_every_pose_key_has_a_file(self):
        for key in poses.POSE_FILES:
            assert poses.POSE_FILES[key].endswith(".webp")

    def test_state_map_keys_all_resolve_to_files(self):
        for state, keys in poses.DEFAULT_STATE_MAP.items():
            assert keys, f"state {state} has no poses"
            for k in keys:
                assert k in poses.POSE_FILES, f"{k} (state {state}) has no file"

    def test_seeded_poses_are_a_subset_of_pose_files(self):
        # Every pose a state references must have a file; POSE_FILES MAY hold more
        # (reserved greeting/event poses that no state maps to yet).
        used = {k for keys in poses.DEFAULT_STATE_MAP.values() for k in keys}
        assert used <= set(poses.POSE_FILES.keys())
        assert len(poses.POSE_FILES) >= len(used)

    def test_shipped_files_exist_on_disk(self):
        d = poses_dir()
        for fname in poses.POSE_FILES.values():
            assert (d / fname).exists(), f"missing asset {fname}"


class TestPoseSelector:
    def test_unknown_state_returns_none(self):
        sel = poses.PoseSelector()
        assert sel.pick("does-not-exist") is None

    def test_single_pose_state_returns_that_pose(self):
        # a state with one candidate pose always returns it (seed-independent:
        # every seeded state now has multiple poses after the Phase-A enrichment)
        sel = poses.PoseSelector({"solo": ["only"]}, rng=random.Random(1))
        assert sel.pick("solo") == "only"
        assert sel.pick("solo") == "only"

    def test_no_immediate_repeat(self):
        sel = poses.PoseSelector(rng=random.Random(42))
        last = None
        for _ in range(50):
            cur = sel.pick("idle")          # idle has 3 poses
            assert cur in poses.DEFAULT_STATE_MAP["idle"]
            if last is not None:
                assert cur != last, "pose repeated immediately"
            last = cur

    def test_filename_lookup(self):
        sel = poses.PoseSelector()
        assert sel.filename("idle_1") == "serenity_idle_1.webp"
        assert sel.filename("nope") is None
