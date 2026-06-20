"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Focus / Pomodoro timer strip shown next to Serenity (UI for core.pomodoro).
Role:    Picking the "Focus" activity reveals this strip: a 25/5 focus-break countdown
         (core.pomodoro.Pomodoro - the pure, clock-injected state machine) driven by a 1s
         QTimer. Click it to start / pause / resume; a small stop control ends the session.
         When a phase elapses it emits phase_changed so the shell can have Serenity comment.
         The widget only RENDERS phase + remaining seconds and forwards clicks; all timing
         logic stays in the pure state machine.

Classes:
- FocusWidget - the focus-session strip (set_active / start; ticks via QTimer)
============================================================
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..core.pomodoro import Phase, Pomodoro
from . import icons
from .theme import COLORS

# Phase -> (human label, accent color) for the strip.
_PHASE_STYLE = {
    Phase.IDLE: ("Focus", COLORS["cyan"]),
    Phase.FOCUS: ("Focus", COLORS["cyan"]),
    Phase.BREAK: ("Break", "#86efac"),
    Phase.LONG_BREAK: ("Long break", "#86efac"),
}


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class FocusWidget(QWidget):
    """A click-to-control Pomodoro strip; hidden until the Focus activity is picked."""

    # (phase value, comment text) when a phase auto-advances.
    phase_changed = Signal(str, str)

    def __init__(self, voice, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("focusStrip")
        self.voice = voice
        self.settings = settings
        self.pomo = Pomodoro()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(8)

        self.icon = QLabel()
        self.icon.setPixmap(icons.pixmap("timer", COLORS["cyan"], 14))
        self.phase_label = QLabel("Focus")
        self.phase_label.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11px;")
        self.time_label = QLabel("25:00")
        self.time_label.setStyleSheet(f"color:{COLORS['ink']}; font-size:13px; font-weight:600;")
        # The whole strip is clickable (start / pause / resume).
        self.action_hint = QLabel("click to start")
        self.action_hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")

        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("iconbtn")
        self.stop_btn.setIcon(icons.icon("close", COLORS["ink3"], 13))
        self.stop_btn.setFixedSize(22, 22)
        self.stop_btn.setToolTip("End focus session")
        self.stop_btn.clicked.connect(self.stop)

        lay.addWidget(self.icon)
        lay.addWidget(self.phase_label)
        lay.addStretch(1)
        lay.addWidget(self.action_hint)
        lay.addWidget(self.time_label)
        lay.addWidget(self.stop_btn)

        self.setCursor(Qt.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.hide()
        self._render()

    @property
    def _lang(self) -> str:
        return getattr(self.settings, "language", "en")

    def set_active(self, active: bool) -> None:
        """Show/hide the strip. Hiding ends any running session."""
        if active:
            self.show()
        else:
            self.stop()
            self.hide()

    def start(self) -> None:
        """Reveal the strip and begin a fresh focus session."""
        self.show()
        self.pomo.start(datetime.now())
        if not self._timer.isActive():
            self._timer.start()
        self._render()

    def stop(self) -> None:
        self.pomo.stop()
        if self._timer.isActive():
            self._timer.stop()
        self._render()

    # --- click toggles start / pause / resume ---
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle()
        super().mousePressEvent(e)

    def _toggle(self) -> None:
        now = datetime.now()
        if self.pomo.phase == Phase.IDLE:
            self.pomo.start(now)
            if not self._timer.isActive():
                self._timer.start()
        elif self.pomo.paused:
            self.pomo.resume(now)
        elif self.pomo.running:
            self.pomo.pause(now)
        self._render()

    def _tick(self) -> None:
        now = datetime.now()
        changed = self.pomo.tick(now)
        if changed is not None:
            self.phase_changed.emit(changed.value, self._comment_for(changed))
        self._render()

    def _comment_for(self, phase: Phase) -> str:
        """A template comment for a phase transition (house style, single hyphen)."""
        if phase == Phase.FOCUS:
            return "Break is over - back to focus." if self._lang == "en" else \
                "Pause vorbei - zurueck zum Fokus."
        if phase == Phase.LONG_BREAK:
            return "Four focus blocks done - take a longer break." if self._lang == "en" else \
                "Vier Bloecke geschafft - mach eine laengere Pause."
        # short break
        return "Focus block done - take a 5 minute break." if self._lang == "en" else \
            "Block geschafft - 5 Minuten Pause."

    def _render(self) -> None:
        label, color = _PHASE_STYLE.get(self.pomo.phase, ("Focus", COLORS["cyan"]))
        remaining = self.pomo.remaining_seconds(datetime.now())
        if self.pomo.phase == Phase.IDLE:
            self.time_label.setText(_mmss(self.pomo.focus_minutes * 60))
            self.action_hint.setText("click to start")
        else:
            self.time_label.setText(_mmss(remaining))
            self.action_hint.setText("paused - click to resume" if self.pomo.paused
                                     else "click to pause")
        self.phase_label.setText(label)
        self.phase_label.setStyleSheet(f"color:{color}; font-size:11px;")
        self.icon.setPixmap(icons.pixmap("timer", color, 14))
