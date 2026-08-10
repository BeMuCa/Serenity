# Phase C — state_tag + context + Two-Axis Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stamp every new Note/Todo with the creation-time activity state (registry key) + global context, and filter the item surfaces by both axes (context toggle + a deselectable state chip).

**Architecture:** Pure additions in `core/` (model fields, `key_for_label`, `visible` predicate), a single `stamp()` closure built by `Shell` and threaded to every creation funnel, a shell-synced state chip in both list views, and a context post-filter on every todo/note-showing surface (lists, calendar, graph, mini, AI candidate lists). Spec: `docs/superpowers/specs/2026-07-03-phase-c-state-tag-design.md` (requirements R1–R16 referenced below).

**Tech Stack:** Python 3.12, PySide6 (offscreen-testable), PyYAML, pytest.

## Global Constraints

- Suite gate after EVERY task: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → all pass (plain `python` is not on PATH).
- Every NEW .py file starts with the project header comment block (Author/Created/Purpose/Role/Functions).
- NEVER touch the SQLite index schema/`_index_note` (spec §3), never re-stamp on edit, chip state never persisted.
- `context` values are exactly `"business"`/`"private"`; anything else coerces to `None` at deserialize.
- Match existing style; conventional commit messages; commit after each task.

---

### Task 1: Model fields + tolerant round-trip (R6 data half)

**Files:**
- Modify: `serenity/core/models.py` (Todo ~62-145, Note ~148-188)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Todo.state_tag: Optional[str]`, `Todo.context: Optional[str]`, same on `Note`; module helper `_clean_context(v)`, `_clean_state_tag(v)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models.py`)

```python
def test_todo_state_tag_context_roundtrip():
    t = Todo(title="x", state_tag="working", context="business")
    d = t.to_dict()
    assert d["state_tag"] == "working" and d["context"] == "business"
    t2 = Todo.from_dict(d)
    assert t2.state_tag == "working" and t2.context == "business"


def test_todo_legacy_dict_defaults_none():
    t = Todo.from_dict({"id": "a", "title": "old"})   # pre-Phase-C dict: keys absent
    assert t.state_tag is None and t.context is None


def test_todo_invalid_context_and_state_coerce_none():
    t = Todo.from_dict({"id": "a", "context": "banana", "state_tag": ["x"]})
    assert t.context is None and t.state_tag is None
    t = Todo.from_dict({"id": "a", "context": 123, "state_tag": ""})
    assert t.context is None and t.state_tag is None


def test_note_state_tag_context_roundtrip_and_legacy():
    n = Note(title="x", state_tag="working", context="private")
    fm = n.to_frontmatter()
    assert fm["state_tag"] == "working" and fm["context"] == "private"
    n2 = Note.from_frontmatter(fm, "body", "/tmp/x.md")
    assert n2.state_tag == "working" and n2.context == "private"
    old = Note.from_frontmatter({"id": "a", "title": "old"}, "b", "/tmp/y.md")
    assert old.state_tag is None and old.context is None


def test_note_invalid_context_coerces_none():
    n = Note.from_frontmatter({"id": "a", "context": "Business"}, "b", "/tmp/y.md")
    assert n.context is None   # wrong case = invalid; matches BOTH contexts downstream
```

- [ ] **Step 2: Run to verify failure** — `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_models.py -q` → FAIL (unexpected keyword `state_tag`).

- [ ] **Step 3: Implement.** In `models.py` add after `_parse_iso`:

```python
def _clean_context(v) -> Optional[str]:
    return v if v in ("business", "private") else None


def _clean_state_tag(v) -> Optional[str]:
    return v if isinstance(v, str) and v else None
```

Add fields to `Todo` (after `ics_uid`): `state_tag: Optional[str] = None` and `context: Optional[str] = None`  # creation-time stamp: registry key / global context (Phase C). Add to `Todo.to_dict()` after the `"ics_uid"` entry: `"state_tag": self.state_tag, "context": self.context,`. Add to `Todo.from_dict()` after `ics_uid=...`: `state_tag=_clean_state_tag(d.get("state_tag")), context=_clean_context(d.get("context")),`. Mirror all three edits on `Note` (fields after `body`; `to_frontmatter` after `"updated"`; `from_frontmatter` after `updated=...`). Update the header-comment Models list line for Todo/Note.

- [ ] **Step 4: Run** the file then the full suite → PASS.
- [ ] **Step 5: Commit** `feat(models): optional state_tag+context on Todo/Note with tolerant coercion (Phase C R6)`

---

### Task 2: `key_for_label` + `visible` predicate (R2, R6, R9)

**Files:**
- Modify: `serenity/core/states.py`
- Test: `tests/test_states.py`

**Interfaces:**
- Produces: `states.key_for_label(states, label) -> Optional[str]`; `states.visible(item, context, state_key=None) -> bool` (item = any object with `.context`/`.state_tag`).

- [ ] **Step 1: Failing tests** (append to `tests/test_states.py`)

```python
from serenity.core.states import ActivityState, default_states, key_for_label, visible


