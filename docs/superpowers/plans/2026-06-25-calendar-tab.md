# Calendar Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only **Calendar** tab that lays out todos-with-a-`due`-date on a 7-column (Mon–Sun) grid, with a week view (grid + filterable event list) and an expandable month view, sized for the 348px dock.

**Architecture:** Mirror the `weekly_board` split — a pure, headless-tested helper (`core/calview.py`) buckets dated todos into `CalGrid` day-cells; a thin Qt view (`ui/calendar_view.py`) only renders it and holds interaction state; the shell wires it in as a new tab (additive, impact-checked LOW risk).

**Tech Stack:** Python 3.12, PySide6, stdlib `calendar` + `datetime`. No new dependencies.

## Global Constraints

- Python 3.12; PySide6 only; **no new dependencies**.
- **No new data model, no migration** — uses existing `Todo.due` / `Todo.category` / `Todo.done` / `Todo.deleted` / `Todo.id`.
- Scope: **events = todos with `due` set and not deleted**. Notes are NOT on the calendar.
- **Cross-platform copy: never use `strftime('%-d')` / `'%#d'`** (Linux-only / Windows-only). Build day numbers from `date.day` (an int). `%b`, `%B`, `%Y` are fine.
- House style: single-hyphen copy, **no emoji**; reuse `theme.COLORS`; `objectName("card")` / `objectName("sectLabel")`.
- **Every new `.py` file starts with the standard header-comment block** (Author: Berk, Created: 2026-06-25, Purpose/Role/Functions — see CLAUDE.md).
- Tests run headless: `QT_QPA_PLATFORM=offscreen python -m pytest -q`. Whole suite must stay green (baseline 770 passed, 5 skipped).
- Pure helpers take an injected `now` so tests never depend on the wall clock.
- Per CLAUDE.md, gitnexus impact analysis was already run on `shell.switch_tab`/`_build_ui` (both LOW, additive); re-run `npx gitnexus analyze` after implementation.

---

### Task 1: `core/calview.py` — `CalEvent` + `collect_events`

**Files:**
- Create: `serenity/core/calview.py`
- Test: `tests/test_calview.py`

**Interfaces:**
- Consumes: `serenity.core.models.Todo` (fields `due: datetime|None`, `title`, `category`, `done`, `deleted`, `id`).
- Produces:
  - `@dataclass CalEvent { when: datetime; title: str; category: str|None; done: bool; has_time: bool; todo_id: str }`
  - `collect_events(todos: list[Todo], now: datetime|None = None, show_done: bool = False) -> list[CalEvent]`
  - `_has_time(due: datetime) -> bool` (module-private helper)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calview.py
"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: Unit tests for the pure Calendar-tab grid helper (core.calview).
Role:    Guards collect_events / build_week / build_month: which todos become events,
         Mon-Sun bucketing, today + month-padding flags, intra-day sort. No Qt.

