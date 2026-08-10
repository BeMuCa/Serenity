# Phase A — State/Context Registry — Design Spec

_Date: 2026-07-01 · Branch: `wf/phase-a-states` · Milestone: States & Contexts (foundation phase)_
_Status: approved design (brainstorm + flow-harden complete); source for the TDD plan._

## 1. Goal

Replace the **three hand-synced, hardcoded activity/state sources** with **one canonical registry** in a new `core/states.py`, and **promote the full styled pose library** so no rendered art is stranded. The registry becomes the single source of truth that the activity selector, the running-activity chip, and the pose map all read as **projections**. This is the foundation the rest of the States & Contexts milestone (Phases B–I) builds on.

## 2. Current state (what we are consolidating)

Three copies, kept in step by hand:

| Source | File:line | Shape | Consumers |
|--------|-----------|-------|-----------|
| `ACTIVITIES` | `ui/mascot_stage.py:43` | `list[(label, state_key, color)]` × 7 | `open_selector()` (241), `_on_pick()` (255) |
| `_ACTIVITY_COLORS` | `ui/activity_chip.py:28` | `{label: color}` | `_color_for()` (79) → `show_running()` (89) |
| `DEFAULT_STATE_MAP` | `core/poses.py:41` | `{state_key: [pose_keys]}` × 10 (6 activity + 4 reaction) | `default_state_map()` (59), `Settings.state_map()` (136), `PoseSelector` (mascot_stage 132) |

Facts that shape the design (verified in code):
- **The display `label` is today's de-facto identity**: `activity_store` logs `ActivityEntry.category = label` (`core/activity.py:41`); `_ACTIVITY_COLORS` is keyed by label; the Weekly Board aggregates by `category`.
- **`state_key` is NOT unique** — it is only the pose-group. `("Focus", "coding", …)` reuses `coding`'s poses.
- `set_state()` (`mascot_stage.py:266`) swaps pose only; **reaction states** (`alert/thinking/success/error`) are pose-only and never enter the log.
- **A 4th hardcoded `set_state("coding")`** lives at `shell.py:481` (focus phase-end reaction) — not one of the 3 sources.
- `Settings` (`core/settings.py`) is a JSON-persisted dataclass; `load()` drops unknown keys (backward-compat is free) but does **no per-value validation** (`settings.py:100-101`); the corrupt-file guard covers only whole-file `JSONDecodeError/OSError` (`87-96`). `state_map()` (`135-136`) uses **REPLACE** semantics (`state_pose_map if truthy else default`). `state_pose_map` survives malformation today only because it is consumed as a raw dict, never reconstructed into a typed object.
- No Private/Business `context` concept exists anywhere. The Weekly Board has no per-activity colors.

## 3. The registry — `core/states.py` (Qt-free, headless-tested)

```python
ACCENT = "#a78bfa"                         # module-level; keeps this file framework-free
IDLE_POSES = ("idle_1", "idle_2", "chilling", "idle_3", "silent")

@dataclass(frozen=True)
class ActivityState:
    key:      str                          # stable id; drives pose lookup
    label:    str                          # display name; what the activity log stores
    color:    str = ACCENT                 # neon hex (used only by menu + chip)
    poses:    tuple[str, ...] = IDLE_POSES  # pose-image KEYS (resolved via POSE_FILES)
    category: str = "activity"             # "activity" (trackable) | "reaction" (pose-only)
    context:  str = "any"                  # "business" | "private" | "any"
```

