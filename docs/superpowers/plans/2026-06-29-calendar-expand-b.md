# Calendar-expand slice (b) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** Add the write path to the slice-(a) week grid — drag a todo onto a slot to reschedule it, click an empty slot to create one — fail-safe per the hardened spec.

**Architecture:** Drag sources (right-list rows + grid event-blocks) and drop targets (hour cells + all-day strip) on `CalendarWeekPanel`; `QuickTodoDialog` gains `default_due` + a save guard; a single `wrote` signal fans cross-surface refresh out through the shell. Reuses the `QDrag` body from `TodoCard._begin_drag`, `TodoStore.add/update/get`, the imperative `.refresh()`.

**Spec:** `docs/superpowers/specs/2026-06-29-calendar-expand-b-design.md` (IDs H1–H8).

## Global Constraints
- Python 3.12 + PySide6; no new dependency. Headless: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (suite currently 912/5, stays green every task). core/ untouched (this slice is UI-only).
- Reuse: `TodoCard._begin_drag` QDrag/QMimeData.setText body; `QuickTodoDialog(todo_store, settings, parent)` + `added`; `TodoStore.add/update/get` (+ `_todos` for the H2 phantom-undo); `parse_capture`; `collect_events(show_done=False)`; the `.refresh()` pattern; `theme.COLORS`.
- Atomic writes only; `CalendarWeekPanel.handle_close()` stays `True`. Surgical edits.

---

### Task 1: `QuickTodoDialog` — `default_due` + when-only parse + save guard

**Files:** Modify `serenity/ui/modals.py`; Test `tests/test_modals.py` (create if absent; else the modals test file).

**Interfaces:**
- Produces: `QuickTodoDialog(todo_store, settings, parent=None, default_due: datetime | None = None)`.
  - **H4:** in `_save`, when `default_due` is set, parse the **`when` field only**:
    `when_cap = parse_capture(when) if when.strip() else None`;
    `due = when_cap.date if (when_cap and when_cap.date) else default_due`;
    `recurring = when_cap.recurring if when_cap else None`; `category/tags` still from the title parse.
    When `default_due is None`, keep the existing combined `title + when` parse (unchanged).
  - **H2:** wrap `self.todo_store.add(todo)` in `try/except OSError`; on failure
    `self.todo_store._todos.remove(todo)`, set a hidden `self._error` QLabel visible, `return`
    (no `settings.save`/`added.emit`/`accept`).