Test classes:
- TestCollectEvents - which todos become events; done/deleted/no-due filtering; has_time
- TestBuildWeek - Mon-Sun week, today flag, intra-day sort, label
- TestBuildMonth - weeks of the month incl. padding flagged, label
============================================================
"""
from datetime import datetime

from serenity.core.calview import collect_events
from serenity.core.models import Todo

NOW = datetime(2026, 6, 25, 9, 0)  # a Thursday


class TestCollectEvents:
    def test_includes_todo_with_due_and_excludes_no_due(self):
        todos = [
            Todo(title="Dentist", due=datetime(2026, 6, 25, 14, 0)),
            Todo(title="No date"),  # due is None -> excluded
        ]
        evs = collect_events(todos, now=NOW)
        assert [e.title for e in evs] == ["Dentist"]
        assert evs[0].todo_id == todos[0].id

    def test_excludes_deleted(self):
        todos = [Todo(title="Gone", due=datetime(2026, 6, 25, 14, 0), deleted=True)]
        assert collect_events(todos, now=NOW) == []

    def test_done_hidden_by_default_shown_with_flag(self):
        todos = [Todo(title="Did it", due=datetime(2026, 6, 25, 10, 0), done=True)]
        assert collect_events(todos, now=NOW) == []
        shown = collect_events(todos, now=NOW, show_done=True)
        assert len(shown) == 1 and shown[0].done is True

    def test_meeting_category_preserved(self):
        todos = [Todo(title="Standup", due=datetime(2026, 6, 25, 9, 0), category="meeting")]
        assert collect_events(todos, now=NOW)[0].category == "meeting"

    def test_has_time_true_for_timed_false_for_midnight(self):
        timed = Todo(title="t", due=datetime(2026, 6, 25, 14, 30))
        allday = Todo(title="a", due=datetime(2026, 6, 25, 0, 0))
        assert collect_events([timed], now=NOW)[0].has_time is True
        assert collect_events([allday], now=NOW)[0].has_time is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_calview.py::TestCollectEvents -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'serenity.core.calview'`.

- [ ] **Step 3: Write minimal implementation**

```python
# serenity/core/calview.py
"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: Pure logic for the Calendar tab - turn todos-with-a-due into a Mon-Sun grid.
Role:    The headless, Qt-free helper the ui.calendar_view renders. Mirrors core.weekly_board:
         the view holds no calendar logic, it only draws the CalGrid this module builds.
         Named 'calview' (not 'calendar') so it never shadows the stdlib calendar module,
         which build_month uses for the month layout.

Functions:
- collect_events(todos, now, show_done) -> [CalEvent] - todos with a due become events
- build_week(events, anchor, now) -> CalGrid - the Mon-Sun week containing anchor
- build_month(events, anchor, now) -> CalGrid - the weeks of anchor's month

Classes:
- CalEvent - one dated todo on the calendar (when, title, category, done, has_time, todo_id)
- DayCell - one grid day (day, in_period, is_today, sorted events)
- CalGrid - weeks of DayCells + a label + the mode ("week"/"month")
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass
class CalEvent:
    """One todo-with-a-deadline placed on the calendar."""

    when: datetime
    title: str
    category: str | None
    done: bool
    has_time: bool
    todo_id: str


def _has_time(due: datetime) -> bool:
    """A due exactly at midnight reads as all-day; any clock time means it is timed.

    Todo only stores `due: datetime` (no has_time flag), so a date-only capture lands at
    00:00 and shows without a time; a parsed clock time ("17 Uhr") shows HH:MM."""
    return not (due.hour == 0 and due.minute == 0 and due.second == 0)


def collect_events(todos, now: datetime | None = None, show_done: bool = False) -> list[CalEvent]:
    """Map the todos that belong on a calendar (a due date, not trashed) to CalEvents.

    Done todos are dropped unless show_done, so the default view is not overcrowded."""
    out: list[CalEvent] = []
    for t in todos:
        if t.deleted or t.due is None:
            continue
        if t.done and not show_done:
            continue
        out.append(
            CalEvent(
                when=t.due,
                title=t.title,
                category=t.category,
                done=t.done,
                has_time=_has_time(t.due),
                todo_id=t.id,
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_calview.py::TestCollectEvents -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add serenity/core/calview.py tests/test_calview.py
git commit -m "feat(calview): CalEvent + collect_events (todos-with-due -> events)"
```

---

### Task 2: `core/calview.py` — `DayCell`, `CalGrid`, `build_week`

**Files:**
- Modify: `serenity/core/calview.py`
- Test: `tests/test_calview.py`

**Interfaces:**
- Consumes: `CalEvent` (Task 1).
- Produces:
  - `@dataclass DayCell { day: date; in_period: bool; is_today: bool; events: list[CalEvent] }`
  - `@dataclass CalGrid { weeks: list[list[DayCell]]; label: str; mode: str }`
  - `build_week(events: list[CalEvent], anchor: date, now: datetime|None = None) -> CalGrid`
  - private: `_week_start(d: date) -> date`, `_day_cell(d, events, now, in_period=True) -> DayCell`, `_week_label(start: date, end: date) -> str`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_calview.py
from datetime import date  # add to imports
from serenity.core.calview import build_week  # add to imports


class TestBuildWeek:
    def test_week_is_monday_to_sunday_containing_anchor(self):
        # anchor Thu 2026-06-25 -> week Mon 22 .. Sun 28
        grid = build_week([], date(2026, 6, 25), now=NOW)
        assert grid.mode == "week"
        assert len(grid.weeks) == 1 and len(grid.weeks[0]) == 7
        days = [c.day for c in grid.weeks[0]]
        assert days[0] == date(2026, 6, 22)
        assert days[-1] == date(2026, 6, 28)

    def test_event_lands_on_its_day_and_today_flagged(self):
        evs = collect_events([Todo(title="Dentist", due=datetime(2026, 6, 25, 14, 0))], now=NOW)
        grid = build_week(evs, date(2026, 6, 25), now=NOW)
        thu = grid.weeks[0][3]  # Mon..Sun -> Thu is index 3
        assert thu.day == date(2026, 6, 25)
        assert thu.is_today is True
        assert [e.title for e in thu.events] == ["Dentist"]
        assert grid.weeks[0][0].is_today is False

    def test_intraday_sort_timed_before_untimed(self):
        evs = collect_events([
            Todo(title="Late", due=datetime(2026, 6, 25, 16, 0)),
            Todo(title="AllDay", due=datetime(2026, 6, 25, 0, 0)),
            Todo(title="Early", due=datetime(2026, 6, 25, 9, 0)),
        ], now=NOW)
        thu = build_week(evs, date(2026, 6, 25), now=NOW).weeks[0][3]
        assert [e.title for e in thu.events] == ["Early", "Late", "AllDay"]

    def test_label_same_month(self):
        assert build_week([], date(2026, 6, 25), now=NOW).label == "Jun 22 - 28"

    def test_label_crosses_month(self):
        # week of Mon 2026-06-29 .. Sun 2026-07-05
        assert build_week([], date(2026, 6, 30), now=NOW).label == "Jun 29 - Jul 5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_calview.py::TestBuildWeek -q`
Expected: FAIL — `ImportError: cannot import name 'build_week'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to serenity/core/calview.py
@dataclass
class DayCell:
    """One day in the grid: its date, whether it belongs to the focused period, today, events."""

    day: date
    in_period: bool
    is_today: bool
    events: list[CalEvent] = field(default_factory=list)


@dataclass
class CalGrid:
    """A laid-out calendar: rows of 7 DayCells (Mon..Sun), a header label, and the mode."""

    weeks: list[list[DayCell]]
    label: str
    mode: str


def _week_start(d: date) -> date:
    """The Monday of d's week (Monday=0)."""
    return d - timedelta(days=d.weekday())


