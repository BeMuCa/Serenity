# Calendar-expand slice (a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** A read-only Teams-style expanded week time-grid (in the shared `ExpandedPanel`) with an inert active-todo list, opened from the Calendar tab.

**Architecture:** Qt-free `build_timegrid` in `core/calview.py` (headless-tested) + a thin `CalendarWeekPanel` that renders it; the shell's single-instance pop-out generalizes (isinstance-based) to host either a note or the calendar. Mirrors the `calview`/`calendar_view` split and reuses the `ExpandedPanel`/`handle_close`/`on_panel_activated` seams from Notes-expand.

**Tech Stack:** Python 3.12, PySide6, stdlib `datetime`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-06-29-calendar-expand-a-design.md` (IDs C1–C6 / L1–L2 / R1–R3).

## Global Constraints
- Python 3.12 + PySide6; no new dependency. New `.py` gets the project header block (Created: 2026-06-29).
- `core/` Qt-free. Headless: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (plain `python` not on PATH). Suite (currently 882 pass / 5 skip) stays green after every task.
- **Read-only:** no writes to `TodoStore`. Reuse: `calview.collect_events`/`_has_time`/`_week_start`/`_week_label`/`_day_cell` sort key, `ExpandedPanel(title, content, anchor)` + its `handle_close()`/`on_panel_activated` protocol, the shell single-instance `self._expanded` + `_close_expanded`/`_request_close_expanded`, `_open_calendar_todo` deep-link, the `theme.COLORS`, the imperative-`.refresh()` pattern.
- Surgical; match existing style. Don't read `note_id` on a non-note (L1).

---

### Task 1: `build_timegrid` + `TimeGrid` (Qt-free core)

**Files:** Modify `serenity/core/calview.py`; Test `tests/test_calview.py`.

**Interfaces:**
- Produces: `@dataclass TimeGrid{days:list[date], hours:list[int], all_day:dict[date,list[CalEvent]], cells:dict[tuple[date,int],list[CalEvent]], label:str, today:date|None}`; `build_timegrid(events, anchor, now=None) -> TimeGrid` per spec §3.1.
- Consumes: `_week_start`, `_week_label`, `CalEvent.has_time`, the `(not e.has_time, e.when, e.title)` sort key.

- [ ] **Step 1: failing tests** in `tests/test_calview.py` (class `TestBuildTimegrid`):
```python
def test_places_timed_event_in_day_hour_cell(self):
    evs = collect_events([Todo(title="Standup", due=datetime(2026,6,30,9,0))], now=NOW)
    g = build_timegrid(evs, date(2026,7,1), now=NOW)   # week Mon 2026-06-29..Sun 07-05
    assert [e.title for e in g.cells[(date(2026,6,30),9)]] == ["Standup"]
def test_midnight_goes_to_all_day_but_0030_is_timed(self):   # C2
    evs = collect_events([Todo(title="AD", due=datetime(2026,6,30,0,0)),
                          Todo(title="Early", due=datetime(2026,6,30,0,30))], now=NOW)
    g = build_timegrid(evs, date(2026,6,30), now=NOW)
    assert [e.title for e in g.all_day[date(2026,6,30)]] == ["AD"]
    assert [e.title for e in g.cells[(date(2026,6,30),0)]] == ["Early"]
def test_adjacent_week_event_not_placed(self):              # C1
    evs = collect_events([Todo(title="NextWk", due=datetime(2026,7,8,9,0))], now=NOW)
    g = build_timegrid(evs, date(2026,7,1), now=NOW)
    assert all("NextWk" not in [e.title for e in v] for v in g.cells.values())
def test_deterministic_cell_order(self):                    # C4
    evs = collect_events([Todo(title="B", due=datetime(2026,6,30,9,0)),
                          Todo(title="A", due=datetime(2026,6,30,9,0))], now=NOW)
    g = build_timegrid(evs, date(2026,6,30), now=NOW)
    assert [e.title for e in g.cells[(date(2026,6,30),9)]] == ["A","B"]
def test_empty_week_full_skeleton(self):                    # C5
    g = build_timegrid([], date(2026,6,30), now=NOW)
    assert len(g.days)==7 and g.hours==list(range(24))
def test_cross_year_label(self):                            # C6
    g = build_timegrid([], date(2026,12,30), now=NOW)
    assert g.label == "Dec 28 - Jan 3"
```
- [ ] **Step 2: run, verify fail.** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_calview.py -q`
- [ ] **Step 3: implement** `TimeGrid` + `build_timegrid`: 7-day list from `_week_start`; filter `e.when.date() in days`; per day sort by the key, split `not has_time`→`all_day[day]` else `cells[(day,e.when.hour)]`; `hours=list(range(24))`; `label=_week_label(start, days[-1])`; `today=(now or datetime.now()).date()`.
- [ ] **Step 4: run, verify pass; full suite green.**
- [ ] **Step 5: commit** — `feat(calview): build_timegrid (Qt-free week day×hour layout)`.

---

### Task 2: `CalendarWeekPanel`

**Files:** Create `serenity/ui/calendar_week_panel.py`; Test `tests/test_ui_calendar_week.py`.

