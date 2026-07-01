# Phase A — State/Context Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, chosen) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three hand-synced hardcoded activity sources with one registry in `core/states.py`, promote the full styled pose library, and rewire the selector/chip/pose-map as projections — settings-persisted with backward-compat.

**Architecture:** `core/states.py` is a pure, Qt-free leaf module (an `ActivityState` frozen dataclass + `DEFAULT_STATES` seed + helpers). `core/poses.py` and `core/settings.py` derive their maps from it; `ui/mascot_stage.py` + `ui/activity_chip.py` read it as projections. Persistence rides on the existing `Settings` JSON dataclass via a new untrusted-input `states()` deserializer.

**Tech Stack:** Python 3.12, dataclasses, PySide6 (UI only), pytest (headless: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`).

## Global Constraints

- Header comment block on every new/edited Python script (Author: Berk, Created: 2026-07-01, Purpose, Role, Models/Functions).
- No new dependencies. `core/states.py` is **Qt-free** (no PySide6 import).
- Every task ends with the **full headless suite green** (was 1001 passed / 5 skipped at branch start).
- Atomic conventional commits, scoped to the task. Branch: `wf/phase-a-states`.
- Import direction (no cycle): `states` (leaf) ← `poses` ← `settings`; UI (`mascot_stage`, `activity_chip`) → `core`.
- The activity **log is unchanged** — `ActivityEntry.category` keeps storing the display label. No migration.

## Impact gate (already run — grep-verified blast radius)

- `current_state` has **zero readers** (written only at `mascot_stage.py:137,267`) → Focus's `set_state("focus")` change is safe.
- `set_state(` sites: `mascot_stage:165` (`"idle"`), `:258` (`_on_pick`), `shell:447` (`"success"`), `:452` (`"working"`), `:481` (`"coding"`→**`"focus"`**, Task 4), `:615` (`"thinking"`) — all keys valid post-registry.
- `state_map()` consumers: `mascot_stage:132,264`, `settings_window:123` — all handle the richer registry-derived map.
- `DEFAULT_STATE_MAP`/`default_state_map()` kept (used by `settings_window:123` + `PoseSelector` default) — become registry-derived.

---

### Task 1: `core/states.py` — the registry module

**Files:**
- Create: `serenity/core/states.py`
- Test: `tests/test_states.py`

**Interfaces:**
- Produces: `ActivityState(key, label, color=ACCENT, poses=IDLE_POSES, category="activity", context="any")` (frozen); `ACCENT="#a78bfa"`; `IDLE_POSES` (tuple); `DEFAULT_STATES: list[ActivityState]`; `default_states() -> list[ActivityState]`; `activities(states) -> list[ActivityState]`; `is_protected(s) -> bool`; `color_for_label(label, states=None, default=ACCENT) -> str`; `selector_rows(states) -> list[tuple[str,str,str]]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_states.py`

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_states.py -q`
Expected: FAIL (`ModuleNotFoundError: serenity.core.states`).

- [ ] **Step 3: Create `serenity/core/states.py`**

```python
"""
============================================================
Author:  Berk
Created: 2026-07-01
Purpose: Single editable registry of Serenity's activity + reaction states.
Role:    The one source of truth for the activity selector, the running-activity
         chip color and the state->pose map. Pure logic - no Qt - so the seed,
         projections and consumers are unit-tested headless. Foundation of the
         States & Contexts milestone (Phase A).

Models:
- ActivityState{key,label,color,poses,category,context} - one activity or reaction.

Functions:
- default_states() -> list[ActivityState] - a fresh copy of the seed.
- activities(states) -> list[ActivityState] - the trackable (category=="activity") rows.
- is_protected(s) -> bool - reaction rows + Idle (undeletable; data marker for Phase E).
- color_for_label(label, states=None, default=ACCENT) -> str - registry color, else default.
- selector_rows(states) -> list[(label,key,color)] - the activity-selector projection.
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ACCENT = "#a78bfa"
IDLE_POSES = ("idle_1", "idle_2", "chilling", "idle_3", "silent")


@dataclass(frozen=True)
class ActivityState:
    key: str
    label: str
    color: str = ACCENT
    poses: tuple[str, ...] = IDLE_POSES
    category: str = "activity"   # "activity" (trackable) | "reaction" (pose-only)
    context: str = "any"         # "business" | "private" | "any"


DEFAULT_STATES: list[ActivityState] = [
    ActivityState("working", "Working", "#a78bfa", ("work_1", "work_2", "concentrating"), "activity", "business"),
    ActivityState("coding", "Coding", "#ff8ad0", ("mission", "work_2", "concentrating"), "activity", "business"),
    ActivityState("meeting", "Meeting", "#5cc8ff", ("time", "aufmerksam", "come"), "activity", "business"),
    ActivityState("planning", "Planning", "#8fd36a", ("nachdenklich", "examining", "detektive", "searching"), "activity", "business"),
    ActivityState("focus", "Focus", "#19e3ff", ("mission", "work_2", "glasses_off"), "activity", "business"),
    ActivityState("entertainment", "Entertainment", "#e3b341", ("chilling", "fun", "dj", "cheering", "giggeling", "amused"), "activity", "business"),
    ActivityState("idle", "Idle", "#19e3ff", ("idle_1", "idle_2", "chilling", "idle_3", "silent"), "activity", "any"),
    ActivityState("alert", "Alert", ACCENT, ("hinweis", "aufmerksam"), "reaction", "any"),
    ActivityState("thinking", "Thinking", ACCENT, ("nachdenklich", "examining", "concentrating"), "reaction", "any"),
    ActivityState("success", "Success", ACCENT, ("happy", "fun", "happy_2", "relieved", "cheering"), "reaction", "any"),
    ActivityState("error", "Error", ACCENT, ("mad", "mad_2", "ups", "ups_2", "annoyed", "überhitzt", "frozen", "spilled_coffee"), "reaction", "any"),
]


def default_states() -> list[ActivityState]:
    return list(DEFAULT_STATES)


def activities(states: list[ActivityState]) -> list[ActivityState]:
    return [s for s in states if s.category == "activity"]


def is_protected(s: ActivityState) -> bool:
    return s.category == "reaction" or s.key == "idle"


def color_for_label(label: str, states: Optional[list[ActivityState]] = None,
                    default: str = ACCENT) -> str:
    for s in (states if states is not None else default_states()):
        if s.label == label:
            return s.color
    return default


def selector_rows(states: list[ActivityState]) -> list[tuple[str, str, str]]:
    return [(s.label, s.key, s.color) for s in activities(states)]
```

- [ ] **Step 4: Run to verify pass** — `...pytest tests/test_states.py -q` → PASS.
- [ ] **Step 5: Full suite** — `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → 1001+ passed (new file adds tests; nothing else changed).
- [ ] **Step 6: Commit**

```bash
git add serenity/core/states.py tests/test_states.py
git commit -m "feat(states): ActivityState registry + seed + projections (Phase A)"
```

---

### Task 2: Promote the styled pose library + derive `DEFAULT_STATE_MAP` (atomic with the test rewrite)

**Files:**
- Copy: `current_Imgs/*.webp` → `serenity/assets/poses/`
- Modify: `serenity/core/poses.py` (extend `POSE_FILES`; derive `DEFAULT_STATE_MAP` from the registry; import `states`)
- Modify: `tests/test_poses.py:32-35` (rewrite the count/equality invariant)
- Test: `tests/test_states.py` (add the seeded-pose ⊆ POSE_FILES cross-check)

**Interfaces:**
- Consumes: `serenity.core.states.default_states` (Task 1).
- Produces: `POSE_FILES` (41 entries); `DEFAULT_STATE_MAP = {s.key: list(s.poses) for s in default_states()}`.

> **Why atomic:** `tests/test_poses.py:32-35` hard-asserts `len(POSE_FILES)==14` and `used==set(keys)`; both break the instant `POSE_FILES` grows and reserved poses exist. The test rewrite MUST land in this same commit (flow-harden P2.1/2.7/2.8).

- [ ] **Step 1: Promote the assets (webp only — exclude the 14 .gif twins)**

Run:
```bash
cp /home/berk/git/ProjectSerenity/current_Imgs/*.webp /home/berk/git/ProjectSerenity/serenity/assets/poses/
ls /home/berk/git/ProjectSerenity/serenity/assets/poses/*.webp | wc -l   # expect 41
ls /home/berk/git/ProjectSerenity/serenity/assets/poses/*.gif 2>/dev/null | wc -l   # expect 0
```

- [ ] **Step 2: Write the failing cross-check test** — append to `tests/test_states.py`

```python
class TestPoseWiring:
    def test_every_seeded_pose_has_a_file(self):
        from serenity.core.poses import POSE_FILES
        for s in default_states():
            for key in s.poses:
                assert key in POSE_FILES, f"{key} (state {s.key}) has no file"
```

Run: `...pytest tests/test_states.py::TestPoseWiring -q`
Expected: FAIL (new pose keys like `concentrating`/`dj`/`überhitzt` not yet in `POSE_FILES`).

- [ ] **Step 3: Extend `POSE_FILES` and derive `DEFAULT_STATE_MAP`** in `serenity/core/poses.py`

Add the import after the stdlib imports (below `import random`):
```python
from .states import default_states
```

Add these 27 entries to the `POSE_FILES` dict (after the existing 14):
```python
    "amused": "serenity_amused.webp",
    "annoyed": "serenity_annoyed.webp",
    "cheering": "serenity_cheering.webp",
    "come": "serenity_come.webp",
    "concentrating": "serenity_concentrating.webp",
    "detektive": "serenity_detektive.webp",
    "dj": "serenity_dj.webp",
    "frozen": "serenity_frozen.webp",
    "giggeling": "serenity_giggeling.webp",
    "glasses_off": "serenity_glasses_off.webp",
    "hand_disappearing": "serenity_hand_disappearing.webp",
    "happy_2": "serenity_happy_2.webp",
    "hi": "serenity_hi.webp",
    "idle_3": "serenity_idle_3.webp",
    "leaving": "serenity_leaving.webp",
    "mad_2": "serenity_mad_2.webp",
    "next_task": "serenity_next_task.webp",
    "relieved": "serenity_relieved.webp",
    "ripped_note": "serenity_ripped_note.webp",
    "searching": "serenity_searching.webp",
    "silent": "serenity_silent.webp",
    "spilled_coffee": "serenity_spilled_coffee.webp",
    "trash": "serenity_trash.webp",
    "ups": "serenity_ups.webp",
    "ups_2": "serenity_ups_2.webp",
    "verlegen": "serenity_verlegen.webp",
    "überhitzt": "serenity_überhitzt.webp",
```

Replace the `DEFAULT_STATE_MAP` literal (lines 40-52) with the registry-derived form (keep a one-line comment):
```python
# State -> candidate pose keys, DERIVED from the core.states registry (single source of truth).
DEFAULT_STATE_MAP: dict[str, list[str]] = {s.key: list(s.poses) for s in default_states()}
```

- [ ] **Step 4: Rewrite the brittle invariant** — `tests/test_poses.py:32-35`

Replace `test_all_14_poses_referenced` with:
```python
    def test_seeded_poses_are_a_subset_of_pose_files(self):
        # Every pose a state references must have a file; POSE_FILES MAY hold more
        # (reserved greeting/event poses that no state maps to yet).
        used = {k for keys in poses.DEFAULT_STATE_MAP.values() for k in keys}
        assert used <= set(poses.POSE_FILES.keys())
        assert len(poses.POSE_FILES) >= len(used)
```

- [ ] **Step 5: Run the affected tests**

Run: `...pytest tests/test_states.py tests/test_poses.py -q`
Expected: PASS (incl. existing `test_shipped_files_exist_on_disk` now confirming all 41 webps landed on disk, and `test_every_pose_key_has_a_file` confirming all are `.webp`).

- [ ] **Step 6: Full suite** — `...pytest -q` → green.
- [ ] **Step 7: Commit**

```bash
git add serenity/assets/poses/ serenity/core/poses.py tests/test_poses.py tests/test_states.py
git commit -m "feat(poses): promote 41 styled poses + registry-derived DEFAULT_STATE_MAP (Phase A)"
```

---

### Task 3: `Settings` persistence — `activity_states` + hardened `states()` + `state_map()` overlay

**Files:**
- Modify: `serenity/core/settings.py` (imports; new field; `states()`; rewrite `state_map()`)
- Test: `tests/test_states.py` (add `TestSettingsRegistry`)

**Interfaces:**
- Consumes: `serenity.core.states.{ActivityState, default_states}`.
- Produces: `Settings.activity_states: list`; `Settings.states() -> list[ActivityState]`; `Settings.state_map() -> dict` (registry-derived base + legacy `state_pose_map` overlay).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_states.py`

```python
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

    def test_malformed_row_falls_back_to_default(self, tmp_path):
        for bad in ([{"label": "X", "color": "#fff"}],      # missing key
                    [{"key": "k", "label": "L", "bogus": 1}],  # extra key
                    ["not-a-dict"],                            # non-dict row
                    "not-a-list",                              # non-list container
                    [{"key": "k", "label": "L", "poses": "mission"}]):  # poses not a seq
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
        assert "focus" in m and m["focus"]        # registry base survives
        assert m["coding"] == ["work_1"]           # legacy per-key override applied
```

- [ ] **Step 2: Run to verify it fails**

Run: `...pytest tests/test_states.py::TestSettingsRegistry -q`
Expected: FAIL (`Settings` has no `activity_states` / `states()`; `state_map()` uses REPLACE semantics so `focus` missing when a legacy map is set).

- [ ] **Step 3: Edit `serenity/core/settings.py`**

Imports — change line 23 and line 29:
```python
from dataclasses import asdict, dataclass, field, fields
```
Remove `from .poses import default_state_map` (line 29 — `state_map()` no longer uses it) and add:
```python
from .states import ActivityState, default_states
```

Add the field right after `state_pose_map` (line 77):
```python
    # editable activity/reaction registry (serialized ActivityState rows); [] => code default
    activity_states: list = field(default_factory=list)
```

Replace `state_map()` (lines 135-136) and add `states()`:
```python
    def states(self) -> list["ActivityState"]:
        """Effective registry: the persisted override if fully valid, else the code default.
        activity_states is untrusted (hand-edit / partial write / schema drift): ANY malformed
        row discards the WHOLE override -> default (never a partial registry)."""
        raw = self.activity_states
        if not isinstance(raw, list) or not raw:
            return default_states()
        allowed = {f.name for f in fields(ActivityState)}
        seen: set = set()
        out: list[ActivityState] = []
        try:
            for row in raw:
                if not isinstance(row, dict):
                    raise TypeError("row is not a mapping")
                if set(row) - allowed or "key" not in row or "label" not in row:
                    raise KeyError("bad row keys")
                row = dict(row)
                if "poses" in row:
                    p = row["poses"]
                    if not isinstance(p, (list, tuple)) or not all(isinstance(x, str) for x in p):
                        raise TypeError("poses not a sequence of str")
                    row["poses"] = tuple(p)
                s = ActivityState(**row)
                if s.key in seen:
                    raise ValueError(f"duplicate key {s.key}")
                seen.add(s.key)
                out.append(s)
        except (TypeError, KeyError, ValueError):
            return default_states()
        return out

    def state_map(self) -> dict:
        """State-key -> pose keys, DERIVED from the registry, with any legacy
        state_pose_map applied as a per-key overlay (never a whole-dict replace)."""
        base = {s.key: list(s.poses) for s in self.states()}
        for k, v in (self.state_pose_map or {}).items():
            if v:
                base[k] = list(v)
        return base
```

- [ ] **Step 4: Run to verify pass** — `...pytest tests/test_states.py::TestSettingsRegistry -q` → PASS.
- [ ] **Step 5: Full suite** — `...pytest -q` → green (existing settings/poses/UI tests unaffected).
- [ ] **Step 6: Commit**

```bash
git add serenity/core/settings.py tests/test_states.py
git commit -m "feat(settings): untrusted activity_states registry + state_map overlay (Phase A)"
```

---

### Task 4: Rewire the consumers (selector, chip, focus reaction)

**Files:**
- Modify: `serenity/ui/mascot_stage.py` (drop `ACTIVITIES`; projection in `open_selector`/`_on_pick`; import `states`)
- Modify: `serenity/ui/activity_chip.py` (drop `_ACTIVITY_COLORS`; `_color_for` via registry; import `states`)
- Modify: `serenity/ui/shell.py:481` (`"coding"` → `"focus"`)
- Test: `tests/test_states.py` (add `TestConsumers`)

**Interfaces:**
- Consumes: `states.selector_rows`, `states.color_for_label`, `Settings.states()`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_states.py`

```python
class TestConsumers:
    def test_chip_color_uses_registry_with_accent_miss_default(self):
        from serenity.ui import activity_chip
        # a registered label resolves to its registry color; an unknown one -> accent default
        chip = activity_chip.ActivityChip.__new__(activity_chip.ActivityChip)
        assert chip._color_for("Coding") == "#ff8ad0"
        from serenity.ui.theme import COLORS
        assert chip._color_for("Ghost") == COLORS["accent"]

    def test_selector_rows_drive_the_menu_and_focus_is_own_key(self):
        # picking "Focus" must resolve to key "focus" (not "coding")
        rows = states.selector_rows(default_states())
        key = next((k for (l, k, _c) in rows if l == "Focus"), "idle")
        assert key == "focus"
```

Run: `...pytest tests/test_states.py::TestConsumers -q` → expect FAIL on the chip test (`_color_for` still reads `_ACTIVITY_COLORS`; passes coincidentally, so assert also that `_ACTIVITY_COLORS` is gone) — see Step 2 note.

> Note: the chip test passes even pre-change (colors match), so it is a *regression guard*, not a red→green driver. The real driver is Step 2's deletion; run the full suite after to confirm no consumer broke.

- [ ] **Step 2: Edit `serenity/ui/mascot_stage.py`**

Add import (with the other `..core` imports near the top):
```python
from ..core import states
```
Delete the `ACTIVITIES` constant and its 2-line comment (lines 41-51).
`open_selector` — change line 241:
```python
        for label, _key, color in states.selector_rows(self.settings.states()):
```
`_on_pick` — change lines 255 & 258:
```python
    def _on_pick(self, label: str):
        rows = states.selector_rows(self.settings.states())
        key = next((k for (l, k, _c) in rows if l == label), "idle")
        self.current_activity = label
        self.close_selector()
        self.set_state(key)
        self.activity_changed.emit(label)
```

- [ ] **Step 3: Edit `serenity/ui/activity_chip.py`**

Add import (with the other `..core` imports):
```python
from ..core import states
```
Delete the `_ACTIVITY_COLORS` dict and its comment (lines 27-36). Change `_color_for` (lines 79-80):
```python
    def _color_for(self, label: str) -> str:
        return states.color_for_label(label, default=COLORS["accent"])
```

- [ ] **Step 4: Edit `serenity/ui/shell.py:481`** (flow-harden P3.1)

```python
        self.mascot.set_state("success" if phase != "focus" else "focus")
```

- [ ] **Step 5: Run tests** — `...pytest tests/test_states.py::TestConsumers tests/test_ui_stage1.py -q` → PASS.
- [ ] **Step 6: Full suite** — `...pytest -q` → green (mascot/chip/settings-window UI tests confirm the projections are behavior-preserving; widen any test asserting a specific pre-enrichment pose set).
- [ ] **Step 7: Commit**

```bash
git add serenity/ui/mascot_stage.py serenity/ui/activity_chip.py serenity/ui/shell.py tests/test_states.py
git commit -m "refactor(ui): read the states registry (selector/chip projections + focus key) (Phase A)"
```

---

### Task 5: Notes wrap + final verification

**Files:** Modify `notes/1_Planning.md` (Phase A session wrap; next = Phase B).

- [ ] **Step 1: Full suite** — `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → all green; record the new count.
- [ ] **Step 2: Update `notes/1_Planning.md`** — add a 2026-07-01 Phase A wrap (registry shipped, 41 poses promoted, 12 flow-harden gaps folded, next = Phase B global context toggle).
- [ ] **Step 3: Commit**

```bash
git add notes/1_Planning.md
git commit -m "docs(notes): Phase A state registry shipped; next = Phase B"
```

---

## Self-review

- **Spec coverage:** registry module (T1), enriched seed (T1), asset promotion webp-only (T2), projections/rewiring (T2 pose-map, T4 selector/chip/shell), persistence + hardened `states()` + overlay (T3), all 12 flow-harden gaps: P1.1+P2.4+P3.2 (T3 `states()`), P2.1/2.7/2.8 (T2 test rewrite), P2.2 (T2 cross-check), P2.3 (T4 chip default), P2.5/2.6 (T3 overlay), P3.1 (T4 shell), P3.3 (T2 webp-only glob). Testing plan → T1–T4 tests. Impact gate → done above. ✅ No gaps.
- **Placeholders:** none — full code in every code step.
- **Type consistency:** `states()`/`selector_rows`/`color_for_label`/`default_states` names match across T1→T4; `state_map()` returns `dict[str, list[str]]` consumed unchanged by `PoseSelector`.