def _day_cell(d: date, events: list[CalEvent], now: datetime, in_period: bool = True) -> DayCell:
    """Bucket the events that fall on day d, sorted timed-first then by time, then title."""
    todays = [e for e in events if e.when.date() == d]
    todays.sort(key=lambda e: (not e.has_time, e.when, e.title))
    return DayCell(day=d, in_period=in_period, is_today=(d == now.date()), events=todays)


def _week_label(start: date, end: date) -> str:
    """e.g. 'Jun 22 - 28' within a month, 'Jun 29 - Jul 5' across one. No %-d (Windows-safe)."""
    if start.month == end.month:
        return f"{start.strftime('%b')} {start.day} - {end.day}"
    return f"{start.strftime('%b')} {start.day} - {end.strftime('%b')} {end.day}"


def build_week(events: list[CalEvent], anchor: date, now: datetime | None = None) -> CalGrid:
    """Lay out the single Mon-Sun week that contains the anchor date."""
    now = now or datetime.now()
    start = _week_start(anchor)
    days = [start + timedelta(days=i) for i in range(7)]
    week = [_day_cell(d, events, now) for d in days]
    return CalGrid(weeks=[week], label=_week_label(start, days[-1]), mode="week")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_calview.py::TestBuildWeek -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add serenity/core/calview.py tests/test_calview.py
