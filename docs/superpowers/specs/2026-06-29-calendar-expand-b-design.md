# Calendar-expand — slice (b): drag-schedule + create — design spec (hardened)

_Status: APPROVED design + flow-hardening folded in. Date: 2026-06-29._
_Slice (b) of 3 (adds the WRITE path to slice (a)'s read-only week grid). (c) = ICS — separate spec._
_Hardening: 4-slice pass, 32 candidates → 14 confirmed (0 P1, 8 P2, 6 P3)._

---

## 1. Summary & scope
Add writing to the slice-(a) `CalendarWeekPanel`: **drag a todo onto a slot to reschedule it**, and
**click an empty slot to create one**. All writes are atomic (a drop commits immediately; a create
goes through a modal dialog), so the panel stays free of transient edit state.

**In scope:** drag sources (right-list rows + grid event-blocks) → drop targets (hour cells +
all-day strip); `QuickTodoDialog.default_due`; a `wrote` signal + shell cross-surface refresh.
**Out of scope:** ICS (c); month view; multi-select drag; resizing/duration (todos are instants).

## 2. Locked decisions
- Drop on hour cell (D, H) → `todo.due = D@H:<original minute>` (**keep the minute**: 14:30→09:30; a
  no-time/00:00 todo→09:00). Drop on the all-day strip for D → `D@00:00` (all-day).
- Create on an empty cell → `QuickTodoDialog` pre-filled with `default_due` = that slot.
- `handle_close()` stays **True** (atomic writes; the slice-(a) "revisit in (b)" note is hereby resolved).

## 3. Architecture
- `serenity/ui/calendar_week_panel.py` *(edit)* — drag sources, drop targets, slot-click create,
  `wrote = Signal()`. Reuses the `QDrag`+`QMimeData.setText(id)` body from `TodoCard._begin_drag`.
- `serenity/ui/modals.py` *(edit)* — `QuickTodoDialog(..., default_due=None)` + a save-failure guard.
- `serenity/ui/shell.py` *(edit)* — wire `cal.wrote → _on_calendar_wrote` (fan-out refresh).
- Reuses `TodoStore.add/update/get`, `collect_events(show_done=False)`, the imperative `.refresh()`.

## 4. Fail-safe requirements (folded from hardening)

### 4.1 P2 — MUST
- **H1 — drop re-resolves the id, skips stale.** `dropEvent` reads `mime_id = e.mimeData().text()`,
  then `t = store.get(mime_id)`. **If `t is None or t.done or t.deleted` → accept the event, `self.refresh()`,
  return WITHOUT writing.** Never mutate a drag-start-captured object. (The `done/deleted` guard is
  load-bearing — `complete()`/`soft_delete()` keep the todo in `_todos`, so a plain None-check (the
  `_on_reorder` template) would still write a new due onto a filtered-out todo → silent vanish.) Only
  on a live todo: set `due`, `store.update(t)`, refresh, emit `wrote`.
- **H2 — `QuickTodoDialog._save` survives a write OSError.** Wrap `todo_store.add(todo)` in
  `try/except OSError`; on failure `self.todo_store._todos.remove(todo)` (undo the in-memory append —
  `add` appends *before* `save()`, so a later successful write would otherwise flush the phantom),
  show an inline error QLabel, and keep the modal open (don't `accept()`/`added.emit`). (This is the
  catalogued capture Flow-6/7 fix applied to the new caller.)
- **H3 — cross-surface refresh via one `wrote` signal.** `CalendarWeekPanel.wrote = Signal()` is
  emitted at the end of **both** write paths (after `store.update`+`self.refresh()` on drop, and after
  the create's `store.add`+`self.refresh()`). `shell._open_calendar_expanded` connects
  `cal.wrote → _on_calendar_wrote`, which calls `self.calendar_view.refresh()` +
  `self.todos_view.refresh()` — **no `switch_tab`** (focus stays on the pop-out). The create path must
  NOT reuse `_on_quick_todo` (it `switch_tab("todos")`s and refreshes neither calendar surface).
- **H4 — create precedence: parse the `when` field only.** When `default_due` is set,
  `QuickTodoDialog._save` parses the **`when` field alone** (not `title + when`):
  `when_cap = parse_capture(when) if when.strip() else None`; `due = when_cap.date if (when_cap and
  when_cap.date) else default_due`. A typed "when" wins; a blank "when" → the clicked slot; a date
  token in the **title** never hijacks placement. (Standalone Quick-todo, `default_due=None`, keeps
  its current combined-parse behaviour.)

### 4.2 P3 — SHOULD (cheap; include)
- **H5 — drop builds a clean `due`.** Hour-cell: `t.due.replace(year=D.y, month=D.m, day=D.d, hour=H,
  second=0, microsecond=0)` (keep minute). All-day strip: `datetime(D.y, D.m, D.d)` **exactly** (not
  `.replace(hour=0,minute=0)`, which can leak inherited seconds → `_has_time` reports timed → the block
  lands in the off-screen 00:00 cell instead of the strip).
- **H6 — right-list rows are drag sources ONLY.** Add a press→`QDrag` gesture to the existing bespoke
  `_list_row` `QFrame`; do **not** reuse the whole `TodoCard` and do **not** `setAcceptDrops` on rows
  or the list host (so a list→list mis-drop is a clean no-op, never a stray `reorder`).
- **H7 — event-block: disambiguate click vs drag.** The block keeps slice-(a)'s `clicked → open_todo`
  (deep-link). Start the `QDrag` only after the cursor moves ≥ `QApplication.startDragDistance()` from
  the press (record press pos in `mousePressEvent`, start in `mouseMoveEvent`, set a `_dragging` flag;
  gate the emit on `not self._dragging`). Do **not** wire `QDrag` to `pressed` (its blocking `exec`
  swallows the release → the click-through deep-link would die).
- **H8 — created out-of-week todo stays visible.** If a create's resolved `due` falls outside the
  shown week, set the panel anchor to that todo's week before refreshing, so the new event is visible
  (a correct write otherwise looks like it failed → duplicate re-create). *(Chosen over a mascot
  notice: no new voice/infra; drops never trigger this — you can only drop onto a visible cell.)*

## 5. Files
**Edit:** `serenity/ui/calendar_week_panel.py` (H1/H3/H5/H6/H7/H8 + `wrote`), `serenity/ui/modals.py`
(H2/H4 + `default_due`), `serenity/ui/shell.py` (H3 wiring). **Tests:** `tests/test_ui_calendar_week.py`,
`tests/test_modals.py` (or wherever QuickTodoDialog is tested), `tests/test_ui_expanded.py`.

## 6. Testing
- **Drop (`test_ui_calendar_week.py`):** live todo → due set to D@H:minute (H5 keep-minute + sec/micro
  zeroed); all-day-strip drop → exact midnight, renders in the strip; **drop of a done/deleted/purged
  id → no write, grid self-heals** (H1); drop on the all-day strip vs hour cell.
- **Create:** slot-click opens `QuickTodoDialog` with `default_due`; blank "when" → slot; typed "when"
  wins; **title with a date token + blank when → slot wins, title does not set due** (H4); out-of-week
  create → anchor moves so the event is visible (H8).
- **QuickTodoDialog (`test_modals.py`):** `add` OSError → phantom removed from `_todos`, modal stays
  open with the error, `added` not emitted (H2); `default_due=None` path unchanged (regression).
- **Cross-surface (`test_ui_expanded.py`):** a drop emits `wrote` → shell refreshes calendar_view +
  todos_view, **no `switch_tab`** (H3); a slot-create likewise; both via the panel-owned handler.
- **Gestures:** event-block click still emits `open_todo`; a past-threshold move starts a drag, not a
  click (H7); right-list row is a drag source and never a drop target (H6).
- Full suite green headless; re-analyze + `detect_changes` once before push.

## 7. Notes / forward
- Dropped-but-accepted (no action, matches existing semantics): mutate-in-memory-then-`update` (the
  shipped Todos convention + atomic write); recurring-due re-anchor (accepted model behaviour);
  header/gutter drop no-op (OS no-drop cursor); same-cell no-op write; drag-reentrancy (the panel owns
  no timers, unlike `TodosView`).
- Slice (c) ICS is next; Phase A (state registry) after the calendar work.
