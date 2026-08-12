"""
============================================================
Author:  Berk
Created: 2026-07-08
Purpose: ReminderPicker widget — 5 checkboxes for reminder rungs, bound to due date.
Role:    Used by TodoCard (🔔 popover menu) and QuickTodoDialog (row). Shows which
         reminder rungs are available based on the current due date, disables past
         rungs, dims already-fired rungs (but keeps them toggleable). Emits changed
         signal with selected offsets on toggle.

Classes:
- ReminderPicker - five checkboxes (RUNG_LABELS order), refresh on due, changed signal
============================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core import reminders
from ..core.models import Todo
from .theme import COLORS


# Short forms for a narrow host (the capture bubble); RUNG_LABELS stay the default.
_COMPACT_LABELS = {10080: "1w", 1440: "1d", 60: "1h", 30: "30m", 5: "5m"}


class ReminderPicker(QWidget):
    """Five checkboxes for reminder rungs, bound to a due_provider callable.

    Shows which rungs are armable based on the current due time. Disables all if
    no due date or due is too soon. Dims already-fired rungs but keeps them toggleable.

    Signals:
    - changed(list[int]): emitted on any toggle, with current selected() offsets

    Methods:
    - selected() -> list[int]: checked rungs in RUNG_MINUTES order (descending)
    - refresh(): re-evaluate against due_provider() and fired list
    """

    changed = Signal(list)

    def __init__(
        self,
        due_provider: Callable[[], Optional[datetime]],
        initial: list[int] = (),
        fired: list[int] = (),
        parent=None,
        compact: bool = False,
    ):
        super().__init__(parent)
        self.due_provider = due_provider
        self.fired = fired
        self.checkboxes = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._compact = compact     # a 348px dock cannot fit "1 week" x5
        # Five checkboxes in RUNG_MINUTES order (descending: 1 week, 1 day, 1 hour, 30 min, 5 min)
        checks_lay = QHBoxLayout()
        checks_lay.setSpacing(8)
        for rung in reminders.RUNG_MINUTES:
            full = reminders.RUNG_LABELS[rung]
            cb = QCheckBox(_COMPACT_LABELS[rung] if compact else full)
            if compact:
                cb.setToolTip(full)          # the full wording stays reachable on hover
            cb.setChecked(rung in initial)
            cb.toggled.connect(self._on_toggle)
            checks_lay.addWidget(cb)
            self.checkboxes[rung] = cb

        checks_lay.addStretch(1)
        lay.addLayout(checks_lay)

        # Stylesheet for dimmed checkboxes (fired rungs keep their color muted)
        self.setStyleSheet(f'QCheckBox[dimmed="true"] {{ color: {COLORS["ink3"]}; }}')

        # Hint label
        self.hint = QLabel()
        self.hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")
        lay.addWidget(self.hint)

    def selected(self) -> list[int]:
        """Return checked rungs in RUNG_MINUTES (descending) order."""
        result = []
        for rung in reminders.RUNG_MINUTES:
            if self.checkboxes[rung].isChecked():
                result.append(rung)
        return result

    def _on_toggle(self, _):
        """Any checkbox toggled: emit changed with current selection."""
        self.changed.emit(self.selected())

    def refresh(self) -> None:
        """Re-evaluate which rungs are enabled, based on due_provider() and fired list."""
        due = self.due_provider()

        if due is None:
            # No due date: all disabled, show hint
            for cb in self.checkboxes.values():
                cb.setEnabled(False)
            self.hint.setText("Set a due date to add reminders")
            return

        # Compute armable rungs (those whose fire time is still in the future)
        now = datetime.now()
        synthetic_todo = Todo(due=due, reminder_offsets=reminders.RUNG_MINUTES)
        armable = reminders.armable_offsets(synthetic_todo, now)

        # If no armable rungs (due is too soon or overdue), disable all
        if not armable:
            for cb in self.checkboxes.values():
                cb.setEnabled(False)
            self.hint.setText("Due too soon for a reminder")
            return

        # Enable only armable rungs; disable past rungs
        for rung, cb in self.checkboxes.items():
            cb.setEnabled(rung in armable)

        # Apply dimmed style to fired rungs (dynamic property requires unpolish/polish)
        for rung, cb in self.checkboxes.items():
            if rung in self.fired:
                cb.setProperty("dimmed", True)
            else:
                cb.setProperty("dimmed", False)
            # Re-polish so the stylesheet rule recognizes the updated property
            cb.style().unpolish(cb)
            cb.style().polish(cb)

        self.hint.setText("")