git commit -m "feat(calview): DayCell/CalGrid + build_week (Mon-Sun bucketing)"
```

---

### Task 3: `core/calview.py` — `build_month`

**Files:**
- Modify: `serenity/core/calview.py`
- Test: `tests/test_calview.py`

**Interfaces:**
- Consumes: `CalEvent`, `DayCell`, `CalGrid`, `_day_cell` (Tasks 1–2).
- Produces: `build_month(events: list[CalEvent], anchor: date, now: datetime|None = None) -> CalGrid`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_calview.py
from serenity.core.calview import build_month  # add to imports


class TestBuildMonth:
    def test_weeks_are_full_mon_sun_rows_with_padding_flagged(self):
        # June 2026: Jun 1 is a Monday, so the grid starts exactly on Jun 1 (no leading pad),
        # and the last week (Jun 29, 30, then Jul 1..5) has trailing padding from July.
        grid = build_month([], date(2026, 6, 15), now=NOW)
        assert grid.mode == "month"
        assert all(len(w) == 7 for w in grid.weeks)
        first = grid.weeks[0][0]
        assert first.day == date(2026, 6, 1) and first.in_period is True
        last = grid.weeks[-1][-1]
        assert last.day.month == 7        # trailing pad from July
        assert last.in_period is False

    def test_label_is_month_year(self):
        assert build_month([], date(2026, 6, 15), now=NOW).label == "June 2026"

    def test_event_placed_in_month_grid(self):
        evs = collect_events([Todo(title="Ship", due=datetime(2026, 6, 25, 0, 0))], now=NOW)
        grid = build_month(evs, date(2026, 6, 1), now=NOW)
        hits = [c for w in grid.weeks for c in w if c.events]
        assert len(hits) == 1 and hits[0].day == date(2026, 6, 25)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_calview.py::TestBuildMonth -q`
Expected: FAIL — `ImportError: cannot import name 'build_month'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to serenity/core/calview.py
import calendar as _stdlib_calendar  # add near the top imports, not inline


def build_month(events: list[CalEvent], anchor: date, now: datetime | None = None) -> CalGrid:
    """Lay out the weeks of the anchor's month (Mon-Sun rows).

    Uses the stdlib calendar's monthdatescalendar, which returns whole Mon..Sun weeks padded
    with the adjacent months' days; those padding days are flagged in_period=False so the view
    can dim them."""
    now = now or datetime.now()
    cal = _stdlib_calendar.Calendar(firstweekday=0)  # 0 = Monday
    weeks = [
        [_day_cell(d, events, now, in_period=(d.month == anchor.month)) for d in wk]
        for wk in cal.monthdatescalendar(anchor.year, anchor.month)
    ]
    return CalGrid(weeks=weeks, label=f"{anchor.strftime('%B %Y')}", mode="month")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_calview.py -q`
Expected: PASS (whole file — 13 tests).

- [ ] **Step 5: Commit**

```bash
git add serenity/core/calview.py tests/test_calview.py
git commit -m "feat(calview): build_month (stdlib calendar weeks, padding flagged)"
```

---

### Task 4: `ui/calendar_view.py` — view skeleton (week grid + event list + day filter)

**Files:**
- Create: `serenity/ui/calendar_view.py`
- Test: `tests/test_ui_calendar.py`

**Interfaces:**
- Consumes: `core.calview.{collect_events, build_week, build_month, CalGrid, DayCell}`; `core.todo_store.TodoStore` (`.all()`); `ui.theme.COLORS`.
- Produces:
  - `class CalendarView(QWidget)` with `__init__(self, todo_store, parent=None)`, `refresh() -> None`, signal `open_todo = Signal(str)`.
  - Internal state: `_anchor: date`, `_mode: str = "week"`, `_selected_day: date|None = None`, `_show_done: bool = False`.

This task builds the **week view only** (grid row + filterable list + refresh). Controls
(month toggle / nav / today / show-done) come in Task 5; for now the view always renders the
week containing today, and clicking a day filters the list.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ui_calendar.py
"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: Headless smoke tests for the Calendar tab view (ui.calendar_view).
Role:    Under QT_QPA_PLATFORM=offscreen, assert CalendarView builds + refresh() renders for
         empty and populated stores, and that day-click / month-toggle / nav / show-done do
         not raise. Pure layout logic is covered by tests/test_calview.py.