Pure helpers:
- `default_states() -> list[ActivityState]` — a fresh copy of the seed.
- `activities(states) -> list[ActivityState]` — rows where `category == "activity"`.
- `is_protected(s) -> bool` — `s.category == "reaction" or s.key == "idle"` (used by Phase E's delete-guard; data marker only in Phase A).
- `color_for_label(label, states=None) -> str` — registry color for a label, else `ACCENT` (preserves today's miss-default; defaults to `default_states()` when `states` is None).

### Seed (`DEFAULT_STATES`) — enriched with all fitting promoted poses

| key | label | cat | color | poses (keys) | context |
|-----|-------|-----|-------|--------------|---------|
| working | Working | activity | `#a78bfa` | work_1, work_2, concentrating | business |
| coding | Coding | activity | `#ff8ad0` | mission, work_2, concentrating | business |
| meeting | Meeting | activity | `#5cc8ff` | time, aufmerksam, come | business |
| planning | Planning | activity | `#8fd36a` | nachdenklich, examining, detektive, searching | business |
| focus | Focus | activity | `#19e3ff` | mission, work_2, glasses_off | business |
| entertainment | Entertainment | activity | `#e3b341` | chilling, fun, dj, cheering, giggeling, amused | business |
| idle | Idle | activity | `#19e3ff` | idle_1, idle_2, chilling, idle_3, silent | any |
| alert | Alert | reaction | `ACCENT` | hinweis, aufmerksam | any |
| thinking | Thinking | reaction | `ACCENT` | nachdenklich, examining, concentrating | any |
| success | Success | reaction | `ACCENT` | happy, fun, happy_2, relieved, cheering | any |
| error | Error | reaction | `ACCENT` | mad, mad_2, ups, ups_2, annoyed, überhitzt, frozen, spilled_coffee | any |

**Focus cleanup:** `focus` gets its own key, seeded with coding's core poses (`mission, work_2`) plus `glasses_off`. Picking Focus still shows a work-family pose and still logs the label `Focus`; the change is that it now calls `set_state("focus")` instead of `set_state("coding")`. Nothing that worked stops working, but note the pose *pools* are intentionally **enriched** (more variety — focus gains `glasses_off`) and the 14 existing images are **re-styled** — both intended visible changes per option B + (i), not regressions.

## 4. Asset promotion

Copy the **styled `.webp` poses only** from `current_Imgs/` into `serenity/assets/poses/` and extend `POSE_FILES` (`core/poses.py`) with every promoted key → filename.

- **`*.webp` only** — the 14 `.gif` twins in `current_Imgs/` are excluded (explicit glob, never a directory-level copy). [gap P3.3]
- This **overwrites the 14 existing poses** with their re-styled versions **and adds 27 new** → 41 total (user chose option (i): one consistent style). Visible in-app change to the existing 14, by design.
- **Reserved poses** (`hi, leaving, next_task, ripped_note, trash, verlegen, hand_disappearing`) are added to `POSE_FILES` so they are available, but are **not seeded into any state** — their triggers are Phase F (greetings) / event wiring. (`come` is the one beckon pose that *is* seeded — into `meeting`.) Tally: of the 27 new poses, 20 are seeded into states and 7 stay reserved.

## 5. Projections & rewiring

The registry is the source; the three structures become computed views:

- **`ACTIVITIES`** → built from `settings.states()` activity rows as `[(s.label, s.key, s.color)]`. `_on_pick()` maps `label → key → set_state(key)`. (Menu has `settings`, so it reads the live registry.)
- **`_ACTIVITY_COLORS`** → **deleted**; `activity_chip._color_for(label)` returns `states.color_for_label(label)` (keeps the `ACCENT` miss-default). [gap P2.3] (In Phase A the registry == code default, so `color_for_label` reads `default_states()`; wiring the chip to the live `settings` registry is a Phase-E concern, once recolor editing exists.)
- **`DEFAULT_STATE_MAP` / `Settings.state_map()`** → derived from the registry as `{s.key: list(s.poses) for s in states}`, then **overlaid** by any legacy `state_pose_map` (see §6). `POSE_FILES` extended per §4.
- **`shell.py:481`** → `set_state("success" if phase != "focus" else "focus")` (was `"coding"`). [gap P3.1]

Files touched: **new** `core/states.py`; `core/poses.py` (`POSE_FILES` grows; `DEFAULT_STATE_MAP` becomes registry-derived); `core/settings.py` (`activity_states` field + `states()` + rewritten `state_map()`); `ui/mascot_stage.py` (`ACTIVITIES` projection, `_on_pick` uses `key`); `ui/activity_chip.py` (color via registry); `ui/shell.py:481`.

## 6. Persistence & backward-compat

- New field: `Settings.activity_states: list = field(default_factory=list)` — empty means "use the code default".
- **`Settings.states()` treats `activity_states` as fully untrusted** [gap P1.1, P2.4, P3.2]:
  1. Not a list, or empty → `default_states()`.
  2. Per row, require: row is a `dict`; keys ⊆ `ActivityState` field names; `key` and `label` present (the only fields without dataclass defaults); if `poses` is present it is a list/tuple of `str`.
  3. Coerce `poses` back to a **tuple** (JSON round-trips it as a list).
  4. Enforce **cross-row key uniqueness**.
  5. **Any** violation (bad row shape, missing/extra key, wrong type, duplicate key) → discard the **whole** override → `default_states()` (never ship a partial registry). Mirrors the defensive intent of `activity_store.py:64-82`.
- **`Settings.state_map()` = registry-derived base, then key-level overlay** [gap P2.5, P2.6]:
  ```python
  def state_map(self) -> dict:
      base = {s.key: list(s.poses) for s in self.states()}   # includes the new "focus" key
      for k, v in (self.state_pose_map or {}).items():
          if v:
              base[k] = list(v)
      return base
  ```
  Never early-returns the raw legacy override, so newly-seeded keys (`focus`) always resolve.
- Old `settings.json` with no `activity_states` → unknown-key drop → default registry. **Zero migration.** The activity log (`ActivityEntry.category = label`) is unchanged; existing `activity.json` keeps working.
- Nothing is written to disk until a user edits (Phase E) — `settings.json` stays clean; the default lives in code.

## 7. Hardened behaviors folded from the flow-harden pass (12 confirmed)

| # | Pri | Requirement | Verify |
|---|-----|-------------|--------|
| P1.1 | P1 | `states()` untrusted-input contract (§6) — no crash on any malformed persisted row | test: bad row (missing/extra key, non-dict, non-list, bad poses) → `states()` returns default, does NOT raise |
| P2.1/2.7/2.8 | P2 | Rewrite `test_poses.py:32-35` **in the same commit** as the promote: drop `len==14`; change `used == set(keys)` → `used ⊆ set(keys)` (seeded poses ⊆ POSE_FILES; reserved poses need not be seeded) | suite stays green across the promote task |
| P2.2 | P2 | Every seeded pose_key ∈ `POSE_FILES`; every `poses` tuple non-empty | test in `test_states.py` |
| P2.3 | P2 | Chip color keeps the `ACCENT` miss-default for unknown/stale labels | test: `color_for_label("Nonexistent") == ACCENT` |
| P2.4 | P2 | Duplicate keys in persisted registry → whole override discarded | test in `test_states.py` |
| P2.5/2.6 | P2 | `state_map()` overlay (§6): legacy `state_pose_map` never hides the `focus` key | test: legacy 10-state map → `state_map()["focus"]` present (= focus's seeded poses), never absent |
| P3.1 | P3 | `shell.py:481` → `"focus"` | test: focus phase-end resolves to focus pose family |
| P3.2 | P3 | `poses` coerced to tuple on load (folded into P1.1) | round-trip test: `states()[i].poses` is a `tuple` |
| P3.3 | P3 | Promote `*.webp` only; the 14 `.gif` twins excluded | test: no non-`.webp` in `POSE_FILES`; every value exists on disk (existing `test_shipped_files_exist_on_disk` extends to guard this) |

## 8. Out of scope (deferred to their phases)

Settings editor UI + auto-color-on-add helper + delete-guard **enforcement** (E) · Private/Business toggle + filtering (B) · per-activity board colors (D) · greeting/event pose **triggers** (F / event wiring) · activity-log key migration (deferred by design — label stays the log identity). The `context` field and `is_protected` data markers are seeded now but read by no code until B/E.

## 9. Testing plan

- **`tests/test_states.py`** (new): seed integrity (unique keys; every seeded pose ∈ `POSE_FILES`; reaction rows flagged; `is_protected` = reactions + idle; `context` defaults); `color_for_label` (hit + `ACCENT` miss); `states()` deserializer (round-trip equal; empty→default; not-a-list→default; missing/extra key→default; non-dict row→default; bad `poses`→default; duplicate key→default; `poses` is a tuple after load); `state_map()` overlay (registry base includes `focus`; legacy override overlays per-key and never hides seeded keys).
- **`tests/test_poses.py`**: rewrite `test_all_14_poses_referenced` per P2.1; the other three tests extend as-is to guard the promote (every `POSE_FILES` value ends `.webp` + exists on disk; `state_map` keys resolve).
- **Existing UI tests** (mascot/chip/poses/settings) stay green — the rewire preserves every existing behavior path (any test asserting a *specific* pre-enrichment pose set may need its expectation widened to the enriched pool). Add: picking Focus calls `set_state("focus")` and resolves to focus's seeded pool (work-family: `mission/work_2/glasses_off`).
- Gate: full headless suite (`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`) green after **every** task.

## 10. Impact gate (before editing the hardcoded symbols)

Fresh `npx gitnexus analyze`, then `gitnexus_impact` (upstream) on `ACTIVITIES` / `_ACTIVITY_COLORS` / `DEFAULT_STATE_MAP` / `set_state`. HIGH fan-out expected. Explicitly confirm nothing **reads** `current_state == "coding"` in a way the focus-key change breaks (the flow-harden pass already found the only other `set_state("coding")` **write** site at `shell.py:481`, folded in as P3.1). If a real `current_state == "coding"` reader exists, `focus` keeps `key="coding"` as a fallback.
```
