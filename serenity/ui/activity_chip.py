"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Compact "what Serenity is tracking right now" chip (running activity + elapsed).
Role:    Sits just above the mascot stage. When an activity span is running (core.activity
         ActivityLog via core.activity_store) it shows the activity name + a live mm:ss
         elapsed counter, ticking once a second; when nothing is tracked it hides. Read-only
         display - the activity is started/stopped from the mascot's activity selector.

Classes:
- ActivityChip - the compact running-activity indicator (show(entry) / clear() / tick())
============================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..core.activity import ActivityEntry
from .theme import COLORS

# activity label -> the neon dot color used in the selector (kept in step with ACTIVITIES).
_ACTIVITY_COLORS = {
    "Working": "#a78bfa",
    "Coding": "#ff8ad0",
    "Meeting": "#5cc8ff",
    "Planning": "#8fd36a",
    "Entertainment": "#e3b341",
    "Focus": "#19e3ff",
    "Idle": "#19e3ff",
}


def _fmt_elapsed(seconds: int) -> str:
    """Whole seconds -> 'm:ss' under an hour, else 'h:mm:ss'."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class ActivityChip(QWidget):
    """Shows the running activity + a live elapsed counter; hidden when idle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("activityChip")
        self._entry: Optional[ActivityEntry] = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)

        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.name = QLabel("")
        self.name.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11px;")
        self.elapsed = QLabel("")
        self.elapsed.setStyleSheet(f"color:{COLORS['ink']}; font-size:11px; font-weight:600;")
        tracking = QLabel("tracking")
        tracking.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px; letter-spacing:1px;")
        lay.addWidget(self.dot)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(tracking)
        lay.addWidget(self.elapsed)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        self.hide()

    def _color_for(self, label: str) -> str:
        return _ACTIVITY_COLORS.get(label, COLORS["accent"])

    def show_running(self, entry: Optional[ActivityEntry]) -> None:
        """Show the chip for a running span, or hide it when there is none / it is Idle."""
        # A finished span, no span, or an explicit Idle selection means "not tracking".
        if entry is None or entry.end is not None or entry.category == "Idle":
            self.clear()
            return
        self._entry = entry
        color = self._color_for(entry.category)
        self.dot.setStyleSheet(f"background:{color}; border-radius:4px;")
        self.name.setText(entry.category)
        self.tick()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def clear(self) -> None:
        self._entry = None
        if self._timer.isActive():
            self._timer.stop()
        self.hide()

    def tick(self) -> None:
        if self._entry is None:
            return
        self.elapsed.setText(_fmt_elapsed(self._entry.seconds(datetime.now())))
