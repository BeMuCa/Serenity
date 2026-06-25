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
