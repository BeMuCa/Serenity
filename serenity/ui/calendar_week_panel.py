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

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import reminders
from ..core.calview import _week_start, build_timegrid, collect_events
from ..core.states import visible
from .calendar_view import _WEEKDAYS   # reuse the sibling's weekday labels (one source, no drift)
from .modals import QuickTodoDialog
from .theme import COLORS

_ROW_H = 38          # pixel height of one hour row (used to scroll to ~08:00 on first show)
_SCROLL_HOUR = 8     # the working-hours window the viewport opens on


def _start_id_drag(widget, todo_id: str) -> None:
    """Reuse of TodoCard._begin_drag's body: a QDrag carrying the todo id as plain text.
    Shared by the right-list rows (press gesture) and event-blocks (threshold gesture)."""
    drag = QDrag(widget)
    mime = QMimeData()
    mime.setText(todo_id)
    drag.setMimeData(mime)
    drag.exec(Qt.MoveAction)


class _DropCell(QFrame):
    """An hour cell or all-day-strip cell that accepts a dropped todo id. Cells are rebuilt every
    refresh, so each one carries its own (day, hour) slot; hour is None for the all-day strip. On
    drop it hands (day, hour) back to the panel, which re-resolves the id and writes (H1/H5)."""

    def __init__(self, panel, day: date, hour, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._day = day
        self._hour = hour          # int hour, or None => all-day strip
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._panel._handle_drop(e, self._day, self._hour)

    def mousePressEvent(self, e):
        # slice (b): a left-click on an EMPTY cell creates a todo pre-filled with this slot. A cell
        # holding an event block routes its own click through the block; an empty-space press here
        # opens the create dialog. (Cells with blocks are inert to avoid stealing a near-miss.)
        if e.button() == Qt.LeftButton and not self.findChildren(_EventBlock):
            self._panel._handle_slot_click(self._day, self._hour)
        else:
            super().mousePressEvent(e)


class _EventBlock(QPushButton):
    """A clickable event block that is ALSO a threshold drag source (H7). A plain click still
    deep-links (clicked -> open_todo, gated on not _dragging); a press-then-move past the OS drag
    distance starts a QDrag instead. QDrag is NOT wired to `pressed` - its blocking exec would
    swallow the release and kill the click-through."""

    def __init__(self, todo_id: str, label: str, parent=None):
        super().__init__(label, parent)
        self._todo_id = todo_id
        self._press_pos = None
        self._dragging = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.position()      # QPointF; pos() is deprecated in Qt6
            self._dragging = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press_pos is not None and not self._dragging
                and (e.position() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._dragging = True
            self._start_drag()
            return
        super().mouseMoveEvent(e)

    def _start_drag(self):
        _start_id_drag(self, self._todo_id)


class _ListRow(QFrame):
    """A right-hand active-todo row that is a drag source ONLY (H6): a left-press starts a QDrag
    carrying the todo id. setAcceptDrops stays False so a list->list mis-drop is a clean no-op."""

    def __init__(self, todo_id: str, parent=None):
        super().__init__(parent)
        self._todo_id = todo_id

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            _start_id_drag(self, self._todo_id)
        else:
            super().mousePressEvent(e)


class CalendarWeekPanel(QWidget):
    """Renders one Mon-Sun week as a day x hour grid + all-day strip + active-todo list.

    Clicking an event emits open_todo(todo_id) for the shell to deep-link to the Todos tab; an
    empty slot opens QuickTodoDialog pre-filled with that slot (slice (b); inert when settings is
    None). build_timegrid does all bucketing; refresh() re-reads the store and repaints."""

    open_todo = Signal(str)  # emits a todo id when an event block is clicked
    wrote = Signal()         # slice (b): a drop/create committed a write -> shell fans refresh out

    def __init__(self, todo_store, settings=None, parent=None, stamp=None):
        super().__init__(parent)
        self.todo_store = todo_store
        self._settings = settings         # slice (b): needed by the create dialog; None => create inert
        self._stamp = stamp               # Phase C R11: threaded into the slot-click QuickTodoDialog
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
        """Always proceeds. Slice (b) writes are atomic (a drop commits immediately via
        store.update; a create commits via the modal), so the panel holds no in-flight edit state."""
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
    def _context_todos(self, todos):
        """The context axis (Phase C R13); slice-(a) usage without settings shows all."""
        if self._settings is None:
            return todos
        ctx = self._settings.context()
        return [t for t in todos if visible(t, ctx)]

    def refresh(self) -> None:
        events = collect_events(self._context_todos(self.todo_store.all()), show_done=False)
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
            wrap = _DropCell(self, day, None)        # hour=None => drop sets exact midnight (H5)
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
        cell = _DropCell(self, day, hour)            # drop reschedules to (day, hour) (H5)
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
        block = _EventBlock(e.todo_id, f"{when} {e.title}")   # slice (b): threshold drag source (H7)
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
        # H7: a plain click deep-links; a click that ended a drag does not. Gate the emit on the
        # block's _dragging flag (partial holds the panel signal + block, same no-cycle shape as
        # slice (a)'s direct connect - no bound-lambda capturing the widget twice).
        block.clicked.connect(partial(self._emit_open_todo, block, e.todo_id))
        return block

    def _emit_open_todo(self, block, todo_id: str) -> None:
        """Deep-link on a plain click only - a click that ended a threshold drag is swallowed."""
        if not block._dragging:
            self.open_todo.emit(todo_id)

    def _handle_drop(self, e, day: date, hour) -> None:
        """A todo id was dropped on slot (day, hour) [hour None => all-day strip]. Re-resolve the
        id and skip stale ones (H1): done/deleted/purged accept + self-heal with NO write. On a
        live todo build a clean due (H5), persist via store.update, refresh, and emit wrote."""
        t = self.todo_store.get(e.mimeData().text())
        if t is None or t.done or t.deleted:
            e.acceptProposedAction()
            self.refresh()                       # grid self-heals (a stale block disappears)
            return
        if hour is None:
            t.due = datetime(day.year, day.month, day.day)             # exact midnight (all-day)
        else:
            base = t.due or datetime(day.year, day.month, day.day)     # no-time todo -> minute 0
            t.due = base.replace(year=day.year, month=day.month, day=day.day,
                                 hour=hour, second=0, microsecond=0)    # keep the minute
        if t.reminder_active is not None or t.reminder_nudge_at is not None:
            reminders.silence(t)
        self.todo_store.update(t)
        self.refresh()
        self.wrote.emit()
        e.acceptProposedAction()

    def _handle_slot_click(self, day: date, hour) -> None:
        """An empty slot (day, hour) [hour None => all-day strip] was clicked: open QuickTodoDialog
        pre-filled with this slot as default_due. Inert when settings is absent (slice-(a) usage)."""
        if self._settings is None:
            return
        slot = (datetime(day.year, day.month, day.day) if hour is None
                else datetime(day.year, day.month, day.day, hour))
        dlg = QuickTodoDialog(self.todo_store, self._settings, default_due=slot, parent=self,
                              stamp=self._stamp)
        dlg.added.connect(self._on_created)
        dlg.exec()

    def _on_created(self, todo) -> None:
        """A create committed. H8: if the new todo's due falls outside the shown week, re-anchor to
        its week so the event is visible (a correct write otherwise looks like it failed). Then
        repaint and fan refresh out via wrote."""
        if todo.due is not None and _week_start(todo.due.date()) != _week_start(self._anchor):
            self._anchor = _week_start(todo.due.date())
        self.refresh()
        self.wrote.emit()

    def _render_list(self):
        self._clear(self._list)
        head = QLabel("Active todos")
        head.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")
        self._list.addWidget(head)
        actives = self._context_todos(self.todo_store.active())
        if not actives:
            empty = QLabel("Nothing active.")
            empty.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
            self._list.addWidget(empty)
        for t in actives:
            self._list.addWidget(self._list_row(t))
        self._list.addStretch(1)

    def _list_row(self, t) -> QFrame:
        card = _ListRow(t.id)            # H6: drag source only (mime=t.id), never a drop target
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
