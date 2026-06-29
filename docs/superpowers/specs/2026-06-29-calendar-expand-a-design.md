# Calendar-expand — slice (a): read-only expanded week grid — design spec (hardened)

_Status: APPROVED design + flow-hardening folded in. Date: 2026-06-29._
_Slice (a) of 3. (b) = drag-schedule/create write path; (c) = ICS import/export — each its own later spec._
_Reuses the `ExpandedPanel` foundation from Notes-expand (`docs/superpowers/specs/2026-06-27-notes-expand-design.md`)._
_Hardening: 3-slice pass, 23 candidates → 7 confirmed (0 P1, 4 P2, 3 P3)._

---

## 1. Summary & scope

Expand the Calendar tab into a large left-docked **Teams-style week time-grid** in the shared
`ExpandedPanel`: 7 day-columns (Mon–Sun) × hour rows, an all-day strip on top, today highlighted,
week nav, and a **read-only right-hand list of active todos** (inert here; it becomes the drag
source in slice (b)). **Read-only — no writes.**

**In scope:** a Qt-free `build_timegrid` layout helper in `core/calview.py`; a `CalendarWeekPanel`
widget; the Calendar tab's expand (⤢) entry button; generalizing the shell's single-instance
pop-out management to host *either* a note or a calendar.

**Out of scope:** drag-scheduling, slot-click creation, the right list becoming draggable (all (b));
ICS import/export (c); month view in the pop-out (the tab keeps month); any write path.

## 2. Locked decisions
1. **Grid hours:** full 24h in the grid, viewport default-scrolled to ~08:00 (working-hours window;
   off-hours by scroll).
2. **Events are instants:** a `Todo` has only `due` (no duration) → each renders as a small block at
   its due-hour; exact-midnight (`has_time` False) → the all-day strip.
3. **Right panel:** read-only list of **active** todos (open, not trashed), ordered like the Todos
   tab; inert in (a).
4. **Read-only:** click an event → deep-link to the Todos tab; empty-slot clicks do nothing.

## 3. Architecture (mirrors the `calview`/`calendar_view` split)

- `serenity/core/calview.py` *(edit)* — add **`build_timegrid(events, anchor, now=None) -> TimeGrid`**
  (Qt-free, headless-tested) + a `TimeGrid` dataclass. Reuses `_week_start`, `_week_label`, and the
  existing `CalEvent.has_time` (from `collect_events` → `_has_time`); does **not** recompute the
  midnight boundary.
- `serenity/ui/calendar_week_panel.py` *(new)* — `CalendarWeekPanel(todo_store)`: renders the grid +
  all-day strip + right active-todo list + week nav; `open_todo = Signal(str)`; `refresh()`;
  `on_panel_activated()`; `handle_close() -> bool`. Hosted inside an `ExpandedPanel`.
- `serenity/ui/calendar_view.py` *(edit)* — add the expand (⤢) button to the Calendar tab, emitting
  an `expand_requested` signal the shell connects.
- `serenity/ui/shell.py` *(edit)* — generalize the single-instance pop-out so `self._expanded` holds
  either a `NoteEditorPanel` or a `CalendarWeekPanel`; add `_open_calendar_expanded()`; refresh hooks.

### 3.1 `build_timegrid` contract
`TimeGrid` dataclass: `days: list[date]` (7, Mon→Sun), `hours: list[int]` (0..23, always full),
`all_day: dict[date, list[CalEvent]]`, `cells: dict[tuple[date, int], list[CalEvent]]`,
`label: str`, `today: date | None`.