**Interfaces:**
- Consumes: `build_timegrid`, `collect_events`, `TodoStore`, `theme.COLORS`.
- Produces: `class CalendarWeekPanel(QWidget)` — `open_todo = Signal(str)`; `refresh()` (re-read `collect_events(show_done=False)` + `build_timegrid` for the current `_anchor`, repaint grid + all-day strip + right active-todo list); `on_panel_activated()` → `refresh()` (R1); `handle_close() -> bool` → `True` (L2, with the "revisit in slice (b)" comment); week nav `_go_prev/_go_next/_go_today` (±7 days / today); a `QScrollArea` over the hour grid, scrolled to ~08:00 on first show; right list = `store.all()` filtered open & not deleted, ordered like the Todos tab.

- [ ] **Step 1: failing smoke tests** (offscreen; qapp fixture like `test_ui_calendar.py`): builds for a store with a dated todo; the event renders in its (day,hour) cell; an all-day todo lands in the strip; week nav shifts the anchor ±7 / today; clicking an event emits `open_todo(id)`; the right list contains active todos and omits done/trashed; `refresh()` picks up a newly-added todo; `on_panel_activated()` calls `refresh()`; `handle_close()` is True.
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement** (header block; reuse `_WEEKDAYS`/`COLORS`; `_clear` layout helper like `calendar_view`; build hour rows 0–23 with an hour-label column + 7 day columns in a `QGridLayout` inside a `QScrollArea`; all-day strip pinned above; event blocks show `HH:MM title`, meeting category accent; today column accent; `QScrollBar.setValue` to the 08:00 row on first `showEvent`).
- [ ] **Step 4: run, verify pass; full suite green.**
- [ ] **Step 5: commit** — `feat(ui): CalendarWeekPanel (read-only week time-grid + active-todo list)`.

---

### Task 3: Calendar tab expand entry

**Files:** Modify `serenity/ui/calendar_view.py`; Test `tests/test_ui_calendar.py`.

**Interfaces:**
- Produces: an expand (⤢) `QPushButton` in the Calendar tab header, emitting `expand_requested = Signal()` (the shell opens the pop-out for the current week). Existing week/month tab behaviour untouched.

- [ ] **Step 1: failing test:** `CalendarView` exposes `expand_btn`; clicking it emits `expand_requested`.
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement** — add the button beside the existing header controls (`tab` objectName, matching style); declare + emit the signal.
- [ ] **Step 4: run, verify pass.**
- [ ] **Step 5: commit** — `feat(ui): Calendar tab expand-to-pop-out button`.

---

### Task 4: Shell — generalized single-instance + refresh hooks

**Files:** Modify `serenity/ui/shell.py`; Test `tests/test_ui_expanded.py`.

**Interfaces:**
- Consumes: `CalendarView.expand_requested`, `CalendarWeekPanel`, `ExpandedPanel`, the existing `_expanded`/`_close_expanded`/`_request_close_expanded`/`_open_calendar_todo`.
- Produces:
  - **L1:** generalize the single-instance preamble to be **isinstance-based** — a helper used by both note and calendar opens: if `self._expanded` is open, `NoteEditorPanel` same-id → raise/activate; `CalendarWeekPanel` on a calendar request → raise/activate (no rebuild); any cross-kind/different → `content.handle_close()` (return if False) then `_close_expanded()`. **Never read `note_id` on a non-note.**
  - `_open_calendar_expanded()`: build `ExpandedPanel(CalendarWeekPanel(todo_store), anchor=self)`, wire `panel.open_todo → _open_calendar_todo` and the panel's close routing; connect `calendar_view.expand_requested → _open_calendar_expanded`.
  - **R2:** in `_commit_capture`'s todo branch, after `todos_view.refresh()`, `if isinstance(self._expanded._content, CalendarWeekPanel): self._expanded._content.refresh()`.
  - **R3:** in `set_window_mode` MODE_FULL re-show, after `self._expanded.show()`, `if hasattr(content, "refresh"): content.refresh()`.

- [ ] **Step 1: failing tests** (offscreen, `TestShellExpandWiring` style, isolate config/vault):
  expand opens a calendar pop-out (`_content` is a `CalendarWeekPanel`); re-open reuses (same panel object, no rebuild) (L1); **opening the calendar while a dirty note pop-out is open routes through the note's `handle_close()` first** (monkeypatch the note's `handle_close` to record the call) (L1); opening a note while the calendar is open does not raise (no `note_id` read on the calendar) (L1); a `_commit_capture` with a calendar pop-out open calls its `refresh()` (R2); `set_window_mode(MODE_FULL)` re-show calls the calendar's `refresh()` (R3).
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement** — refactor the single-instance preamble into the isinstance-based helper (note path keeps its same-id fast-path inside the `NoteEditorPanel` branch); add `_open_calendar_expanded`; add the two guarded refresh hooks.
- [ ] **Step 4: run, verify pass; FULL suite green; `npx gitnexus analyze` then `gitnexus detect_changes`.**
- [ ] **Step 5: commit** — `feat(ui): wire Calendar-expand into the shell (generalized single-instance + refresh hooks)`.

## Self-Review
- **Spec coverage:** C1–C6 → Task 1; L1/L2 → Tasks 4/2; R1 → Task 2; R2/R3 → Task 4; panel render/nav/click/right-list → Task 2; entry → Task 3. All mapped.
- **Types:** `build_timegrid(events, anchor, now=None) -> TimeGrid`; `CalendarWeekPanel(todo_store)` with `open_todo:Signal(str)`/`refresh()`/`on_panel_activated()`/`handle_close()->bool`; `CalendarView.expand_requested:Signal()` — consistent across tasks.