def test_key_for_label_maps_and_misses():
    assert key_for_label(default_states(), "Working") == "working"
    assert key_for_label(default_states(), "Nope") is None
    assert key_for_label(default_states(), "Idle") == "idle"


def test_key_for_label_duplicate_labels_first_wins():
    sts = [ActivityState("a1", "Same"), ActivityState("a2", "Same")]
    assert key_for_label(sts, "Same") == "a1"


class _Item:
    def __init__(self, context=None, state_tag=None):
        self.context, self.state_tag = context, state_tag


def test_visible_context_axis():
    assert visible(_Item(context="business"), "business")
    assert not visible(_Item(context="private"), "business")
    assert visible(_Item(context=None), "business") and visible(_Item(context=None), "private")
    # invalid stored values match BOTH (belt+braces on top of deserialize coercion)
    assert visible(_Item(context="work"), "business") and visible(_Item(context=123), "private")


def test_visible_state_axis():
    assert visible(_Item(context="business", state_tag="working"), "business", "working")
    assert not visible(_Item(context="business", state_tag="coding"), "business", "working")
    assert not visible(_Item(context="business", state_tag=None), "business", "working")
    # state_key=None means the axis is OFF, never "match None"
    assert visible(_Item(context="business", state_tag=None), "business", None)
```

- [ ] **Step 2: Run** → FAIL (ImportError).
- [ ] **Step 3: Implement** in `states.py` (append; update header Functions list):

```python
def key_for_label(states: list[ActivityState], label: str) -> Optional[str]:
    """The FIRST activity row matching `label` (registry order), else None (R9)."""
    for s in activities(states):
        if s.label == label:
            return s.key
    return None


def visible(item, context: str, state_key: Optional[str] = None) -> bool:
    """Two-axis filter predicate (R2/R6). state_key=None == state axis OFF."""
    item_ctx = getattr(item, "context", None)
    if item_ctx not in ("business", "private"):
        item_ctx = None                     # invalid/absent stamp matches BOTH contexts
    if item_ctx is not None and item_ctx != context:
        return False
    return state_key is None or item.state_tag == state_key
