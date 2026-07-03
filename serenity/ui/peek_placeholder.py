"""
============================================================
Author:  Berk
Created: 2026-07-03
Purpose: The privacy-blurred placeholder for cross-context urgent todos (urgency-peek).
Role:    Rendered by TodosView instead of a TodoCard when a todo is urgent but belongs
         to the OTHER context: shows only relative time-left + a lock + the context
         label - never the title/details. Two-click armed confirm flips the global
         context to reveal the real todo (R-D); ticks like a card so the countdown
         stays live (R-B). Phase H's reminder snooze will anchor here later.

Functions:
- blurred_line(todo, context_label, now) - the shared title-free text (R-E/R-F)

Classes:
- PeekPlaceholder - read-only blurred row: needs_tick()/tick(now) + reveal_requested
============================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QElapsedTimer, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QWidget

from ..core.ranking import format_time_left

DISARM_MS = 3000        # the armed "Switch to <ctx>?" prompt auto-reverts after this


def blurred_line(todo, context_label: str, now: Optional[datetime] = None) -> str:
    """The title-free blurred text for one cross-context urgent todo (R-E/R-F).

    Shared by the Todos-list placeholder and the mini dock's peek line so the privacy
    rules live in ONE place: relative time only, never the title/details, never "None",
    never elapsed timer seconds."""
    suffix = f"🔒 {context_label} item"
    if todo.due is not None:
        return f"⏰ {format_time_left(todo.due, now or datetime.now())} · {suffix}"
    if todo.timer_running:
        return f"▶ running · {suffix}"
    return f"● in progress · {suffix}"


class PeekPlaceholder(QWidget):
    """A blurred stand-in for one cross-context urgent todo (no title, no details).

    Content forms (R-E): "⏰ <relative time-left> · 🔒 <ctx> item" when due is set;
    "▶ running · 🔒 <ctx> item" for a running timer without a due; "● in progress ·
    🔒 <ctx> item" otherwise. Never absolute clock times, never "None", never elapsed
    timer seconds. First click ARMS a confirm prompt (auto-disarms); only a second
    click past the double-click interval emits reveal_requested (R-D)."""

    reveal_requested = Signal()

    def __init__(self, todo, context_label: str, parent=None,
                 now: Optional[datetime] = None):
        super().__init__(parent)
        self.todo = todo
        self._context_label = context_label
        self._armed = False
        self._arm_clock = QElapsedTimer()
        self._disarm_timer = QTimer(self)
        self._disarm_timer.setSingleShot(True)
        self._disarm_timer.setInterval(DISARM_MS)
        self._disarm_timer.timeout.connect(self._disarm)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QFrame()
        row.setObjectName("card")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(9, 6, 9, 6)
        self.label = QLabel()
        rl.addWidget(self.label)
        rl.addStretch(1)
        lay.addWidget(row)
        self._render(now)

    # ---- content (R-E/R-F: relative-only, nothing identifying) ----
    def _render(self, now: Optional[datetime] = None) -> None:
        self.label.setText(blurred_line(self.todo, self._context_label, now))

    # ---- tick protocol (R-B: same shape as TodoCard, so the view's 1s tick serves us) ----
    def needs_tick(self) -> bool:
        return True                       # exists only for urgent items - always live

    def tick(self, now: datetime) -> None:
        if not self._armed:               # never clobber the armed confirm prompt
            self._render(now)

    # ---- two-click armed confirm (R-D) ----
    def _confirm_gate_open(self) -> bool:
        """A confirm click within the double-click interval of arming is an accidental
        double-click, not a decision - ignore it (mis-click can never flip context)."""
        return self._arm_clock.elapsed() > QApplication.doubleClickInterval()

    def mousePressEvent(self, e):         # noqa: N802 (Qt override)
        if not self._armed:
            self._armed = True
            self._arm_clock.start()
            self._disarm_timer.start()
            self.label.setText(f"Switch to {self._context_label}?")
        elif self._confirm_gate_open():
            self._disarm()
            self.reveal_requested.emit()

    def _disarm(self) -> None:
        self._armed = False
        self._disarm_timer.stop()
        self._render()