- [ ] **Step 1: failing tests** — (a) `default_due=D@09:00`, when blank, title `"Call Tom Monday"` → `todo.due == D@09:00` (title doesn't bleed, H4); (b) `default_due=D@09:00`, when `"friday 3pm"` → due == parsed friday (typed wins); (c) `default_due=None` combined-parse unchanged (regression); (d) monkeypatch `todo_store.add` to raise OSError → `added` not emitted, `len(todo_store._todos)` unchanged (phantom removed), error label visible (H2). Use a real `TodoStore(tmp_path)` + `Settings`.
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement** the ctor param, the when-only branch, the guard + `self._error` QLabel.
- [ ] **Step 4: run, verify pass; full suite green.**
- [ ] **Step 5: commit** — `feat(modals): QuickTodoDialog default_due + when-only parse + save guard`.

---

### Task 2: `CalendarWeekPanel` — drag sources, drop targets, reschedule write

**Files:** Modify `serenity/ui/calendar_week_panel.py`; Test `tests/test_ui_calendar_week.py`.

**Interfaces:**
- Produces: `wrote = Signal()`; drop-capable hour cells + all-day-strip cells; drag-source rows + blocks.
  - **drop targets:** in `_hour_cell` / the all-day cell wrap, `setAcceptDrops(True)` and install
    `dragEnterEvent` (accept if `e.mimeData().hasText()`) + `dropEvent`. Since cells are rebuilt each
    refresh, wire drops via small `QFrame` subclasses or per-cell event handling that carries
    `(day, hour)` / `(day, all_day=True)`.
  - **dropEvent (H1/H5):** `mid = e.mimeData().text(); t = store.get(mid)`;
    `if t is None or t.done or t.deleted: e.acceptProposedAction(); self.refresh(); return`.
    Else hour-cell: `t.due = t.due.replace(year=D.y, month=D.m, day=D.d, hour=H, second=0, microsecond=0)`;
    all-day: `t.due = datetime(D.y, D.m, D.d)`. `store.update(t); self.refresh(); self.wrote.emit();
    e.acceptProposedAction()`.
  - **drag sources:** right-list `_list_row` gets a press→`QDrag` (mime=`t.id`), **no setAcceptDrops** (H6);
    event-blocks get a movement-threshold drag (record press pos; start `QDrag` in `mouseMoveEvent`
    once `>= QApplication.startDragDistance()`, set `_dragging`; keep `clicked → open_todo`, gated on
    `not self._dragging`) (H7).

- [ ] **Step 1: failing tests** — live todo dropped on hour cell → due=D@H:minute, sec/micro 0, `wrote`
  emitted; all-day-strip drop → exact midnight, renders in strip; **done/deleted/purged id drop → no
  write (store unchanged), refresh ran** (H1); right-list row exposes a drag start and is not a drop
  target (H6); event-block past-threshold move starts a drag while a plain click still emits `open_todo`
  (H7). (Drive drops by constructing a `QDropEvent`/`QMimeData` with the id, or call the dropEvent
  handler directly with a fake event carrying `mimeData().text()`.)
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement.** Keep the QDrag body identical to `TodoCard._begin_drag`.
- [ ] **Step 4: run, verify pass; full suite green.**
- [ ] **Step 5: commit** — `feat(ui): CalendarWeekPanel drag-to-reschedule (drop targets + drag sources + wrote)`.

---

### Task 3: `CalendarWeekPanel` — create-on-slot

**Files:** Modify `serenity/ui/calendar_week_panel.py`; Test `tests/test_ui_calendar_week.py`.

**Interfaces:**
- Produces: empty-cell click → `QuickTodoDialog(self.todo_store, self._settings, default_due=slot, parent=self)`
  where slot = `datetime(D.y,D.m,D.d,H)` (hour cell) or `datetime(D.y,D.m,D.d)` (all-day strip);
  connect `dlg.added → _on_created`. `_on_created(todo)`: **H8** if the todo's `due` week ≠ the shown
  week, set `self._anchor` to that todo's Monday; then `self.refresh(); self.wrote.emit()`.
  - Panel needs `settings` for the dialog — add it as an **optional** ctor param
    `CalendarWeekPanel(todo_store, settings=None, parent=None)` so the existing slice-(a)
    `CalendarWeekPanel(store)` calls and tests keep working unchanged; the shell passes
    `self.settings`. If `settings is None`, the create path is simply inert (no crash). Empty-cell
    detection: a click on a cell with no event block.

- [ ] **Step 1: failing tests** — clicking an empty cell opens a `QuickTodoDialog` with `default_due`
  == that slot (monkeypatch `QuickTodoDialog` to capture the kwarg / not exec); `_on_created` with a
  todo whose due is in the shown week → grid shows it + `wrote` emitted; `_on_created` with a due in a
  **different** week → `self._anchor` moved to that week and the event is rendered (H8).
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement** (add the `settings` ctor param; update the slice-(a) construction sites —
  the shell `_open_calendar_expanded` — to pass `self.settings`).
- [ ] **Step 4: run, verify pass; full suite green.**
- [ ] **Step 5: commit** — `feat(ui): CalendarWeekPanel create-on-slot (QuickTodoDialog default_due + H8)`.

---

### Task 4: Shell — cross-surface refresh on `wrote`

**Files:** Modify `serenity/ui/shell.py`; Test `tests/test_ui_expanded.py`.

**Interfaces:**
- Produces: in `_open_calendar_expanded`, pass `self.settings` to `CalendarWeekPanel` and add
  `cal.wrote.connect(self._on_calendar_wrote)`; new slot **H3**:
  `def _on_calendar_wrote(self): self.calendar_view.refresh(); self.todos_view.refresh()` — **no
  `switch_tab`** (focus stays on the pop-out).

- [ ] **Step 1: failing tests** — open the calendar pop-out; emit `panel.wrote` (or simulate a drop) →
  assert `calendar_view.refresh` and `todos_view.refresh` both ran and `switch_tab` was NOT called
  (spy); a slot-create likewise fans out (H3).
- [ ] **Step 2: run, verify fail.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run, verify pass; FULL suite green; re-analyze + `gitnexus detect_changes`.**
- [ ] **Step 5: commit** — `feat(ui): wire Calendar-expand writes to cross-surface refresh (wrote signal)`.

## Self-Review
- **Coverage:** H1/H5 → Task 2; H2/H4 → Task 1; H3 → Tasks 2-4 (signal emitted in 2/3, wired in 4);
  H6/H7 → Task 2; H8 → Task 3. All mapped.
- **Types:** `QuickTodoDialog(todo_store, settings, parent=None, default_due=None)`;
  `CalendarWeekPanel(todo_store, settings=None, parent=None)` + `wrote: Signal()`; `_on_calendar_wrote()`.
  `settings` is OPTIONAL (default None) so slice-(a)'s `CalendarWeekPanel(store)` calls/tests are
  unchanged; only the create path uses it, and is inert when None. The shell passes `self.settings`.