Test classes:
- TestCalendarView - builds, renders week grid + event list, day filter, controls
============================================================
"""
import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.models import Todo  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.calendar_view import CalendarView  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class TestCalendarView:
    def test_builds_empty(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        view.refresh()  # must not raise on an empty store

    def test_renders_with_a_dated_todo(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Dentist", due=datetime.now().replace(hour=14, minute=0)))
        view = CalendarView(store)
        view.refresh()  # must not raise; the event is in this week

    def test_day_click_filters_without_raising(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Dentist", due=datetime.now().replace(hour=14, minute=0)))
        view = CalendarView(store)
        view._on_day_clicked(datetime.now().date())  # select a day -> filter
        view._on_day_clicked(datetime.now().date())  # click again -> clear filter
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_calendar.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'serenity.ui.calendar_view'`.

- [ ] **Step 3: Write minimal implementation**

```python
# serenity/ui/calendar_view.py
"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: The Calendar tab - a Mon-Sun grid of todo deadlines (renders core.calview).
Role:    Read-only deadline view in the shell tab row. Holds only interaction state
         (focused week/month, selected day, show-done); all bucketing is core.calview.
         Week view = one 7-col row + a filterable event list; Month view = the full month
         grid, click a week to drop back into week view. No event creation/editing.

Classes:
- CalendarView - the tab widget; refresh() rebuilds from the todo store
============================================================
"""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.calview import build_month, build_week, collect_events
from .theme import COLORS

_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


