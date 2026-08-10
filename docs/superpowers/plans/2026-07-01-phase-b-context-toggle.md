# Phase B — Context Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A global Private↔Business context toggle (3 entry points, kept in sync) that swaps the selector's activity set, shows a per-context mood pose, and persists — building on the Phase A registry.

**Architecture:** Registry gains 8 Private activities + `CONTEXT_DEFAULT_POSE` + a context-filtering `selector_rows`. `Settings` gains `current_context` (+ guard + load-heal). `Shell.set_context` is the single mutator; `Shell._sync_context` re-syncs all four surfaces (title-bar button, tray action, both mascots' rings, mood pose). `MascotStage` filters its ring by context, rebuilds an open ring on flip, and emits `context_toggle_requested`.

**Tech Stack:** Python 3.12, PySide6, dataclasses, pytest (headless: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`).

## Global Constraints

- Qt-free `core/`; header comment block on every edited/new script; match existing style.
- No new deps. Full headless suite green after every task (1021 passed / 5 skipped at branch start).
- Atomic conventional commits on `wf/phase-b-context`.
- **Context is a property of the activity, not the moment**: a running span is NEVER stopped by a flip; mood pose only when `activity_store.running() is None`.
- Import direction unchanged: `states` (leaf) ← `poses`/`settings`; UI → core.

## Impact gate (grep-verified)

- `selector_rows` gains an optional `context=None` param → default preserves Phase-A callers/tests.
- `set_state` call sites unchanged (Task-A verified: `current_state` has no readers).
- **Two mascots**: `Shell.mascot` (shell.py:348) + `MiniWindow.mascot` (mini_window.py:106, forwards `activity_changed` at :108) — `_sync_context` must touch both.
- Tray left-click (`_on_tray_activated`, Trigger) toggles window → context lives on the **right-click menu** action only.

---

### Task 1: Registry — Private set + `CONTEXT_DEFAULT_POSE` + context-filtered `selector_rows`

**Files:** Modify `serenity/core/states.py`; Test `tests/test_states.py`.

**Interfaces:**
- Produces: 8 new `ActivityState` rows (`context="private"`); `CONTEXT_DEFAULT_POSE: dict[str,str]`; `selector_rows(states, context=None)` (context filters to `s.context in (context,"any")`).

- [ ] **Step 1: Write/adjust failing tests** in `tests/test_states.py`

Update the Phase-A count test [gap P2.8] and add the context tests:
```python
# in class TestSeed: REPLACE test_seven_activities_four_reactions with:
    def test_activity_and_reaction_counts(self):
        acts = [s for s in default_states() if s.category == "activity"]
        reacts = [s for s in default_states() if s.category == "reaction"]
        assert len(acts) == 15 and len(reacts) == 4   # 6 business + 8 private + Idle; 4 reactions

# new class:
class TestContext:
    def test_eight_private_activities_seeded(self):
        priv = [s for s in default_states() if s.context == "private"]
        assert {s.key for s in priv} == {"chilling","friends","girlfriend","music","learning","code","eat","gaming"}

    def test_selector_rows_business_excludes_private_includes_idle(self):
        labels = {l for (l,_k,_c) in states.selector_rows(default_states(), "business")}
        assert "Coding" in labels and "Idle" in labels
        assert "Chilling" not in labels and "Friends" not in labels

    def test_selector_rows_private_excludes_business_includes_idle(self):
        labels = {l for (l,_k,_c) in states.selector_rows(default_states(), "private")}
        assert "Chilling" in labels and "Idle" in labels
        assert "Coding" not in labels and "Meeting" not in labels

    def test_selector_rows_no_context_returns_all(self):
        assert len(states.selector_rows(default_states())) == 15   # Phase-A behaviour preserved

    def test_context_default_pose_keys_resolve(self):
        keys = {s.key for s in default_states()}
        for pose_state in states.CONTEXT_DEFAULT_POSE.values():
            assert pose_state in keys   # "idle","chilling" are real state keys
```

- [ ] **Step 2: Run — expect FAIL** (`selector_rows` takes no context; counts off; no `CONTEXT_DEFAULT_POSE`)

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_states.py -q`

- [ ] **Step 3: Edit `serenity/core/states.py`**

Append after the last reaction row in `DEFAULT_STATES` (before the closing `]`):
```python
    # Phase B - Private context activity set.
    ActivityState("chilling",   "Chilling",   "#8fd36a", ("chilling","silent"),                          "activity", "private"),
    ActivityState("friends",    "Friends",    "#ff8ad0", ("cheering","giggeling","come"),                "activity", "private"),
    ActivityState("girlfriend", "Girlfriend", "#fb7185", ("amused","giggeling","verlegen"),              "activity", "private"),
    ActivityState("music",      "Music",      "#19e3ff", ("dj",),                                        "activity", "private"),
    ActivityState("learning",   "Learning",   "#5cc8ff", ("examining","nachdenklich","detektive","searching"), "activity", "private"),
    ActivityState("code",       "Code",       "#a78bfa", ("mission","work_2"),                           "activity", "private"),
    ActivityState("eat",        "Eat",        "#e3b341", ("idle_1","idle_2"),                            "activity", "private"),
    ActivityState("gaming",     "Gaming",     "#2dd4bf", ("concentrating","mission"),                    "activity", "private"),
```
Add near the top (after `IDLE_POSES`):
```python
CONTEXT_DEFAULT_POSE = {"business": "idle", "private": "chilling"}   # per-context "mood" pose-state
```
Replace `selector_rows`:
```python
def selector_rows(states: list[ActivityState], context: Optional[str] = None) -> list[tuple[str, str, str]]:
    rows = activities(states)
    if context is not None:
        rows = [s for s in rows if s.context in (context, "any")]   # "any" (Idle) shows in both
    return [(s.label, s.key, s.color) for s in rows]
```
Update the module header's Functions block: note `selector_rows(states, context=None)` + `CONTEXT_DEFAULT_POSE`.

- [ ] **Step 4: Run — expect PASS**; then **full suite** green.
- [ ] **Step 5: Commit** — `git commit -m "feat(states): Private context activity set + CONTEXT_DEFAULT_POSE + context-filtered selector_rows (Phase B)"`

---

### Task 2: Settings — `current_context` + guard + load-heal

**Files:** Modify `serenity/core/settings.py`; Test `tests/test_states.py` (new `TestContextPersistence`).

**Interfaces:** Produces `Settings.current_context: str = "business"`; `Settings.context() -> str`.

- [ ] **Step 1: Write failing tests**
```python
class TestContextPersistence:
    def _mk(self, tmp_path, **kw):
        from serenity.core.settings import Settings
        s = Settings(**kw); s._path = tmp_path / "settings.json"; return s

    def test_default_is_business(self, tmp_path):
        assert self._mk(tmp_path).context() == "business"

    def test_roundtrip_private(self, tmp_path):
        from serenity.core.settings import Settings
        s = self._mk(tmp_path, current_context="private"); s.save()
        assert Settings.load(s._path).context() == "private"

    def test_invalid_value_coerced_and_healed(self, tmp_path):
        from serenity.core.settings import Settings
        s = self._mk(tmp_path, current_context="Business"); s.save()
        back = Settings.load(s._path)
        assert back.context() == "business"          # read guard
        assert back.current_context == "business"    # load-time heal (raw field fixed)
```

- [ ] **Step 2: Run — expect FAIL** (no `current_context`/`context()`).
- [ ] **Step 3: Edit `serenity/core/settings.py`**

Add the field right after `activity_states` (line ~79):
```python
    # global Private<->Business context; swaps the offered activity set + mood pose
    current_context: str = "business"
```
Add the guard method (near `states()`):
```python
    def context(self) -> str:
        return self.current_context if self.current_context in ("business", "private") else "business"
```
In `load()`, right after the `undo_seconds` coercion block (after line ~109), add the heal [P3.3]:
```python
        if s.current_context not in ("business", "private"):
            s.current_context = "business"
```

- [ ] **Step 4: Run — expect PASS**; **full suite** green.
- [ ] **Step 5: Commit** — `git commit -m "feat(settings): current_context + guard + load-heal (Phase B)"`

---

### Task 3: MascotStage — context signal, context-filtered ring, open-ring rebuild, context bubble

**Files:** Modify `serenity/ui/mascot_stage.py`; Test `tests/test_ui_context.py` (new).

**Interfaces:**
- Consumes: `Settings.context()`, `states.selector_rows(states, context)`.
- Produces: `MascotStage.context_toggle_requested` (Signal, no args); `open_selector` renders only current-context activities + a context-toggle bubble; `refresh_selector()` rebuilds an open ring.

- [ ] **Step 1: Write failing tests** — `tests/test_ui_context.py`
```python
"""
============================================================
Author:  Berk
Created: 2026-07-01
Purpose: UI tests for the Phase B context toggle (mascot selector + shell flip).
Role:    Under QT_QPA_PLATFORM=offscreen, assert the ring filters by context,
         rebuilds on an open-ring flip, and the shell keeps all surfaces in sync.

Test classes:
- TestMascotContext - selector filtering + open-ring rebuild + context bubble
- TestShellContext - set_context flips/persists/syncs; mood pose; startup sync
============================================================
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from serenity.core import states
from serenity.core.settings import Settings
from serenity.ui.mascot_stage import MascotStage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    s = Settings(); s.vault_path = str(tmp_path / "vault"); s._path = tmp_path / "settings.json"
    return s


class TestMascotContext:
    def test_open_selector_shows_only_current_context(self, qapp, settings):
        settings.current_context = "private"
        m = MascotStage(settings)
        m.open_selector()
        labels = [b.activity for b in m._bubbles]
        assert "Chilling" in labels and "Coding" not in labels    # private set (+ Idle + context bubble)

    def test_flip_while_open_rebuilds_ring(self, qapp, settings):
        settings.current_context = "business"
        m = MascotStage(settings)
        m.open_selector()
        assert "Coding" in [b.activity for b in m._bubbles]
        settings.current_context = "private"                       # simulate a flip
        m.refresh_selector()
        assert m._selector_open                                    # ring stays open
        labels = [b.activity for b in m._bubbles]
        assert "Chilling" in labels and "Coding" not in labels     # rebuilt for the new context

    def test_context_bubble_emits_signal(self, qapp, settings):
        m = MascotStage(settings)
        fired = []
        m.context_toggle_requested.connect(lambda: fired.append(True))
        m.open_selector()
        ctx_bubble = next(b for b in m._bubbles if b.activity.startswith("→"))  # "-> Private"
        ctx_bubble.click()
        assert fired == [True]
```
(`ActivityBubble` stores its label as `.activity` — add that in Step 3 if absent.)

- [ ] **Step 2: Run — expect FAIL** (no context filtering / signal / `.activity`).
- [ ] **Step 3: Edit `serenity/ui/mascot_stage.py`**

Add the signal next to `activity_changed` (class level, ~line 118):
```python
    context_toggle_requested = Signal()   # emitted by the in-ring "switch context" bubble
```
Ensure `ActivityBubble` exposes its label — in `ActivityBubble.__init__`, add `self.activity = label` (so tests + rebuild can read it).
Rewrite `open_selector` to filter by context and append the context bubble:
```python
    def open_selector(self):
        if self._selector_open:
            return
        self._selector_open = True
        ctx = self.settings.context()
        for label, _key, color in states.selector_rows(self.settings.states(), ctx):
            b = ActivityBubble(label, color, self)
            b.clicked.connect(lambda _=False, lbl=label: self._on_pick(lbl))
            self._bubbles.append(b)
        other = "Business" if ctx == "private" else "Private"
        ctx_b = ActivityBubble(f"→ {other}", "#c9bff0", self)   # "-> <other context>"
        ctx_b.clicked.connect(lambda _=False: self.context_toggle_requested.emit())
        self._bubbles.append(ctx_b)
        self._relayout()
```
`_on_pick` — pass context so the label→key lookup uses the current set:
```python
    def _on_pick(self, label: str):
        rows = states.selector_rows(self.settings.states(), self.settings.context())
        key = next((k for (l, k, _c) in rows if l == label), "idle")
        self.current_activity = label
        self.close_selector()
        self.set_state(key)
        self.activity_changed.emit(label)
```
`refresh_selector` — rebuild an open ring [P2.1/2.2/2.4]:
```python
    def refresh_selector(self):
        """Re-read the state map + (if the ring is open) rebuild it for the current context."""
        self._selector = PoseSelector(self.settings.state_map())
        if self._selector_open:
            self.close_selector()
            self.open_selector()
```

- [ ] **Step 4: Run — expect PASS** (`TestMascotContext`); **full suite** green.
- [ ] **Step 5: Commit** — `git commit -m "feat(ui): context-filtered mascot ring + open-ring rebuild + context bubble (Phase B)"`

---

### Task 4: Icons + TitleBar context button

**Files:** Modify `serenity/ui/icons.py`, `serenity/ui/shell.py` (TitleBar).

**Interfaces:** Produces icon names `"business"`, `"private"`; `TitleBar.context_btn`; `TitleBar.sync_context_icon()`.

- [ ] **Step 1: Add icons** — in `serenity/ui/icons.py` `_PATHS`, add:
```python
    "business": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "private": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
```
- [ ] **Step 2: Add the title-bar button** — in `TitleBar.__init__` (after the `mute_btn` block, ~line 108):
```python
        # context toggle: checked = Private. Reflects settings.current_context (see Shell.set_context).
        self.context_btn = QPushButton()
        self.context_btn.setObjectName("iconbtn")
        self.context_btn.setCheckable(True)
        self.context_btn.clicked.connect(shell.toggle_context)
        self.sync_context_icon()
```
Add `self.context_btn` to the sizing/layout loop (line ~135):
```python
        for b in (self.pin_btn, self.mute_btn, self.context_btn, self.mode_btn, hide_btn, set_btn, min_btn):
```
Add the sync method (after `_sync_mute_icon`):
```python
    def sync_context_icon(self):
        """Match the context button to settings.current_context (checked + house icon = Private)."""
        private = self.shell.settings.context() == "private"
        self.context_btn.setChecked(private)
        self.context_btn.setIcon(icons.icon("private" if private else "business", COLORS["ink2"], 15))
        self.context_btn.setToolTip(f"Context: {'Private' if private else 'Business'} - click to switch")
```
- [ ] **Step 3: Run the full suite** — green (no behaviour tested yet; `toggle_context` lands in Task 5. This task must not run before Task 5 in a red state — so verify by importing only; the `clicked.connect(shell.toggle_context)` requires `Shell.toggle_context` to exist. **Implement Task 5 before running the app**, but the suite stays green because no test constructs TitleBar without a Shell.)

> Note: Tasks 4 and 5 are mutually dependent (TitleBar references `shell.toggle_context`; Shell syncs `title_bar.context_btn`). Implement them back-to-back and commit **together** if a green gate can't sit between them.

- [ ] **Step 4: Commit** (with Task 5, or standalone if suite green) — `git commit -m "feat(ui): title-bar context toggle button + icons (Phase B)"`

---

### Task 5: Shell orchestration — `set_context`/`_sync_context`, tray action, mini forwarding, boot sync

**Files:** Modify `serenity/ui/shell.py`, `serenity/ui/mini_window.py`; Test `tests/test_ui_context.py` (`TestShellContext`).

**Interfaces:**
- Consumes: `states.CONTEXT_DEFAULT_POSE`, `Settings.context()`, `MascotStage.context_toggle_requested`.
- Produces: `Shell.toggle_context()`, `Shell.set_context(ctx)`, `Shell._sync_context()`, `Shell._mascots()`, `Shell._context_action`.

- [ ] **Step 1: Write failing tests** (`TestShellContext` in `tests/test_ui_context.py`)
```python
class TestShellContext:
    def _shell(self, qapp, tmp_path, monkeypatch, context="business"):
        from serenity.core import paths
        monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)
        from serenity.ui.shell import Shell
        sh = Shell()
        sh.settings.current_context = context
        return sh

    def test_toggle_flips_and_persists(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(qapp, tmp_path, monkeypatch, "business")
        sh.toggle_context()
        assert sh.settings.context() == "private"
        from serenity.core.settings import Settings
        assert Settings.load(sh.settings._path).context() == "private"   # saved

    def test_mood_pose_only_when_idle(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(qapp, tmp_path, monkeypatch, "business")
        assert sh.activity_store.running() is None
        sh.set_context("private")
        assert sh.mascot.current_state == "chilling"      # mood pose applied when idle
        sh.activity_store.start("Coding")                 # now tracking
        sh.set_context("business")
        assert sh.mascot.current_state == "chilling"      # unchanged - span running, no mood flip

    def test_invalid_context_coerced(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(qapp, tmp_path, monkeypatch, "business")
        sh.set_context("bogus")                            # must not KeyError
        assert sh.settings.context() == "business"

    def test_title_bar_synced_on_flip(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(qapp, tmp_path, monkeypatch, "business")
        sh.set_context("private")
        assert sh.title_bar.context_btn.isChecked()        # title-bar reflects private
        assert sh._context_action.isChecked()              # tray action reflects private
```
(If `Shell()` construction differs from `test_power.py`'s usage, mirror that — it constructs `Shell()` / `Shell(boot=True)` under the `qapp` fixture.)

- [ ] **Step 2: Run — expect FAIL** (no `toggle_context`/`set_context`).
- [ ] **Step 3: Edit `serenity/ui/mini_window.py`** — forward the context signal (mirror `activity_changed`):
```python
    # near line 45, with the other signals:
    context_toggle_requested = Signal()
    # near line 108, after the activity_changed forward:
        self.mascot.context_toggle_requested.connect(self.context_toggle_requested.emit)
```
- [ ] **Step 4: Edit `serenity/ui/shell.py`**

Import states (top, with the other `..core` imports): `from ..core import states`.
Wire the shell mascot's context signal (after line 374 `self.mascot.activity_changed.connect(self._on_activity)`):
```python
        self.mascot.context_toggle_requested.connect(self.toggle_context)
```
Add the boot-time sync after the chip restore (after line 355):
```python
        self._sync_context()   # title-bar/tray reflect the persisted context + mood pose when idle
```
In `_build_tray`, after the mode-group block (after line 398, before `menu.addSeparator()`):
```python
        menu.addSeparator()
        self._context_action = QAction("", self)
        self._context_action.setCheckable(True)
        self._context_action.triggered.connect(self.toggle_context)
        menu.addAction(self._context_action)
```
In `_ensure_mini` (after line 910):
```python
            self._mini.context_toggle_requested.connect(self.toggle_context)
```
Add the orchestration methods (near `toggle_mute`, ~line 779):
```python
    def _mascots(self):
        ms = [self.mascot]
        if self._mini is not None:
            ms.append(self._mini.mascot)
        return ms

    def toggle_context(self):
        self.set_context("private" if self.settings.context() == "business" else "business")

    def set_context(self, ctx: str):
        if ctx not in ("business", "private"):      # guard the write + CONTEXT_DEFAULT_POSE[] [P3.1]
            ctx = "business"
        self.settings.current_context = ctx
        self.settings.save()
        self._sync_context()

    def _sync_context(self):
        """Re-sync every context surface (title-bar / tray / both mascots) + the idle mood pose."""
        ctx = self.settings.context()
        idle = self.activity_store.running() is None
        for m in self._mascots():
            m.refresh_selector()
            if idle:
                m.set_state(states.CONTEXT_DEFAULT_POSE[ctx])
        if hasattr(self, "title_bar"):
            self.title_bar.sync_context_icon()
        if hasattr(self, "_context_action"):
            other = "Private" if ctx == "business" else "Business"
            self._context_action.setText(f"Switch to {other}")
            self._context_action.setChecked(ctx == "private")
```

- [ ] **Step 5: Run — expect PASS** (`TestShellContext`); **full suite** green.
- [ ] **Step 6: Commit** — `git commit -m "feat(ui): Shell context orchestration - set_context + 3 entry points + both mascots + boot sync (Phase B)"` (fold Task 4 in if no green gate sat between).

---

### Task 6: Notes wrap + final verification

**Files:** Modify `notes/1_Planning.md`.

- [ ] **Step 1:** Full suite green; record the new count.
- [ ] **Step 2:** Add a 2026-07-01 Phase B wrap (context toggle shipped, 3 entry points, 8 Private activities, 11 flow-harden gaps folded, next = Phase C).
- [ ] **Step 3:** Commit — `git commit -m "docs(notes): Phase B context toggle shipped; next = Phase C"`

---

## Self-review

- **Spec coverage:** §3 registry → T1; §4 settings → T2; §6 selector/open-ring → T3; §7 title-bar → T4, bubble → T3, tray → T5; §5 flip flow + §8 startup + mini → T5; all 8 folded gaps: P2.1/2.2/2.4 (T3 refresh_selector), P2.3/2.6 (T5 `_context_action`+`_sync_context`), P2.5 (T4 sync + T5 boot), P2.7 (T5 boot mood), P2.8 (T1 count test), P3.1 (T5 guard), P3.2 (T5 `_mascots`), P3.3 (T2 load-heal). ✅
- **Placeholders:** none — full code per step.
- **Type consistency:** `selector_rows(states, context=None)`, `context()`, `CONTEXT_DEFAULT_POSE`, `context_toggle_requested`, `set_context`/`toggle_context`/`_sync_context`/`_mascots`/`_context_action`, `sync_context_icon` — names consistent T1→T5. `ActivityBubble.activity` added in T3 and read by tests.
- **Note:** T4↔T5 are mutually dependent (TitleBar refs `shell.toggle_context`; Shell syncs `context_btn`) — implement back-to-back; a green gate only exists once both land, so commit together if needed.
