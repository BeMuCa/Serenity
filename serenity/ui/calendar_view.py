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

from datetime import date, datetime, timedelta

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.calview import build_month, build_week, collect_events
from ..core.ics import todos_to_ics, parse_ics, reconcile, decode_ics_bytes
from ..core.models import Todo
from ..core.paths import atomic_write_text
from .ics_import_dialog import ImportPreviewDialog
from .theme import COLORS

ICS_MAX_BYTES = 5 * 1024 * 1024

_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


class CalendarView(QWidget):
    """Renders todo deadlines on a Mon-Sun grid (week or month), event list below."""

    open_todo = Signal(str)  # emits a todo id when an event row is clicked
    expand_requested = Signal()  # the shell opens the week pop-out for the current week
    wrote = Signal()   # a confirmed import landed -> shell fans a cross-surface refresh

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

        # the period label sits in the header row between the nav arrows
        self._label = QLabel()
        self._label.setObjectName("sectLabel")

        # --- header: prev/next nav, the period label, Today, month toggle, show-done ---
        header = QHBoxLayout()
        header.setSpacing(6)
        self._prev_btn = QPushButton("<")
        self._next_btn = QPushButton(">")
        self._today_btn = QPushButton("Today")
        self._mode_btn = QPushButton("Month")
        self._done_btn = QPushButton("Show done")
        self._done_btn.setCheckable(True)
        self.export_btn = QPushButton("⤓ ICS")
        self.import_btn = QPushButton("⤒ ICS")
        self.expand_btn = QPushButton("⤢")  # expand the week into the pop-out
        for b in (self._prev_btn, self._next_btn, self._today_btn, self._mode_btn,
                  self._done_btn, self.export_btn, self.import_btn, self.expand_btn):
            b.setObjectName("tab")
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        self._today_btn.clicked.connect(self._go_today)
        self._mode_btn.clicked.connect(self._toggle_mode)
        self._done_btn.toggled.connect(self._toggle_done)
        self.export_btn.clicked.connect(self._export_ics)
        self.import_btn.clicked.connect(self._import_ics)   # handler arrives in Task 9
        self.expand_btn.clicked.connect(self.expand_requested)
        header.addWidget(self._prev_btn)
        header.addWidget(self._label, 1)
        header.addWidget(self._next_btn)
        header.addWidget(self._today_btn)
        header.addWidget(self._mode_btn)
        header.addWidget(self._done_btn)
        header.addWidget(self.export_btn)
        header.addWidget(self.import_btn)
        header.addWidget(self.expand_btn)
        root.addLayout(header)

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

    # ---- ICS export / import ----
    def _export_ics(self):
        exportable = [t for t in self.todo_store.all()
                      if t.due is not None and not t.done and not t.deleted]
        if not exportable:
            QMessageBox.information(self, "Export calendar",
                                    "No active todos with a due date to export.")
            return
        default = f"serenity-calendar-{datetime.now().strftime('%Y-%m-%d')}.ics"
        path, _ = QFileDialog.getSaveFileName(self, "Export calendar", default,
                                              "iCalendar (*.ics)")
        if not path:
            return
        if not path.lower().endswith(".ics"):
            path += ".ics"
        text = todos_to_ics(exportable, datetime.now())
        try:
            atomic_write_text(Path(path), text)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed",
                                f"Could not write the calendar file:\n{exc}")
            return
        QMessageBox.information(self, "Export calendar",
                                f"Exported {len(exportable)} event(s).")

    def _import_ics(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import calendar", "",
                                              "iCalendar (*.ics)")
        if not path:
            return
        p = Path(path)
        try:
            if p.stat().st_size > ICS_MAX_BYTES:
                QMessageBox.warning(self, "Import calendar",
                                    "That file is too large to import (over 5 MB).")
                return
            with open(p, "rb") as f:
                raw = f.read(ICS_MAX_BYTES + 1)
        except OSError as exc:
            QMessageBox.warning(self, "Import calendar", f"Could not read the file:\n{exc}")
            return
        if len(raw) > ICS_MAX_BYTES:
            QMessageBox.warning(self, "Import calendar",
                                "That file is too large to import (over 5 MB).")
            return
        try:
            text = decode_ics_bytes(raw)
        except ValueError:
            QMessageBox.warning(self, "Import calendar",
                                "That file is not readable text / a valid .ics file.")
            return
        parsed = parse_ics(text)
        if not parsed.is_calendar:
            QMessageBox.warning(self, "Import calendar",
                                "That doesn't look like a calendar (.ics) file.")
            return
        plan = reconcile(parsed, self.todo_store.all())
        if not plan.to_create and not plan.to_update:
            msg = "No importable events found."
            if plan.skipped:
                msg += "\n\nSkipped:\n" + "\n".join(
                    f"• {lbl}: {why}" for lbl, why in plan.skipped[:20])
            QMessageBox.information(self, "Import calendar", msg)
            return
        if ImportPreviewDialog(plan, self).exec() != QDialog.Accepted:
            return
        self._apply_import(plan)

    def _apply_import(self, plan):
        store = self.todo_store
        live = {t.id: t for t in store.all() if not t.done and not t.deleted}
        by_uid = {t.ics_uid: t for t in store.all() if t.ics_uid and not t.done and not t.deleted}
        for ev in plan.to_create:
            target = live.get(ev.uid) or by_uid.get(ev.uid)   # re-resolve a now-existing UID
            if target is not None:
                self._apply_fields(target, ev); store.update(target, persist=False)
            else:
                store.add(Todo(title=ev.title, due=ev.when, category=ev.category,
                               ics_uid=ev.uid), persist=False)
        for todo, ev in plan.to_update:
            cur = live.get(todo.id)
            if cur is None:                                    # purged while the modal was open
                continue
            self._apply_fields(cur, ev); store.update(cur, persist=False)
        try:
            store.save()
        except OSError as exc:
            store.reload()                                     # drop the in-memory changes
            QMessageBox.warning(self, "Import failed", f"Could not save:\n{exc}")
            return
        self.wrote.emit()

    @staticmethod
    def _apply_fields(todo, ev):
        todo.due = ev.when
        todo.title = ev.title
        todo.category = ev.category

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
        btn = QPushButton()
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
            hint = QLabel("Click a week to open it.")
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
