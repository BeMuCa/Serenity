# Phase B — Global Private↔Business Context Toggle — Design Spec

_Date: 2026-07-01 · Branch: `wf/phase-b-context` (off `wf/phase-a-states`) · Milestone: States & Contexts_
_Status: approved design + flow-hardened (11 gaps → 8 deduped requirements folded); source for the TDD plan._

## 1. Goal

A global **Private↔Business** context toggle. Flipping it (a) swaps which activities the mascot selector offers, (b) shows a per-context "mood" idle pose, and (c) persists `current_context` — reachable from **three entry points** (title-bar button, in-ring bubble, tray menu), all kept in sync. Builds on the Phase A registry. **Context is a property of the activity (registry), not of the moment**: a running span is never stopped by a flip, and the Weekly Board's per-context split is derived later (Phase D).

## 2. Dependencies & current state

- Phase A registry: `core/states.py` (`ActivityState{key,label,color,poses,category,context}`, `DEFAULT_STATES`, `selector_rows(states)`, `Settings.states()`/`state_map()`). Of the current 7 activity rows, 6 are tagged `context="business"` (working/coding/meeting/planning/focus/entertainment); Idle is `context="any"`.
- `mascot_stage.py`: `open_selector()` builds `self._bubbles` once (guarded by `_selector_open`); `_on_pick(label)` maps label→key via `selector_rows` and emits `activity_changed`; `refresh_selector()` (line ~262) rebuilds **only** `self._selector` (the `PoseSelector`); `__init__` sets the resting pose with `set_state("idle", silent=True)` (line ~154).
- `shell.py`: `_build_tray()` (line ~380) builds a `QMenu` with `_mode_actions` + `_sync_mode_controls()` (~916); `_sync_mute_icon()` runs at title-bar init (~108) and the running chip is restored at boot (~355) via `activity_store.running()`. The **Mini window** (`mini_window.py:106`) owns a **separate** `MascotStage` (`self._mini.mascot`, lazy; `self._mini` at ~189).
- No context concept exists yet.

## 3. Registry additions (`core/states.py`)

Append 8 Private activities to `DEFAULT_STATES` (all `context="private"`; every pose key already in `POSE_FILES` from Phase A):

| key | label | color | poses |
|-----|-------|-------|-------|
| chilling | Chilling | `#8fd36a` | chilling, silent |
| friends | Friends | `#ff8ad0` | cheering, giggeling, come |
| girlfriend | Girlfriend | `#fb7185` | amused, giggeling, verlegen |
| music | Music | `#19e3ff` | dj |
| learning | Learning | `#5cc8ff` | examining, nachdenklich, detektive, searching |
| code | Code | `#a78bfa` | mission, work_2 |
| eat | Eat | `#e3b341` | idle_1, idle_2 |
| gaming | Gaming | `#2dd4bf` | concentrating, mission |

Plus:
```python
CONTEXT_DEFAULT_POSE = {"business": "idle", "private": "chilling"}   # per-context "mood" pose-state

def selector_rows(states, context=None):     # context=None => all (Phase-A behaviour preserved)
    rows = activities(states)
    if context is not None:
        rows = [s for s in rows if s.context in (context, "any")]   # "any" (Idle) shows in BOTH
    return [(s.label, s.key, s.color) for s in rows]
```
`chilling` is a Private **activity key** *and* a **pose key** — different namespaces, no collision; `set_state("chilling")` resolves via the registry-derived `state_map` (which now includes a `chilling` key → its poses).

## 4. Settings (`core/settings.py`)

- New field `current_context: str = "business"` (old files → `business` via the existing unknown-key drop).
- Read guard `context()` returns `current_context` if in `("business","private")` else `"business"`.
- **Load-time heal** [gap P3.3]: in `load()`, right after the `undo_seconds` coercion, add `if s.current_context not in ("business","private"): s.current_context = "business"` — so a bad persisted value is *healed* (not just read-coerced then re-saved raw).

## 5. The flip flow + cross-surface sync (`Shell`)

One method drives everything; **all four surfaces re-sync** (this is the crux the flow-harden surfaced):
```python
def toggle_context(self):
    self.set_context("private" if self.settings.context() == "business" else "business")

def set_context(self, ctx):
    if ctx not in ("business", "private"):        # [P3.1] guard the write + the dict subscript
        ctx = "business"
    self.settings.current_context = ctx
    self.settings.save()
    self._sync_context()

def _sync_context(self):                          # also called once at startup [§8]
    ctx = self.settings.context()
    idle = self.activity_store.running() is None  # mood pose only when not tracking [Q4]
    for m in self._mascots():                     # shell mascot + mini mascot if it exists [P3.2]
        m.refresh_selector()                      # rebuilds an OPEN ring too (see §6) [P2.1/2.2/2.4]
        if idle:
            m.set_state(states.CONTEXT_DEFAULT_POSE[ctx])
    self.title_bar.sync_context_icon()            # [P2.5]
    self._sync_context_action()                   # tray menu item label/checkstate [P2.3/2.6]
```
`_mascots()` yields `self.mascot` + `self._mini.mascot` when `self._mini` is not None. A **running span is kept** on flip (mood pose is skipped when tracking).

