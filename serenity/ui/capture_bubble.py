"""
============================================================
Author:  Berk
Created: 2026-08-10
Purpose: The Quick-todo bubble - an in-dock capture popup that grows out of the
         "Quick todo" button, with a multi-line title and real date + time pickers.
Role:    Replaces the OS-decorated Quick-todo dialog on the capture-bar path. It is a
         CHILD WIDGET of the dock, not a window: that kills the native title bar, and it
         is also the only placement that works under Wayland (where a client may not
         position its own windows). Saving goes through modals.save_quick_todo, the same
         helper QuickTodoDialog uses, so the two entry points cannot drift apart.

Classes:
- GrowingTextEdit - one-line-tall title input that grows with the text (Enter saves,
  Shift+Enter makes a new line); exposes text()/setText() so it drops into QLineEdit code
- CaptureBubble - the bubble: title + "Due" date/time + reminder rungs + Add; closes on
  Esc, on a click outside itself, or after a successful save
============================================================
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QEvent, QPoint, QSize, Qt, QTime, Signal
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import (QApplication, QCheckBox, QDateEdit, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QTimeEdit, QVBoxLayout)

from ..core.parser import parse_capture
from .modals import save_quick_todo
from .reminder_picker import ReminderPicker
from .theme import COLORS

CARET = 7            # height of the little triangle that points at the anchor button


class GrowingTextEdit(QPlainTextEdit):
    """A title field that is one line tall until the text needs more room."""

    submitted = Signal()

    def __init__(self, placeholder: str = "", max_lines: int = 6, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self._max_lines = max_lines
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _size: self._fit())
        self._fit()

    # QLineEdit-compatible accessors, so callers read like the field they replaced
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:
        self.setPlainText(value)

    def line_count(self) -> int:
        """Visual lines the text currently occupies, wrapped lines included.

        QPlainTextDocumentLayout reports documentSize().height() in LINES, not pixels (a
        QTextEdit would report pixels) - dividing it by the line height collapses every
        length to 1."""
        return max(1, int(self.document().documentLayout().documentSize().height()))

    def _fit(self) -> None:
        lines = min(self.line_count(), self._max_lines)
        frame = int(self.document().documentMargin() * 2) + 2 * self.frameWidth() + 8
        self.setFixedHeight(self.fontMetrics().lineSpacing() * lines + frame)

    def keyPressEvent(self, e):  # noqa: N802 (Qt override)
        # Enter saves (this is a capture field, not an editor); Shift+Enter breaks the line.
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class CaptureBubble(QFrame):
    """Quick-todo capture, anchored above its button inside the dock."""

    added = Signal(object)                 # emits the created Todo

    def __init__(self, todo_store, settings, parent=None, stamp=None) -> None:
        super().__init__(parent)
        self.setObjectName("captureBubble")
        self.todo_store = todo_store
        self.settings = settings
        self._stamp = stamp
        self._caret_x = 0                  # where the triangle points (set by open_above)
        self.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 11, 13, 11 + CARET)
        lay.setSpacing(8)

        head = QLabel("Quick todo")
        head.setStyleSheet("font-size:13px; font-weight:600;")
        lay.addWidget(head)

        self.title = GrowingTextEdit("What needs doing?  (Shift+Enter for a new line)")
        self.title.submitted.connect(self._save)
        lay.addWidget(self.title)

        # --- due row: an explicit date + time, so a reminder can actually be armed ---
        due_row = QHBoxLayout()
        due_row.setSpacing(7)
        self.due_check = QCheckBox("Due")
        self.due_check.toggled.connect(self._on_due_toggled)
        now = datetime.now()
        self.date = QDateEdit(QDate(now.year, now.month, now.day))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd d MMM")    # the year does not fit a 348px dock
        self.time = QTimeEdit(QTime(now.hour, 0))
        self.time.setDisplayFormat("HH:mm")
        for w in (self.date, self.time):
            w.setEnabled(False)            # off until "Due" is ticked
        due_row.addWidget(self.due_check)
        due_row.addWidget(self.date, 1)
        due_row.addWidget(self.time)
        lay.addLayout(due_row)

        self.reminder_picker = ReminderPicker(due_provider=self.due_datetime, compact=True)
        self.reminder_picker.refresh()
        for signal in (self.date.dateTimeChanged, self.time.dateTimeChanged):
            signal.connect(lambda _v: self.reminder_picker.refresh())
        lay.addWidget(self.reminder_picker)

        # Meeting-Prep: default OFF, revealed only once the typed title parses as a meeting.
        self.prep_auto = QCheckBox("Auto-prep")
        self.prep_auto.setToolTip(
            "Prepare this meeting automatically the evening before or the morning of: carry "
            "over what the last protocol left open, plus related notes and your open todos.")
        self.prep_auto.hide()
        self.title.textChanged.connect(self._sync_prep_auto)
        lay.addWidget(self.prep_auto)

        self._error = QLabel("Could not save - your disk may be full. Try again.")
        self._error.setStyleSheet("color:#fca5a5; font-size:11px;")
        self._error.setWordWrap(True)
        self._error.hide()
        lay.addWidget(self._error)

        foot = QHBoxLayout()
        hint = QLabel("Enter saves · Esc closes")
        hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        foot.addWidget(hint)
        foot.addStretch(1)
        self.add_btn = QPushButton("Add todo")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self._save)
        foot.addWidget(self.add_btn)
        lay.addLayout(foot)

    # ------------------------------------------------------------------ due
    def _on_due_toggled(self, on: bool) -> None:
        self.date.setEnabled(on)
        self.time.setEnabled(on)
        self.reminder_picker.refresh()      # rungs are only armable with a due date

    def due_datetime(self):
        """The picked due as a naive local datetime, or None while "Due" is unticked.

        Naive-local on purpose: core.ranking compares `due - datetime.now()`, so a
        timezone-aware value here would poison every downstream comparison."""
        if not self.due_check.isChecked():
            return None
        d, t = self.date.date(), self.time.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())

    # ------------------------------------------------------------------ show / hide
    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        return QSize(max(300, base.width()), base.height())

    def open_above(self, anchor) -> None:
        """Place the bubble over its anchor button, inside the dock, and focus the title."""
        parent = self.parentWidget()
        self.due_check.setChecked(False)
        self.title.setText("")
        self._error.hide()
        self.reminder_picker.refresh()
        self.adjustSize()
        width = min(max(self.sizeHint().width(), 300), max(200, parent.width() - 16))
        self.resize(width, self.sizeHint().height())
        top_left = anchor.mapTo(parent, QPoint(0, 0))
        x = top_left.x() + anchor.width() // 2 - width // 2
        x = max(8, min(x, parent.width() - width - 8))
        y = max(8, top_left.y() - self.height() - 2)
        self.move(x, y)
        self._caret_x = max(CARET + 4,
                            min(top_left.x() + anchor.width() // 2 - x, width - CARET - 4))
        self.show()
        self.raise_()
        self.title.setFocus()

    def close_bubble(self) -> None:
        self.hide()

    def showEvent(self, e):  # noqa: N802 (Qt override)
        super().showEvent(e)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, e):  # noqa: N802 (Qt override)
        super().hideEvent(e)
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        """Close on a press anywhere outside the bubble - but never while a drop-down of our
        own (the calendar) is open, since that popup is a separate window."""
        if event.type() == QEvent.MouseButtonPress and self.isVisible():
            if QApplication.activePopupWidget() is None and not self._contains_global(event):
                self.close_bubble()
        return False

    def _contains_global(self, event) -> bool:
        try:
            point = event.globalPosition().toPoint()
        except AttributeError:              # older event shape
            point = event.globalPos()
        return self.rect().contains(self.mapFromGlobal(point))

    def keyPressEvent(self, e):  # noqa: N802 (Qt override)
        if e.key() == Qt.Key_Escape:
            self.close_bubble()
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):  # noqa: N802 (Qt override)
        """Draw the caret so the bubble reads as coming OUT of its button."""
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(COLORS["panel2"]))
        painter.setPen(QColor(COLORS["accent"]))
        bottom = self.height() - 1
        painter.drawPolygon(QPolygon([
            QPoint(self._caret_x - CARET, bottom - CARET),
            QPoint(self._caret_x + CARET, bottom - CARET),
            QPoint(self._caret_x, bottom),
        ]))
        painter.end()

    # ------------------------------------------------------------------ save
    def _sync_prep_auto(self) -> None:
        """Reveal the auto-prep toggle only while the typed title parses as a meeting."""
        text = self.title.text().strip()
        is_meeting = parse_capture(text).category == "meeting" if text else False
        self.prep_auto.setVisible(is_meeting)
        if not is_meeting:
            self.prep_auto.setChecked(False)

    def _save(self) -> None:
        todo = save_quick_todo(self.todo_store, self.settings,
                               title=self.title.text(), due=self.due_datetime(),
                               stamp=self._stamp, rungs=self.reminder_picker.selected(),
                               prep_auto=self.prep_auto.isChecked())
        if todo is None:
            if self.title.text().strip():
                self._error.show()          # the write failed - keep the bubble open
            return
        self.added.emit(todo)
        self.close_bubble()