class CalendarView(QWidget):
    """Renders todo deadlines on a Mon-Sun grid (week or month), event list below."""

    open_todo = Signal(str)  # emits a todo id when an event row is clicked

    def __init__(self, todo_store, parent=None):
        super().__init__(parent)
        self.todo_store = todo_store
        self._anchor: date = datetime.now().date()
        self._mode = "week"
        self._selected_day: date | None = None
        self._show_done = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # header (label only for now; controls added in Task 5)
        self._label = QLabel()
        self._label.setObjectName("sectLabel")
        root.addWidget(self._label)

        # grid of day cells
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(3)
        root.addWidget(self._grid_host)

        # scrollable event list (week mode)
        self._list_host = QWidget()
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._list_host)
        root.addWidget(scroll, 1)

        self.refresh()

    # ---- data ----
    def _grid_model(self):
        events = collect_events(self.todo_store.all(), show_done=self._show_done)
        if self._mode == "month":
            return build_month(events, self._anchor)
        return build_week(events, self._anchor)

    # ---- interactions ----
    def _on_day_clicked(self, day: date):
        if self._mode == "month":
            # clicking a day in month view selects that week -> back to week view
            self._anchor = day
            self._mode = "week"
            self._selected_day = None
        else:
            # toggle the day filter on the event list
            self._selected_day = None if self._selected_day == day else day
        self.refresh()

    # ---- rendering ----
    def refresh(self) -> None:
        grid = self._grid_model()
        self._label.setText(grid.label)
        self._render_grid(grid)
        self._render_list(grid)

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_grid(self, grid):
        self._clear(self._grid)
        for col, name in enumerate(_WEEKDAYS):
            head = QLabel(name)
            head.setAlignment(Qt.AlignCenter)
            head.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")
            self._grid.addWidget(head, 0, col)
        for r, week in enumerate(grid.weeks, start=1):
            for c, cell in enumerate(week):
                self._grid.addWidget(self._day_button(cell), r, c)

    def _day_button(self, cell) -> QPushButton:
        btn = QPushButton(str(cell.day.day))
        btn.setObjectName("calday")
        btn.setFixedHeight(34)
        meeting = any(e.category == "meeting" for e in cell.events)
        selected = cell.day == self._selected_day
        ink = COLORS["ink"] if cell.in_period else COLORS["ink3"]
        border = COLORS["accent"] if (meeting or selected) else COLORS["line"]
        weight = "700" if cell.is_today else "400"
        dot = " *" if cell.events else ""
        btn.setText(f"{cell.day.day}{dot}")
        btn.setStyleSheet(
            f"QPushButton#calday{{color:{ink}; font-weight:{weight};"
            f" border:1px solid {border}; border-radius:6px;"
            f" background:{COLORS['accent_soft'] if cell.is_today else 'transparent'};}}"
        )
        btn.clicked.connect(lambda _=False, d=cell.day: self._on_day_clicked(d))
        return btn

    def _render_list(self, grid):
        self._clear(self._list)
        if self._mode == "month":
            hint = QLabel("Tap a week to open it.")
            hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
            self._list.addWidget(hint)
            self._list.addStretch(1)
            return
        cells = grid.weeks[0]
        if self._selected_day is not None:
            cells = [c for c in cells if c.day == self._selected_day]
        rows = [(c, e) for c in cells for e in c.events]
        if not rows:
            empty = QLabel("No deadlines this week.")
            empty.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11.5px;")
            self._list.addWidget(empty)
        for cell, e in rows:
            self._list.addWidget(self._event_row(cell.day, e))
        self._list.addStretch(1)

    def _event_row(self, day: date, e) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        when = e.when.strftime("%H:%M") if e.has_time else "all-day"
        day_lbl = QLabel(f"{_WEEKDAYS[day.weekday()]} {day.day}")
        day_lbl.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        title = QLabel(e.title)
        title.setStyleSheet(
            f"color:{COLORS['accent'] if e.category == 'meeting' else COLORS['ink']};"
            f" font-size:12px; text-decoration:{'line-through' if e.done else 'none'};"
        )
        time_lbl = QLabel(when)
        time_lbl.setStyleSheet(f"color:{COLORS['ink2']}; font-size:10.5px;")
        lay.addWidget(day_lbl)
        lay.addWidget(title, 1)
        lay.addWidget(time_lbl)
        # whole row opens the underlying todo
        card.mousePressEvent = lambda _ev, tid=e.todo_id: self.open_todo.emit(tid)
        return card
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_calendar.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add serenity/ui/calendar_view.py tests/test_ui_calendar.py
git commit -m "feat(ui): CalendarView week grid + filterable event list"
```

---

### Task 5: `ui/calendar_view.py` — controls (Month/Week toggle, ‹/›/Today nav, Show done)

**Files:**
- Modify: `serenity/ui/calendar_view.py`
- Test: `tests/test_ui_calendar.py`

**Interfaces:**
- Consumes: the Task-4 `CalendarView` state + `refresh()`.
- Produces: header control buttons + handlers `_toggle_mode()`, `_go_prev()`, `_go_next()`, `_go_today()`, `_toggle_done(checked)`, and `_shift_month(d: date, delta: int) -> date`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ui_calendar.py
class TestCalendarControls:
    def test_month_toggle_then_back_to_week(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        view._toggle_mode()
        assert view._mode == "month"
        view._toggle_mode()
        assert view._mode == "week"

    def test_prev_next_today_week(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        start = view._anchor
        view._go_next()
        assert (view._anchor - start).days == 7
        view._go_prev()
        assert view._anchor == start
        view._go_next()
        view._go_today()
        assert view._anchor == datetime.now().date()

    def test_prev_next_month(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        view._toggle_mode()  # month
        m0 = view._anchor.month
        view._go_next()
        assert view._anchor.month == (m0 % 12) + 1

    def test_show_done_toggle_changes_state(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        assert view._show_done is False
        view._toggle_done(True)
        assert view._show_done is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_calendar.py::TestCalendarControls -q`
Expected: FAIL — `AttributeError: 'CalendarView' object has no attribute '_toggle_mode'`.

- [ ] **Step 3: Write minimal implementation**

Add a controls row to `__init__` (insert directly after the `self._label` block, before the grid host) and the handler methods. Use `from datetime import timedelta` (add to the import line `from datetime import date, datetime, timedelta`).

```python
        # --- controls row (replaces the label-only header) ---
        header = QHBoxLayout()
        header.setSpacing(6)
        self._prev_btn = QPushButton("<")
        self._next_btn = QPushButton(">")
        self._today_btn = QPushButton("Today")
        self._mode_btn = QPushButton("Month")
        self._done_btn = QPushButton("Show done")
        self._done_btn.setCheckable(True)
        for b in (self._prev_btn, self._next_btn, self._today_btn, self._mode_btn, self._done_btn):
            b.setObjectName("tab")
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        self._today_btn.clicked.connect(self._go_today)
        self._mode_btn.clicked.connect(self._toggle_mode)
        self._done_btn.toggled.connect(self._toggle_done)
        header.addWidget(self._prev_btn)
        header.addWidget(self._label, 1)
        header.addWidget(self._next_btn)
        header.addWidget(self._today_btn)
        header.addWidget(self._mode_btn)
        header.addWidget(self._done_btn)
```