```

- [ ] **Step 4: Run** file + full suite → PASS.
- [ ] **Step 5: Commit** `feat(states): key_for_label + visible() two-axis predicate (Phase C R2/R6/R9)`

---

### Task 3: Store plumbing — `NoteStore.create` params + recurrence inherit (R11 part, R12)

**Files:**
- Modify: `serenity/core/note_store.py:140-162`, `serenity/core/todo_store.py:175-192`
- Test: `tests/test_note_store.py`, `tests/test_todo_store.py`

**Interfaces:**
- Produces: `NoteStore.create(title, body="", tags=None, color=None, pinned=False, state_tag=None, context=None)`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_note_store.py
def test_create_stamps_state_tag_context(tmp_path):
    store = NoteStore(tmp_path)
    n = store.create("t", state_tag="working", context="business")
    assert (n.state_tag, n.context) == ("working", "business")
    store2 = NoteStore(tmp_path)          # survives the file round-trip + reindex
    n2 = store2.get(n.id)
    assert (n2.state_tag, n2.context) == ("working", "business")

# tests/test_todo_store.py
def test_recurrence_clone_inherits_stamp(tmp_path):
    store = TodoStore(tmp_path)
    t = store.add(Todo(title="standup", recurring="daily",
                       state_tag="deep_work", context="private"))
    store.complete(t.id)
    clone = next(x for x in store.all() if x.id != t.id)
    assert (clone.state_tag, clone.context) == ("deep_work", "private")
    assert clone.done is False


def test_recurrence_clone_field_list_pinned(tmp_path):
    """Pin the hand-written clone subset (R12): title/recurring/category/tags/due/subtasks
    + state_tag/context. ics_uid + linked_note_ids stay deliberately NOT copied."""
    store = TodoStore(tmp_path)
    t = store.add(Todo(title="s", recurring="daily", ics_uid="U", linked_note_ids=["n1"],
                       state_tag="k", context="business"))
    store.complete(t.id)
    clone = next(x for x in store.all() if x.id != t.id)
    assert clone.ics_uid is None and clone.linked_note_ids == []
    assert (clone.state_tag, clone.context) == ("k", "business")
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `NoteStore.create`: add `state_tag: Optional[str] = None, context: Optional[str] = None` params; pass `state_tag=state_tag, context=context` into the `Note(...)` constructed at line ~149. `TodoStore._spawn_recurrence`: add `state_tag=done_todo.state_tag, context=done_todo.context,` to the `clone = Todo(...)` literal; extend its docstring field list.
- [ ] **Step 4: Run** files + full suite → PASS.
- [ ] **Step 5: Commit** `feat(stores): create() stamp passthrough + recurrence clone inherits stamp (Phase C R11/R12)`

---

### Task 4: Shell `stamp()` + direct funnels (R10, R11 core)

**Files:**
- Modify: `serenity/ui/shell.py` (view ctor ~336, `_commit_capture` ~743, `_open_quick_note` ~763, `_open_quick_todo` ~773, capture-parse site that sets `_pending`), `serenity/ui/modals.py` (QuickNoteDialog ~137-148, QuickTodoDialog ~151-224), `serenity/ui/todos_view.py:496-509`
- Test: `tests/test_shell_stamp.py` (new), extend `tests/test_modals.py`

**Interfaces:**
- Consumes: `key_for_label`, model fields (T1/T2).
- Produces: `Shell.stamp() -> tuple[Optional[str], str]`; `QuickNoteDialog(note_store, settings, parent=None, stamp=None)`; `QuickTodoDialog(todo_store, settings, parent=None, default_due=None, stamp=None)`; `TodosView(store, settings, note_store=None, stamp=None, parent=None)`.

- [ ] **Step 1: Failing tests** (`tests/test_shell_stamp.py`, offscreen; build a Shell with a temp vault the way `tests/test_shell.py` does — reuse its fixture pattern):

```python
def test_stamp_reads_running_and_context(shell):
    shell.settings.current_context = "business"
    shell._on_activity("Working")
    assert shell.stamp() == ("working", "business")
    shell._on_activity("Idle")
    assert shell.stamp() == (None, "business")


def test_stamp_unmappable_label_is_none(shell):
    shell.activity_store.start("NoSuchLabel")
    assert shell.stamp()[0] is None


def test_add_bar_stamps_at_save(shell):
    shell._on_activity("Coding")
    shell.todos_view.add_input.setText("write tests")
    shell.todos_view._add()
    t = shell.todo_store.all()[-1]
    assert (t.state_tag, t.context) == ("coding", "business")


def test_capture_snapshot_survives_switch(shell):
    shell.settings.current_context = "business"
    shell._on_activity("Working")
    cap = shell.router.route("call tom")            # leaves cap pending on a slot
    shell._pending = cap                            # simulate the pending ask
    shell._pending_stamp = shell.stamp()
    shell.set_context("private")
    shell._on_activity("Gaming")
    shell._commit_capture(shell._pending)
    t = shell.todo_store.all()[-1]
    assert (t.state_tag, t.context) == ("working", "business")   # snapshot, not "now"
```

Extend `tests/test_modals.py`: construct `QuickTodoDialog(store, settings, stamp=lambda: ("working", "private"))`, drive `title` + `_save()`, assert the added todo's `(state_tag, context)`; same for `QuickNoteDialog`.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**

`shell.py` — add next to `_mascots()`:

```python
def stamp(self):
    """Creation-time (state_tag, context): the running activity's registry key
    (None when idle/unmappable) + the effective global context (R10/R11)."""
    entry = self.activity_store.running()
    key = states.key_for_label(self.settings.states(), entry.category) if entry else None
    return key, self.settings.context()
