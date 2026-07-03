"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The compact "Mini" window mode - a small always-on-top dock (Serenity + one todo).
Role:    One of the three window modes (Full / Mini / Hidden, spec sec 4 / Build Decisions).
         Mini shrinks Serenity to a tiny always-on-top widget showing only the avatar
         (clickable -> the activity selector, same MascotStage) and the single most-actionable
         todo chosen by core.window_mode.mini_todos (top / urgent, blocked ones dropped).
         Read-only apart from the activity selector; clicking the todo or the restore control
         brings the full dock back. The shell owns the stores and toggles modes.

Classes:
- MiniWindow - the compact frameless always-on-top mini-dock
============================================================
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.ranking import peek_class
from ..core.states import visible
from ..core.window_mode import mini_todos
from . import icons
from .peek_placeholder import blurred_line
from .mascot_stage import MascotStage
from .theme import COLORS, stylesheet

MINI_WIDTH = 232


class _PeekLine(QLabel):
    """The clickable blurred peek line (R-H): click = context toggle, no other affordance."""

    clicked = Signal()

    def mousePressEvent(self, e):         # noqa: N802 (Qt override)
        self.clicked.emit()


class MiniWindow(QWidget):
    """A tiny always-on-top dock: Serenity (click to pick activity) + the top todo."""

    # bubbled up so the shell can react with the same handlers as the full stage.
    activity_changed = Signal(str)
    restore_requested = Signal()
    context_toggle_requested = Signal()

    def __init__(self, todo_store, settings, parent=None):
        super().__init__(parent)
        self.todo_store = todo_store
        self.settings = settings
        self.setObjectName("dock")
        self.setWindowTitle("Serenity")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(stylesheet(settings.accent))
        self.setFixedWidth(MINI_WIDTH)
        self._drag = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # tiny title strip with a restore-to-full control
        strip = QFrame()
        strip.setObjectName("titleBar")
        strip.setFixedHeight(28)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(10, 0, 6, 0)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background:{COLORS['accent']}; border-radius:3px;")
        brand = QLabel("Serenity")
        brand.setObjectName("brand")
        sl.addWidget(dot)
        sl.addWidget(brand)
        sl.addStretch(1)
        restore_btn = QPushButton()
        restore_btn.setObjectName("iconbtn")
        restore_btn.setIcon(icons.icon("restore", COLORS["ink2"], 13))
        restore_btn.setFixedSize(22, 22)
        restore_btn.setToolTip("Back to full window")
        restore_btn.clicked.connect(self.restore_requested.emit)
        sl.addWidget(restore_btn)
        self._strip = strip
        root.addWidget(strip)

        # the one most-actionable todo
        self.todo_card = QFrame()
        self.todo_card.setObjectName("card")
        tl = QVBoxLayout(self.todo_card)
        tl.setContentsMargins(10, 7, 10, 7)
        tl.setSpacing(2)
        self.todo_kicker = QLabel("UP NEXT")
        self.todo_kicker.setStyleSheet(f"color:{COLORS['ink3']}; font-size:9px; letter-spacing:1px;")
        self.todo_label = QLabel("All clear")
        self.todo_label.setWordWrap(True)
        self.todo_label.setStyleSheet(f"color:{COLORS['ink']}; font-size:12px;")
        tl.addWidget(self.todo_kicker)
        tl.addWidget(self.todo_label)
        # urgency-peek (R-H): the title-free blurred line for a cross-context urgent
        # todo - this card must never claim "All clear" while one exists. Clicking it
        # toggles the context (this window IS the toggle surface, so one click is fine).
        self.peek_label = _PeekLine()
        self.peek_label.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11px;")
        self.peek_label.clicked.connect(self.context_toggle_requested.emit)
        self.peek_label.hide()
        tl.addWidget(self.peek_label)
        wrap = QWidget()
        wlay = QVBoxLayout(wrap)
        wlay.setContentsMargins(8, 6, 8, 0)
        wlay.addWidget(self.todo_card)
        root.addWidget(wrap)

        # the mascot stage (re-used: handles click-to-select + emits activity_changed)
        self.mascot = MascotStage(settings)
        self.mascot.setMinimumHeight(150)
        self.mascot.activity_changed.connect(self.activity_changed.emit)
        self.mascot.context_toggle_requested.connect(self.context_toggle_requested.emit)
        root.addWidget(self.mascot)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(30_000)
        self._refresh_timer.timeout.connect(self.refresh_todo)
        self.refresh_todo()

    def refresh_todo(self) -> None:
        """Show the single top/urgent actionable todo (core.window_mode.mini_todos).
        The pick respects the context axis (Phase C R13) - the always-on-top card must
        never surface an other-context title (the toggle sits on this very window).
        An urgent OTHER-context todo shows as the title-free blurred peek line (R-H)
        instead of this card lying "All clear"."""
        now = datetime.now()
        ctx = self.settings.context()
        actives = [t for t in self.todo_store.all() if not t.done and not t.deleted]
        picks = mini_todos([t for t in actives if visible(t, ctx)], now=now, limit=1)
        blurred = [t for t in actives if peek_class(t, ctx, None, now) == "peek_blurred"]
        if blurred:
            b = min(blurred, key=lambda t: t.due or datetime.max)   # soonest deadline first
            self.peek_label.setText(blurred_line(b, (b.context or "").capitalize(), now))
            self.peek_label.show()
        else:
            self.peek_label.hide()
        if picks:
            self.todo_label.setText(picks[0].title)
            self.todo_kicker.show()
        elif blurred:
            self.todo_label.setText("")                             # the peek line IS the surface
            self.todo_kicker.hide()
        else:
            self.todo_label.setText("All clear - nothing actionable.")
            self.todo_kicker.hide()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_todo()
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()

    # drag the frameless mini-dock by its title strip
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._strip.geometry().contains(e.position().toPoint()):
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)