Then **replace** the earlier `root.addWidget(self._label)` line so the label is added via the
header layout instead (remove the standalone `root.addWidget(self._label)` and add
`root.addLayout(header)` in its place). Add the handlers:

```python
    @staticmethod
    def _shift_month(d: date, delta: int) -> date:
        """First-of-month, shifted by delta months (no third-party deps)."""
        m = d.month - 1 + delta
        return date(d.year + m // 12, m % 12 + 1, 1)

    def _toggle_mode(self):
        self._mode = "month" if self._mode == "week" else "week"
        self._mode_btn.setText("Week" if self._mode == "month" else "Month")
        self._selected_day = None
        self.refresh()

    def _go_prev(self):
        self._anchor = (self._shift_month(self._anchor, -1) if self._mode == "month"
                        else self._anchor - timedelta(days=7))
        self._selected_day = None
        self.refresh()

    def _go_next(self):
        self._anchor = (self._shift_month(self._anchor, 1) if self._mode == "month"
                        else self._anchor + timedelta(days=7))
        self._selected_day = None
        self.refresh()

    def _go_today(self):
        self._anchor = datetime.now().date()
        self._selected_day = None
        self.refresh()

    def _toggle_done(self, checked: bool):
        self._show_done = bool(checked)
        self.refresh()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_calendar.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add serenity/ui/calendar_view.py tests/test_ui_calendar.py
git commit -m "feat(ui): Calendar controls - month toggle, week/month nav, today, show-done"
```

---

### Task 6: Shell wiring — new tab + click-through

**Files:**
- Modify: `serenity/ui/shell.py` (import ~`:58`; tab loop `:290-291`; stack list `:319-321`; `switch_tab` `:404-414`; `_wire` `:349`)
- Test: `tests/test_ui_calendar.py`

**Interfaces:**
- Consumes: `CalendarView` (Tasks 4–5); `Shell.todo_store`, `Shell.switch_tab`.
- Produces: a `"calendar"` tab + view; `_open_calendar_todo(todo_id)` handler.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ui_calendar.py
from serenity.core.settings import Settings  # noqa: E402


class TestShellCalendarTab:
    def test_shell_has_calendar_tab_and_switches(self, qapp, tmp_path):
        from serenity.ui.shell import Shell
        s = Settings()
        s.vault_path = str(tmp_path / "vault")
        # Shell.__init__ loads Settings from disk; point it at the tmp vault via monkeypatch-free
        # construction is covered by the existing TestShell. Here assert the tab + view exist.
        shell = Shell()
        try:
            assert "calendar" in shell.tab_buttons
            shell.switch_tab("calendar")
            assert shell.stack.currentIndex() == shell._view_index["calendar"]
        finally:
            shell.close()
```

> If `Shell()` reads the real user Settings and that is awkward in CI, mirror the existing
> `TestShell` setup in `tests/test_ui_stage1.py` (it constructs `Shell()` the same way and is
> already green); match whatever that test does for vault isolation.

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_calendar.py::TestShellCalendarTab -q`
Expected: FAIL — `assert 'calendar' in shell.tab_buttons` (KeyError / AssertionError).

- [ ] **Step 3: Write minimal implementation**

In `serenity/ui/shell.py`:

1. Add the import near the other view imports (~`:58`):
```python
from .calendar_view import CalendarView
```

2. Add to the tab-button loop list (`:290-291`):
```python
        for key, label in [("todos", "Todos"), ("notes", "Notes"),
                           ("graph", "Graph"), ("board", "Board"),
                           ("calendar", "Calendar")]:
```

3. Construct the view alongside the others (after `self.board_view = ...`, ~`:316`):
```python
        self.calendar_view = CalendarView(self.todo_store)
```