- `now = now or datetime.now()`; `start = _week_start(anchor)`; `days = [start+i for i in range(7)]`.
- **Week-membership filter:** only events with `e.when.date() in days` are placed; others dropped
  (mirrors `build_week`'s `_day_cell` date filter — guards "phantom events from other weeks").
- For each placed event: `not e.has_time` → `all_day[day]`; else → `cells[(day, e.when.hour)]`.
- **Deterministic order:** every `all_day[day]` list and every `cells[...]` bucket is sorted by the
  existing key `(not e.has_time, e.when, e.title)` (the one `_day_cell` uses and `test_calview`
  pins) — so stack order can't flicker between refreshes.
- `label = _week_label(start, days[-1])`; `today = now.date()` (caller compares per-day).
- Empty week → full 7-day × 24-hour skeleton with empty buckets (never a sparse/degenerate grid).

## 4. Fail-safe requirements (folded from hardening)

### 4.1 Lifecycle (P2 + P3 — MUST)
- **L1 (H-P2-1 / H-P3-7):** the generalized pop-out entry is **isinstance-based, never reads
  `note_id` on a non-note**. Reuse fast-paths: an already-open `NoteEditorPanel` with the same id →
  raise/activate; an already-open `CalendarWeekPanel` on a calendar request → raise/activate
  (preserves week + scroll state, no rebuild). **Any cross-kind switch** (note↔calendar, or a
  different note) resolves the current panel via `handle_close()` **first** (so a dirty note's
  Save/Discard/Cancel runs), then `_close_expanded()`, then builds the new one.
- **L2:** `CalendarWeekPanel.handle_close() -> True` (read-only; nothing to lose). *Comment in code:
  must be revisited in slice (b) when drag-scheduling adds an in-flight write.*

### 4.2 Refresh / staleness (P2 — MUST; the pop-out is a detached window `switch_tab` never re-enters)
- **R1 (H-P2-2):** `CalendarWeekPanel.on_panel_activated() -> self.refresh()` — re-reads
  `collect_events` + `build_timegrid` whenever the pop-out window is re-activated (the detached-window
  analogue of "refresh on tab re-entry"; covers every mutation source: inline due-edit, done-grace,
  soft-delete, reorder, capture). `refresh()` is idempotent/cheap.
- **R2 (H-P2-3):** in `shell._commit_capture`'s todo branch, after `todos_view.refresh()`, add a
  type-guarded `if isinstance(self._expanded._content, CalendarWeekPanel): self._expanded._content.refresh()`
  (voice capture commits without reactivating the window, so R1 alone misses it).
- **R3 (H-P2-4):** in `shell.set_window_mode`'s MODE_FULL re-show block, after `self._expanded.show()`,
  `if hasattr(content, "refresh"): content.refresh()` — the `hasattr` guard re-renders the calendar
  but is a safe no-op for `NoteEditorPanel` (which has none and must not reload while dirty). Don't
  rely on activation here: MODE_FULL re-show calls `show()/raise_()` but not `activateWindow()`, so
  `ActivationChange` isn't reliably delivered.

### 4.3 Correctness guardrails (P3 + verified-as-tests — land WITH the new function)
- **C1:** week-membership filter (C2 of §3.1) — a test asserts an adjacent-week event is NOT placed.
- **C2:** midnight split via `has_time`, not a re-derivation — a `00:00` event → all-day strip; a
  `00:30` event → the `00:00` hour bucket (timed). Reuses the existing `_has_time` micro-second test.
- **C3:** strict all-day vs timed partition (no event both in the strip and a cell).
- **C4 (H-P3-1):** deterministic per-cell order (test: two same-hour timed events + two same-day
  all-day events come back time/title-ordered regardless of store input order).
- **C5:** empty week → full skeleton (test: `build_timegrid([], anchor)` yields 7 days × 24 hours,
  all empty).
- **C6 (H-P3-2):** cross-**year** week label — keep `_week_label` as-is (matches the existing tab,
  no regression) and **pin it with a test** (`Dec 28 2026 … Jan 3 2027` → `"Dec 28 - Jan 3"`),
  documenting the year-less label as intentional.

## 5. Files
**New:** `serenity/ui/calendar_week_panel.py`, `tests/test_ui_calendar_week.py`.
**Edit:** `serenity/core/calview.py` (`build_timegrid` + `TimeGrid`), `tests/test_calview.py`
(build_timegrid tests C1–C6), `serenity/ui/calendar_view.py` (⤢ entry), `serenity/ui/shell.py`
(generalized single-instance + `_open_calendar_expanded` + R2/R3 refresh hooks),
`tests/test_ui_expanded.py` (shell calendar-pop-out + cross-kind lifecycle tests).

## 6. Testing
- **Headless `tests/test_calview.py`:** `build_timegrid` C1–C6 (membership, midnight split, partition,
  deterministic order, empty skeleton, cross-year label).
- **UI smoke `tests/test_ui_calendar_week.py` (offscreen):** panel builds + docks-left; events land in
  the right (day,hour) cells + all-day strip; week nav prev/next/today; event click emits `open_todo`;
  right list shows active todos; `refresh()` re-reads the store; `on_panel_activated()` refreshes;
  `handle_close()` is True; viewport scrolled to ~08:00.
- **UI smoke `tests/test_ui_expanded.py` (offscreen):** Calendar ⤢ opens a pop-out; **opening the
  calendar over a DIRTY note routes through the note's `handle_close()` first** (L1); re-opening the
  calendar reuses (no rebuild, raise/activate) (L1); a todo mutation + re-activation refreshes the
  grid (R1); mode-switch mini→full refreshes (R3); opening a note over the calendar works (no
  `note_id` AttributeError).
- Whole suite stays green headless; `gitnexus detect_changes` before commit.

## 7. Notes / forward
- `handle_close() -> True` is correct only because (a) is read-only; **slice (b) must revisit it**
  when drag-scheduling introduces an in-flight write.
- `build_timegrid` deliberately reuses `_week_start`/`_week_label`/`CalEvent.has_time`/the `_day_cell`
  sort key — no duplicated calendar logic.