```

- View ctor: `TodosView(self.todo_store, self.settings, note_store=self.note_store, stamp=self.stamp)`.
- `_open_quick_note` / `_open_quick_todo`: pass `stamp=self.stamp` to the dialogs.
- Capture snapshot: at EVERY site that assigns `self._pending = cap` (mic route + slot-ask flow; grep `_pending =`), also set `self._pending_stamp = self.stamp()`; initialize `self._pending_stamp = None` in `__init__` next to `_pending`. In `_commit_capture`, read `st, ctx = self._pending_stamp if self._pending_stamp is not None else self.stamp()` then clear `self._pending_stamp = None` alongside `_pending`; pass into both branches: `Todo(..., state_tag=st, context=ctx)` and `self.note_store.create(cap.title, body=cap.raw, state_tag=st, context=ctx)`.

`modals.py` — both dialogs: accept `stamp=None` keyword, store `self._stamp = stamp`; in `_save()` immediately before building/creating: `st, ctx = self._stamp() if self._stamp else (None, None)`; `QuickTodoDialog`: add `state_tag=st, context=ctx` to BOTH `Todo(...)` literals (~204 and ~209); `QuickNoteDialog`: `self.note_store.create(title or "Quick note", body=body, tags=tags, state_tag=st, context=ctx)`.

`todos_view.py` — ctor: add `stamp=None` param, `self._stamp = stamp`; `_add()`: `st, ctx = self._stamp() if self._stamp else (None, None)` then `Todo(..., state_tag=st, context=ctx)`.

- [ ] **Step 4: Run** new tests + full suite → PASS.
- [ ] **Step 5: Commit** `feat(ui): Shell.stamp() closure + save-time stamping in all direct funnels (Phase C R10/R11)`

---

### Task 5: Derived funnels — prep-note, recovery, ICS import (R11 rest, R12 rest)

**Files:**
- Modify: `serenity/ui/todos_view.py:399-417`, `serenity/ui/note_editor_panel.py:~281`, `serenity/ui/calendar_view.py` (ctor + `_apply_import` ~259), `serenity/ui/shell.py:341`
- Test: extend `tests/test_todos_view.py`, `tests/test_note_editor_panel.py`, `tests/test_calendar_view.py`

**Interfaces:**
- Produces: `CalendarView(todo_store, settings=None)`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_todos_view.py — prep-note inherits the todo's stamp
def test_prep_note_inherits_todo_stamp(tmp_path, qapp):
    ...build TodosView with a note_store; todo = Todo(title="m", state_tag="meeting", context="business")...
    card._on_note_btn()
    note = note_store.get(todo.linked_note_ids[0])
    assert (note.state_tag, note.context) == ("meeting", "business")

# tests/test_calendar_view.py — import stamps context only; update path never restamps
def test_ics_import_create_stamps_context(...):
    view = CalendarView(store, settings=settings_with_context("private"))
    ...run _apply_import with a plan containing one to_create...
    assert (created.state_tag, created.context) == (None, "private")

def test_ics_reimport_update_keeps_stamp(...):
    ...existing todo state_tag="working", context="business"; re-import same uid with changed title...
    assert (todo.state_tag, todo.context) == ("working", "business")

# tests/test_note_editor_panel.py — recovery re-save keeps the old stamp
def test_save_as_new_keeps_stamp(...):
    ...note with state_tag="working", context="business"; purge the .md; trigger _save_as_new...
    assert (recreated.state_tag, recreated.context) == ("working", "business")
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- `todos_view.py:_on_note_btn`: `note = self.note_store.create(self.todo.title or "Untitled", body=body, state_tag=self.todo.state_tag, context=self.todo.context)`.
- `note_editor_panel.py:_save_as_new`: pass `state_tag=self._note.state_tag, context=self._note.context` (match the local variable name used there) into `store.create(...)`.
- `calendar_view.py`: ctor gains `settings=None`, store `self.settings = settings`; in `_apply_import`'s create branch: `todo.state_tag = None; todo.context = self.settings.context() if self.settings else None` before `store.add` (exact shape per the code there — set fields on the `Todo` the plan builds). The UID-match update branch: no stamp writes.
- `shell.py:341`: `CalendarView(self.todo_store, settings=self.settings)`.
- [ ] **Step 4: Run** + full suite → PASS.
- [ ] **Step 5: Commit** `feat(ui): derived creations inherit stamps; ICS import stamps context (Phase C R11/R12)`

---

### Task 6: State chip + list post-filters + hints + grace (R1–R5, R7, R15)

**Files:**
- Create: `serenity/ui/state_chip.py` (header comment required)
- Modify: `serenity/ui/todos_view.py` (ctor/refresh), `serenity/ui/notes_view.py` (ctor/refresh), `serenity/ui/shell.py` (`_build_ui` end, `_on_activity`, `_sync_context`)
- Test: `tests/test_state_chip.py` (new), extend `tests/test_shell.py`

**Interfaces:**
- Produces: `StateFilterChip(QWidget)` with `.set_state(key, label, color, checked)` / `.clear()` / `.active_key() -> Optional[str]` / signal `toggled_filter`; views gain `set_state_filter(key, label, color, checked)` + internal `_state_key`; `Shell._sync_state_chips(preserve_checked=False)`.

- [ ] **Step 1: Failing tests** (representative — the full §7 chip table row by row):

```python
def test_chip_hidden_when_idle(shell): ...            # R2: no span -> both chips hidden, filter off
def test_chip_boot_restore(tmp_vault): ...            # R1: activity.json open span -> build Shell -> chips visible+checked
def test_chip_auto_recheck_on_switch(shell): ...      # R4: uncheck, switch activity -> re-checked + relabeled
def test_manual_uncheck_lasts_span(shell): ...        # R4: uncheck persists across refresh() within the span
def test_chip_unmappable_hidden(shell): ...           # R2: start("NoSuchLabel") -> hidden, all ctx items shown
def test_flip_cross_context_unchecks(shell): ...      # R7: business activity + flip private -> visible+UNCHECKED
def test_post_filter_lists(shell): ...                # context axis hides other-context todo/note in both views
def test_grace_pending_card_survives_filter(shell): ...  # R3: id in _grace_timers renders despite filter
def test_hidden_hint_shows_count(shell): ...          # R5: chip checked + hidden>0 -> "N hidden..." label
def test_flip_keeps_running_span(shell): ...          # R15: flip never stops the span; stamp = (key, new ctx)
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**