## 6. Selector: filter by context + rebuild an open ring (`mascot_stage.py`)

- `open_selector()` / `_on_pick()` pass `self.settings.context()` into `states.selector_rows(...)` → only the current context's activities (+ Idle).
- **`refresh_selector()` rebuilds an open ring** [P2.1/2.2/2.4 — the dominant finding]:
  ```python
  def refresh_selector(self):
      self._selector = PoseSelector(self.settings.state_map())
      if self._selector_open:            # flip via the in-ring bubble must re-render, not go stale
          self.close_selector()
          self.open_selector()
  ```

## 7. Three entry points

- **Title-bar button** — a checkable `context_btn` next to mute/pin/mode; `clicked → shell.toggle_context`. `TitleBar.sync_context_icon()` sets its checkstate + icon (business vs private) from `settings.context()`. Add two SVG paths to `icons.py` `_PATHS` (`"business"`, `"private"`).
- **In-ring bubble** — `open_selector()` appends one extra bubble labelled with the *other* context; its click emits a new `MascotStage.context_toggle_requested` signal → `shell.toggle_context` (mirrors `activity_changed`). Both mascots' bubbles connect to the same handler.
- **Tray menu** — a context toggle `QAction` in `_build_tray()`, stashed as `self._context_action`; `_sync_context_action()` sets its text ("Switch to Private/Business") + checkstate. Left-click / `_on_tray_activated` still shows/restores the window (context lives on the right-click menu only) [tray-gesture flow].

## 8. Startup sync [P2.5, P2.7]

`MascotStage.__init__` fixes the resting pose to `idle` unconditionally. At `Shell` init (after mascot + activity_store + title bar exist, near the chip restore ~355), call `self._sync_context()` so the title-bar icon + tray item reflect the persisted context AND the correct mood pose shows when idle (fixes "Private last used → boots showing business idle").

## 9. Hardened behaviors folded from the flow-harden pass (11 confirmed → 8 requirements)

| # | Pri | Requirement | Verify |
|---|-----|-------------|--------|
| P2.1/2.2/2.4 | P2 | `refresh_selector()` rebuilds an **open** ring (stale-ring on in-ring flip) | test: open ring → `toggle_context` → live bubble labels == `selector_rows(states, new_ctx)`; `_selector_open` still True |
| P2.3/2.6 | P2 | Tray context action re-synced on every flip (label + checkstate), regardless of entry point | test: flip from title-bar → tray action text/checkstate reflect new ctx |
| P2.5 | P2 | Title-bar context icon synced at **startup** | test: boot with `current_context="private"` → `context_btn` reflects private |
| P2.7 | P2 | **Startup mood pose** matches persisted context when idle | test: boot private + not running → mascot pose-state is `chilling`; boot with a running span → pose unchanged |
| P2.8 | P2 | Update Phase-A seed tests for the 8 new rows | `test_seven_activities_four_reactions` → `len(activities)==15 and len(reactions)==4` (6 business + 8 private + Idle) |
| P3.1 | P3 | `set_context` coerces invalid `ctx`→business before persist + `CONTEXT_DEFAULT_POSE[]` | test: `set_context("bogus")` → business, no `KeyError` |
| P3.2 | P3 | Mini-window mascot refreshed + mood-posed on flip | test: with `_mini` present, flip → mini mascot selector/pose updated |
| P3.3 | P3 | `load()` heals an invalid persisted `current_context` | test: load `current_context="Business"`/`5` → `business`, no crash |

## 10. Out of scope (later phases)

Weekly Board business/private/both view → **Phase D** (enabled by the `context` tags seeded here). `state_tag` filtering of todos/notes → **Phase C**. Editor UI for activities → **Phase E**. Two-idle-states modelling — explicitly rejected (one shared Idle + `CONTEXT_DEFAULT_POSE`).

## 11. Testing

- **`tests/test_states.py`**: 8 Private activities seeded (`context="private"`, unique keys/labels, poses ⊆ `POSE_FILES`); `selector_rows(states,"business")` excludes private + includes Idle; `selector_rows(states,"private")` excludes business + includes Idle; `selector_rows(states)` unchanged (all); `CONTEXT_DEFAULT_POSE` values resolve to `state_map` keys; **update** `test_seven_activities_four_reactions` → 15/4.
- **`tests/test_settings` (or test_states)**: `current_context` round-trip; old file → business; invalid value → business (guard + load-heal).
- **UI tests** (mascot/shell): `set_context` flips+persists; `_sync_context` updates title-bar + tray + both mascots; open-ring rebuild on flip; mood pose only when idle; running span survives a flip; each of the 3 entry points invokes `toggle_context`; startup sync.
- Gate: full headless suite green after every task (`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`).

## 12. Impact gate (before editing)

Grep the consumers of `refresh_selector`, `open_selector`, `selector_rows`, `set_state`, and the tray/title-bar builders. `selector_rows` gains an optional `context` param (default None = Phase-A behaviour, so existing callers/tests are unaffected). The two-mascot reality (shell + mini) is the main blast surface — both must be handled by `_sync_context`.
