"""
============================================================
Author:  Berk
Created: 2026-06-29
Purpose: CalendarWeekPanel - the read-only Teams-style expanded week time-grid that lives inside
         an ExpandedPanel for the Calendar-expand pop-out (slice a).
Role:    The thin UI layer of Calendar-expand: it RENDERS the core.calview.TimeGrid (7 day columns
         x 24 hour rows + an all-day strip) and a read-only right-hand list of active todos, plus
         week nav. All bucketing/layout is core.calview.build_timegrid; this widget owns only the
         widgets, the week anchor, and the click-through signal. READ-ONLY - never writes the store.

Classes:
- CalendarWeekPanel - day x hour grid in a QScrollArea + all-day strip + active-todo list + week nav;
  open_todo = Signal(str) on event click; refresh()/on_panel_activated()/handle_close() seams
============================================================
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import partial

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

from ..core.calview import build_timegrid, collect_events
from .calendar_view import _WEEKDAYS   # reuse the sibling's weekday labels (one source, no drift)
from .theme import COLORS

_ROW_H = 38          # pixel height of one hour row (used to scroll to ~08:00 on first show)
_SCROLL_HOUR = 8     # the working-hours window the viewport opens on


class CalendarWeekPanel(QWidget):
    """Renders one Mon-Sun week as a day x hour grid + all-day strip + active-todo list.

    Read-only: clicking an event emits open_todo(todo_id) for the shell to deep-link to the Todos
    tab; empty slots and the right list are inert in slice (a). build_timegrid does all bucketing;
    refresh() re-reads the store and repaints."""

    open_todo = Signal(str)  # emits a todo id when an event block is clicked

    def __init__(self, todo_store, parent=None):
        super().__init__(parent)
        self.todo_store = todo_store
        self._anchor: date = datetime.now().date()
        self._grid = None                 # the latest TimeGrid (set by refresh)
        self._scrolled = False            # scroll-to-08:00 happens once, on first show

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- header: prev/next nav, the week label, Today ---
        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 8)
        header.setSpacing(6)
        self._prev_btn = QPushButton("<")
        self._next_btn = QPushButton(">")
        self._today_btn = QPushButton("Today")
        self._label = QLabel()
        self._label.setObjectName("sectLabel")
        for b in (self._prev_btn, self._next_btn, self._today_btn):
            b.setObjectName("tab")
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        self._today_btn.clicked.connect(self._go_today)
        header.addWidget(self._prev_btn)
        header.addWidget(self._label, 1)
        header.addWidget(self._next_btn)
        header.addWidget(self._today_btn)
        root.addLayout(header)

        # --- body: [ grid (scrollable) | active-todo list ] side by side ---
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)

        # all-day strip, pinned above the scrollable hour grid
        self._allday_host = QWidget()
        self._allday = QGridLayout(self._allday_host)
        self._allday.setContentsMargins(4, 2, 4, 2)
        self._allday.setSpacing(2)
        left.addWidget(self._allday_host)

        # the day x hour grid inside a scroll area (full 24h; viewport opens on ~08:00)
        self._grid_host = QWidget()
        self._gridlay = QGridLayout(self._grid_host)
        self._gridlay.setContentsMargins(4, 0, 4, 4)
        self._gridlay.setSpacing(2)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidget(self._grid_host)
        left.addWidget(self._scroll, 1)
        body.addLayout(left, 1)

        # the read-only right-hand active-todo list (inert in slice (a))
        self._list_host = QWidget()
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(8, 8, 8, 8)
        self._list.setSpacing(6)
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QFrame.NoFrame)
        list_scroll.setFixedWidth(220)
        list_scroll.setWidget(self._list_host)
        body.addWidget(list_scroll)
        root.addLayout(body, 1)

        self.refresh()

    # ---- lifecycle / refresh seams (host ExpandedPanel calls these) ----
    def on_panel_activated(self) -> None:
        """The pop-out window became active - re-read the store (R1). The detached-window analogue
        of 'refresh on tab re-entry'; covers every mutation source (edit, done, delete, capture)."""
        self.refresh()

    def handle_close(self) -> bool:
        """Read-only: nothing to lose, so a close always proceeds.
        Revisit in slice (b): drag-scheduling adds an in-flight write that must be resolved here."""
        return True

    # ---- week nav ----
    def _go_prev(self):
        self._anchor = self._anchor - timedelta(days=7)
        self.refresh()

    def _go_next(self):
        self._anchor = self._anchor + timedelta(days=7)
        self.refresh()

    def _go_today(self):
        self._anchor = datetime.now().date()
        self.refresh()

    # ---- rendering ----
    def refresh(self) -> None:
        events = collect_events(self.todo_store.all(), show_done=False)
        self._grid = build_timegrid(events, self._anchor)
        self._label.setText(self._grid.label)
        self._render_allday(self._grid)
        self._render_grid(self._grid)
        self._render_list()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_allday(self, grid):
        self._clear(self._allday)
        corner = QLabel("all-day")
        corner.setStyleSheet(f"color:{COLORS['ink3']}; font-size:9.5px;")
        self._allday.addWidget(corner, 0, 0)
        for col, day in enumerate(grid.days, start=1):
            wrap = QWidget()
            cell = QVBoxLayout(wrap)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            for e in grid.all_day.get(day, []):
                cell.addWidget(self._event_block(e))
            self._allday.addWidget(wrap, 0, col)

    def _render_grid(self, grid):
        self._clear(self._gridlay)
        # per-day "is today" computed once here, not re-derived in each of the 168 hour-cells
        is_today = {d: (grid.today is not None and d == grid.today) for d in grid.days}
        # day-name header row (row 0); the hour-label column is column 0
        for col, day in enumerate(grid.days, start=1):
            head = QLabel(f"{_WEEKDAYS[day.weekday()]} {day.day}")
            head.setAlignment(Qt.AlignCenter)
            color = COLORS["accent"] if is_today[day] else COLORS["ink3"]
            weight = "700" if is_today[day] else "400"
            head.setStyleSheet(f"color:{color}; font-size:10px; font-weight:{weight};")
            self._gridlay.addWidget(head, 0, col)
        # hour rows
        for hour in grid.hours:
            r = hour + 1
            hr = QLabel(f"{hour:02d}:00")
            hr.setAlignment(Qt.AlignRight | Qt.AlignTop)
            hr.setStyleSheet(f"color:{COLORS['ink3']}; font-size:9.5px;")
            self._gridlay.addWidget(hr, r, 0)
            for col, day in enumerate(grid.days, start=1):
                self._gridlay.addWidget(self._hour_cell(grid, day, hour, is_today[day]), r, col)

    def _hour_cell(self, grid, day: date, hour: int, is_today: bool) -> QWidget:
        cell = QFrame()
        cell.setObjectName("calcell")
        bg = COLORS["accent_soft"] if is_today else "transparent"
        cell.setStyleSheet(
            f"QFrame#calcell{{border:1px solid {COLORS['line']}; border-radius:4px;"
            f" background:{bg};}}"
        )
        cell.setMinimumHeight(_ROW_H)
        lay = QVBoxLayout(cell)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(1)
        for e in grid.cells.get((day, hour), []):
            lay.addWidget(self._event_block(e))
        lay.addStretch(1)
        return cell

    def _event_block(self, e) -> QPushButton:
        """A small clickable block: HH:MM title, with a meeting-category accent.

        A QPushButton (not a QLabel + mousePressEvent override): the click-through is wired with
        a Qt-side clicked->open_todo connection so it carries no Python self<->widget reference
        cycle (a mousePressEvent bound-lambda would, and PySide6 segfaults GC-collecting one across
        the 168 cells this grid builds)."""
        when = e.when.strftime("%H:%M") if e.has_time else "all-day"
        block = QPushButton(f"{when} {e.title}")
        block.setObjectName("calblock")
        meeting = e.category == "meeting"
        fg = COLORS["accent"] if meeting else COLORS["ink"]
        border = COLORS["accent"] if meeting else COLORS["line2"]
        block.setStyleSheet(
            f"QPushButton#calblock{{color:{fg}; font-size:10px; padding:1px 4px; text-align:left;"
            f" border:1px solid {border}; border-radius:4px;"
            f" background:{COLORS['accent_soft'] if meeting else COLORS['panel2']};}}"
        )
        block.setToolTip(e.title)
        block.clicked.connect(partial(self.open_todo.emit, e.todo_id))
        return block

    def _render_list(self):
        self._clear(self._list)
        head = QLabel("Active todos")
        head.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")
        self._list.addWidget(head)
        actives = self.todo_store.active()
        if not actives:
            empty = QLabel("Nothing active.")
            empty.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
            self._list.addWidget(empty)
        for t in actives:
            self._list.addWidget(self._list_row(t))
        self._list.addStretch(1)

    def _list_row(self, t) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(6)
        title = QLabel(t.title)
        title.setStyleSheet(f"color:{COLORS['ink']}; font-size:11.5px;")
        lay.addWidget(title, 1)
        return card

    # ---- first-show: open the viewport on the working-hours window ----
    def showEvent(self, e):
        super().showEvent(e)
        if not self._scrolled:
            self._scrolled = True               # once only: a later re-show must not clobber scroll
            self._scroll_to_working_hours()

    def _scroll_to_working_hours(self) -> None:
        self._scroll.verticalScrollBar().setValue(_SCROLL_HOUR * _ROW_H)