`state_chip.py` — one pill chip in a `QFrame#card` row:

```python
class StateFilterChip(QWidget):
    toggled_filter = Signal()
    def __init__(self, parent=None):
        ...  # QHBoxLayout; self.btn = QPushButton(objectName "pill", checkable);
        ...  # self.btn.toggled.connect(lambda _: self.toggled_filter.emit()); start hidden
    def set_state(self, key, label, color, checked):
        self._key = key
        self.btn.setText(f"● {label}")
        self.btn.setStyleSheet(f"color:{color};")
        self.btn.setChecked(checked)
        self.setVisible(True)
    def clear(self):
        self._key = None
        self.setVisible(False)
    def active_key(self):
        return self._key if self.isVisible() and self.btn.isChecked() else None
```

Views: instantiate the chip (Todos: between add-row and list; Notes: after the Text/Meaning toggle row), connect `toggled_filter` → `self.refresh`; add `set_state_filter(key, label, color, checked)` → `chip.set_state(...)` or `chip.clear()` when `key is None`, then `self.refresh()`. In each `refresh()` post-filter: `ctx = self.settings.context() if self.settings else None`; `skey = self.chip.active_key()`; items = `[x for x in fetched if ctx is None or visible(x, ctx, skey)]`; TodosView additionally re-adds (unfiltered, deduped) any todo whose id is in `self._grace_timers` (R3). Hidden-hint label (`QLabel`, ink3 11px, hidden by default): shown with `f"{hidden} hidden by context/state filter"` when `hidden > 0` AND (Notes: non-empty query; Todos: `skey is not None`) (R5).