4. Add it to the stack list (`:319-321`):
```python
        for key, view in [("todos", self.todos_view), ("notes", self.notes_view),
                          ("graph", self.graph_view), ("board", self.board_view),
                          ("calendar", self.calendar_view), ("trash", self.trash_view)]:
```

5. In `switch_tab` add a refresh branch (after the `board` branch, ~`:414`):
```python
        elif key == "calendar":
            self.calendar_view.refresh()
```

6. In `_wire` (~`:354`) connect click-through and add the handler:
```python
        self.calendar_view.open_todo.connect(self._open_calendar_todo)
```
```python
    def _open_calendar_todo(self, todo_id: str):
        """Calendar event clicked: jump to the Todos tab (read-only deep-link)."""
        self._touch()
        self.switch_tab("todos")
        self.todos_view.refresh()
```

> If `TodosView` exposes a method to scroll-to / highlight a specific todo, call it with
> `todo_id` after `switch_tab("todos")`; otherwise the tab-switch above is sufficient for v1.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_calendar.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Verify the tab label fits the 348px row**

Run the app on a display if available, or eyeball the dock screenshot: the row is
Todos / Notes / Graph / Board / Calendar + trash icon. If "Calendar" clips, change the label in
step 2 to `"Cal"` (keep the key `"calendar"`). Note the decision in the commit message.

- [ ] **Step 6: Commit**

```bash
git add serenity/ui/shell.py tests/test_ui_calendar.py
git commit -m "feat(ui): wire Calendar tab into the shell + event click-through"
```

---

### Task 7: Full-suite green, docs, re-index

**Files:**
- Modify: `notes/1_Planning.md`, `notes/0_Learnings.md`

- [ ] **Step 1: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: PASS — baseline 770 + the new calview/calendar tests, 5 skipped unchanged. Fix any regression before continuing.

- [ ] **Step 2: Update `notes/1_Planning.md`**

Mark the Calendar tab built (it was item (1) in the USER-SET BUILD ORDER) and note the next step is **Phase A** (state registry). Record that notes were dropped from the calendar (deadlines only).

- [ ] **Step 3: Add a learning to `notes/0_Learnings.md`**

Add a short entry (with a TOC line): stdlib `calendar.Calendar(firstweekday=0).monthdatescalendar()` gives whole Mon–Sun weeks with adjacent-month padding for a month grid; and avoid `strftime('%-d')`/`'%#d'` for cross-platform day numbers — use `date.day`.

- [ ] **Step 4: Re-index the knowledge graph**

Run: `npx gitnexus analyze`
Expected: index updated to the new HEAD (clears the stale-index warning).

- [ ] **Step 5: Commit**

```bash
git add notes/1_Planning.md notes/0_Learnings.md
git commit -m "docs(notes): Calendar tab done; next = Phase A; calview learnings"
```

---

## Self-Review

**1. Spec coverage:**
- Events = todos with `due`, not deleted, done-gated → Task 1 ✓
- Week view = 7-col row + event list, day-click filter → Task 4 ✓
- Month view = extend grid, click week → week view → Tasks 3 (build) + 4 (`_on_day_clicked` month branch) + 5 (toggle) ✓
- Nav ‹/›/Today (week & month) → Task 5 ✓
- Show-done toggle (default off, struck-through) → Tasks 1 (filter) + 4 (`line-through`) + 5 (toggle) ✓
- Meeting highlight → Task 4 (`_day_button` border + `_event_row` accent) ✓
- No notes / no model / no migration → enforced in Global Constraints + Task 1 ✓
- Shell tab wiring (additive, LOW risk) + click-through → Task 6 ✓
- Tests headless, suite green → every task + Task 7 ✓

**2. Placeholder scan:** No TBD/TODO. The two latitude points (TodosView focus method in Task 6; the walrus-rewrite note in Task 3) are explicit, bounded instructions, not gaps.

**3. Type consistency:** `CalEvent`/`DayCell`/`CalGrid` field names and the `collect_events`/`build_week`/`build_month(events, anchor, now)` signatures match across Tasks 1–6. `_shift_month`, `_on_day_clicked`, `open_todo` names are consistent between view and shell. `_WEEKDAYS` indexing uses Monday=0 (matches `date.weekday()` and `firstweekday=0`).