`shell.py` — new `_sync_state_chips(preserve_checked=False)`: read `entry = self.activity_store.running()`; resolve `key = states.key_for_label(self.settings.states(), entry.category) if entry else None`; when `key is None` → both views `set_state_filter(None, "", "", False)`; else find the registry row (label/color by key), compute `checked`: `False` if the row's context not in `(self.settings.context(), "any")` (R7), else `True` unless `preserve_checked` and the view's chip already shows this key (keep each view's current checked state, R4 per-view). Call it: at the END of `_build_ui` (after `activity_chip.show_running`, R1), in `_on_activity` (after start/stop), and in `_sync_context` (with `preserve_checked=True`) — `_sync_context` also calls `self.todos_view.refresh()` + `self.notes_view.refresh()`. Suppress the completion bubble in `_on_todo_completed` when `todo.context` is set and differs from `settings.context()` (R3): guard the `mascot.says` line only.

- [ ] **Step 4: Run** + full suite → PASS.
- [ ] **Step 5: Commit** `feat(ui): state filter chip + two-axis list filtering + grace/hint safety nets (Phase C R1-R5,R7,R15)`

---

### Task 7: Cross-surface context — calendar, graph, mini + sync fan-out (R13)

**Files:**
- Modify: `serenity/ui/calendar_view.py` (`_grid_model` ~127, event-row build), `serenity/ui/calendar_week_panel.py` (~242 grid events, ~384 side list), `serenity/ui/graph_view.py` (ctor + `refresh` ~87), `serenity/ui/mini_window.py` (ctor + `refresh_todo` ~120), `serenity/ui/shell.py` (`_sync_context`, graph/mini construction)
- Test: extend `tests/test_calendar_view.py`, `tests/test_graph_view.py`, `tests/test_mini_window.py`, `tests/test_shell.py`

- [ ] **Step 1: Failing tests** — for each surface: seed one `context="business"` + one `context="private"` + one unstamped todo; with context=business assert the private one is absent and the other two present. Plus: `test_sync_context_fans_out(shell)` — flip context, assert calendar view + open week pop-out + mini `refresh_todo` all re-query (use monkeypatched counters or visible-content assertions).

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Uniform pattern — each surface filters its todo fetch when it has settings:

```python
todos = self.todo_store.all()
if self.settings is not None:
    ctx = self.settings.context()
    todos = [t for t in todos if visible(t, ctx)]
```

- `calendar_view._grid_model`: apply before `collect_events(...)` (view has settings since Task 5).
- `calendar_week_panel`: same at ~242 (`collect_events`) and ~384 (`self.todo_store.active()` side list) using `self._settings`.
- `graph_view`: ctor gains `settings=None` (shell passes it at ~339); filter in `refresh()` before `build_graph(todos)` — edges to dropped nodes disappear with the nodes.
- `mini_window.refresh_todo`: filter `self.todo_store.all()` the same way before `mini_todos(...)` (ctor already receives settings; verify + thread if not).
- `shell._sync_context`: extend the Task-6 fan-out with `self.calendar_view.refresh()`, the open-pop-out refresh (copy the `isinstance(inner, CalendarWeekPanel)` block from `_on_calendar_wrote`), `self.graph_view.refresh()`, and `if self._mini is not None: self._mini.refresh_todo()`.
- [ ] **Step 4: Run** + full suite → PASS.
- [ ] **Step 5: Commit** `feat(ui): context axis on calendar/graph/mini + full _sync_context fan-out (Phase C R13)`

---

### Task 8: AI surfaces candidate filtering + Ask cache key + Trash suffix (R16, R14)

**Files:**
- Modify: `serenity/ui/notes_view.py` (refresh ~452-469, `open_note`, `_open_ask`, `_open_duplicates`, NoteCard/ReadNoteDialog provider args ~83-135, ~182-190, `_ensure_related` ~296), `serenity/ui/ask_dialog.py` (~140-150 + cache lookup), `serenity/ui/trash_view.py` (row meta label)
- Test: extend `tests/test_notes_view.py`, `tests/test_ask_dialog.py`, `tests/test_trash_view.py`

- [ ] **Step 1: Failing tests**
- related chips: expand a business note while context=business with a private note in the vault → private title NOT among chips, but `semantic.index` still received the FULL active list (assert via a stub index recording its `index()` arg).
- Ask: retrieval candidates exclude private notes in business context; cache: same question in business vs private yields separate cache entries (no cross-context answer reuse).
- duplicates scan: candidate list excludes other-context notes.
- Meaning-mode list search: `semantic.index` called with full corpus; rendered results filtered.
- Trash: a trashed `context="private"` note row's meta label ends with `· private`; unstamped row unchanged; trash list itself NOT filtered.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- `notes_view.py`: add `def _filtered_active(self): ctx = self.settings.context() if self.settings else None; base = self.store.all_active(); return base if ctx is None else [n for n in base if visible(n, ctx)]`. Thread it as a NEW `candidates_provider` kwarg into `NoteCard` and `ReadNoteDialog` (keep `notes_provider=self.store.all_active` for indexing); `_ensure_related`/dialog: `self.semantic.index(self._notes_provider())` (full) then `related_notes(self.note, self._candidates_provider(), index=...)` (fallback to `notes_provider` when candidates kwarg is None so old callers keep working). In `refresh()` meaning branch: `self.semantic.index(active)` stays on full `active`; rank over `self._filtered_active()` (then the Task-6 post-filter is a no-op for context but still applies the state axis). `_open_ask` / `_open_duplicates`: pass the filtered provider as the candidate source (+ full provider for indexing where the dialog indexes).
- `ask_dialog.py`: index on the full provider; retrieve/rank over candidates; cache key: wherever the question keys the warm cache, use `f"{self._context()}::{q}"` with `_context()` from a threaded settings/context callable (thread `context_provider=lambda: settings.context()` from `_open_ask`).
- `trash_view.py`: locate the per-row meta-label f-string; append `f" · {item.context}"` when `getattr(item, 'context', None)` is set (works for both Note and Todo rows). No filtering.
- [ ] **Step 4: Run** + full suite → PASS.
- [ ] **Step 5: Commit** `feat(ui): context-filtered AI candidates (full-corpus index kept) + ctx-keyed Ask cache + trash context suffix (Phase C R16/R14)`

---

### Task 9: Pop-out editor front-matter round-trip (R8)

**Files:**
- Modify: `serenity/core/note_draft.py` (`validate` ~98-136, `promote` ~229-247)
- Test: extend `tests/test_note_draft.py`

- [ ] **Step 1: Failing tests**

```python
def test_validate_rejects_bad_context(store_note):
    with pytest.raises(NoteDraftInvalid):
        validate(fm_text_with(context="banana"), store_note)
    validate(fm_text_with(context="private"), store_note)      # ok
    validate(fm_text_with(context=None), store_note)           # explicit null ok


def test_validate_rejects_nonstring_state_tag(store_note):
    with pytest.raises(NoteDraftInvalid):
        validate(fm_text_with(state_tag=["x"]), store_note)


def test_promote_persists_stamp_edits(tmp_store):
    ...note with state_tag="working", context="business"; promote with fm_edited=True and
    fm text setting state_tag: focus / context: private...
    assert (live.state_tag, live.context) == ("focus", "private")
    ...promote with fm text OMITTING both keys -> keeps live values...
    ...promote with explicit `state_tag: null` -> None...
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `validate()` — after the pinned/deleted block:

```python
    if "context" in fm and fm["context"] is not None and fm["context"] not in ("business", "private"):
        raise NoteDraftInvalid("'context' must be business, private or null.")
    if "state_tag" in fm and fm["state_tag"] is not None and not isinstance(fm["state_tag"], str):
        raise NoteDraftInvalid("'state_tag' must be a string or null.")
```

`promote()` — inside the `if fm_edited:` block, after the `deleted` line:

```python
        if "state_tag" in fm:
            live.state_tag = fm["state_tag"] or None
        if "context" in fm:
            live.context = fm["context"] or None
```

- [ ] **Step 4: Run** + full suite → PASS.
- [ ] **Step 5: Commit** `feat(core): pop-out fm editor round-trips state_tag/context with strict gate (Phase C R8)`

---

### Task 10: User flows + docs wrap

**Files:**
- Modify: `notes/5_Interaction_Flows.md` (new Phase-C area section), `notes/1_Planning.md` (wrap), `docs/serenity-spec.md` + `notes/2_System_Arch.md` (field/filter mentions, mirroring the Phase A/B sync commit `f783788`)

- [ ] **Step 1:** Append a `## Area: states-contexts (Phase C)` section to `notes/5_Interaction_Flows.md`: every flow from the flow-harden pass (create-under-activity, create-idle, context flip, chip lifecycle, derived creations, hand-edited vault input, cross-surface) with its interruptions marked OK (and which R# net covers it) — the 16 requirements each appear as the safety net of at least one flow; the refuted candidate is recorded as OK-by-analysis.
- [ ] **Step 2:** Planning wrap + spec/arch sync (fields on the models, the two axes, surfaces list).
- [ ] **Step 3:** Full suite green; `gitnexus_detect_changes` before the wrap commit (PR-boundary policy).
- [ ] **Step 4: Commit** `docs: Phase C user flows + spec/arch sync + planning wrap`

---

## After the plan: QA pipeline (goal condition)

criticizer → fix → optimizer → fix → test-agent → fix, each adversarially verified, full suite green between passes (per CLAUDE.md + `feature-qa-agent-pipeline`).
