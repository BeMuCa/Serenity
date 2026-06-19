"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The Serenity stage - animated WebP avatar, speech bubble, activity selector.
Role:    The app's signature widget (the only neon zone). Plays a per-state random
         pose via QMovie, shows what Serenity says, and on click reveals the activity
         selector: category bubbles arc around her, the speech bubble slides out of
         the way, picking one sets the activity + swaps her pose. Esc / re-click closes.

Classes:
- ActivityBubble - a single clickable category bubble
- SpeechBubble - Serenity's comment bubble (+ inline slot-filling answer box)
- MascotStage - the stage: avatar (QMovie), bubble, selector, state machine
============================================================
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..core.poses import PoseSelector

# activity -> mascot state (decisions doc activity model). neon dot color per activity.
ACTIVITIES = [
    ("Working", "working", "#a78bfa"),
    ("Coding", "coding", "#ff8ad0"),
    ("Meeting", "meeting", "#5cc8ff"),
    ("Planning", "planning", "#8fd36a"),
    ("Entertainment", "entertainment", "#e3b341"),
    ("Idle", "idle", "#19e3ff"),
]


class ActivityBubble(QPushButton):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(label, parent)
        self.activity = label
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QPushButton {{
                color: #dfe3f5; background: rgba(16,18,30,0.9);
                border: 1px solid {color}; border-radius: 13px;
                padding: 5px 11px; font-size: 11px;
            }}
            QPushButton:hover {{ border: 1px solid #19e3ff; color: #ffffff; }}
            """
        )


class SpeechBubble(QFrame):
    """Serenity's comment bubble. Can show an inline answer box for slot-filling."""

    answered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("speechBubble")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(3)
        who = QLabel("SERENITY")
        who.setStyleSheet("color:#19e3ff; font-size:9px; letter-spacing:2px;")
        self.say = QLabel("Online und bereit.")
        self.say.setWordWrap(True)
        self.say.setStyleSheet("color:#eef1ff; font-size:13.5px; font-weight:500;")
        self.answer = QLineEdit()
        self.answer.setPlaceholderText("Type your answer, Enter to send")
        self.answer.hide()
        self.answer.returnPressed.connect(self._send)
        lay.addWidget(who)
        lay.addWidget(self.say)
        lay.addWidget(self.answer)
        self._apply_style("#19e3ff")
        self.setMaximumWidth(280)

    def _apply_style(self, color: str):
        self.setStyleSheet(
            f"QFrame#speechBubble {{ background: rgba(10,12,20,0.95); "
            f"border: 1px solid {color}; border-radius: 13px; }}"
        )

    def set_text(self, text: str, color: str = "#19e3ff"):
        self.say.setText(text)
        self._apply_style(color)
        self.answer.hide()
        self.adjustSize()

    def ask(self, text: str, color: str = "#a78bfa"):
        self.say.setText(text)
        self._apply_style(color)
        self.answer.clear()
        self.answer.show()
        self.answer.setFocus()
        self.adjustSize()

    def _send(self):
        text = self.answer.text().strip()
        self.answer.hide()
        if text:
            self.answered.emit(text)


class MascotStage(QWidget):
    """Avatar + speech bubble + click-to-pick activity selector."""

    activity_changed = Signal(str)        # emits the chosen activity label

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._selector = PoseSelector(settings.state_map())
        self._movie: Optional[QMovie] = None
        self._selector_open = False
        self._bubbles: list[ActivityBubble] = []
        self.current_activity = "Idle"
        self.current_state = "idle"

        self.setMinimumHeight(232)
        self.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0c0c12, stop:1 #0a0a10);"
            "border-top: 1px solid rgba(255,255,255,0.08);"
        )

        # avatar
        self.avatar = QLabel(self)
        self.avatar.setScaledContents(True)
        self.avatar.setCursor(Qt.PointingHandCursor)
        self.avatar.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # speech bubble
        self.bubble = SpeechBubble(self)

        self.set_state("idle", silent=True)
        self._relayout()

    # --- sizing / layout (manual: arc bubbles around avatar) ---
    def sizeHint(self) -> QSize:
        return QSize(340, 240)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _avatar_px(self) -> int:
        return self.settings.avatar_px

    def _relayout(self):
        px = self._avatar_px()
        w = self.width()
        h = self.height()
        # avatar bottom-center
        self.avatar.setFixedSize(px, px)
        ax = (w - px) // 2
        ay = h - px - 6
        self.avatar.move(ax, ay)
        # speech bubble above her head (or pushed up when selector open)
        self.bubble.adjustSize()
        bw = self.bubble.width()
        bx = max(8, (w - bw) // 2)
        by = 6 if self._selector_open else max(4, ay - self.bubble.height() - 4)
        self.bubble.move(bx, by)
        self.bubble.raise_()
        if self._selector_open:
            self._place_bubbles()

    def _place_bubbles(self):
        """Arc the activity bubbles around the avatar."""
        w = self.width()
        cx = w / 2
        n = len(self._bubbles)
        if not n:
            return
        cy = self.height() - self._avatar_px() * 0.55
        radius_x = min(w * 0.42, 150)
        radius_y = self._avatar_px() * 0.78
        # spread from ~200deg to ~340deg (upper arc, left to right)
        start, end = 200, 340
        for i, b in enumerate(self._bubbles):
            b.adjustSize()
            frac = i / (n - 1) if n > 1 else 0.5
            ang = math.radians(start + (end - start) * frac)
            bx = cx + radius_x * math.cos(ang) - b.width() / 2
            by = cy - radius_y * math.sin(ang) - b.height() / 2
            bx = max(4, min(bx, w - b.width() - 4))
            by = max(4, by)
            b.move(int(bx), int(by))
            b.show()
            b.raise_()

    # --- avatar click toggles the selector ---
    def mousePressEvent(self, e):
        # clicking the avatar area toggles; clicking empty space closes
        if self.avatar.geometry().contains(e.position().toPoint()):
            self.toggle_selector()
        elif self._selector_open:
            self.close_selector()
        super().mousePressEvent(e)

    def toggle_selector(self):
        if self._selector_open:
            self.close_selector()
        else:
            self.open_selector()

    def open_selector(self):
        if self._selector_open:
            return
        self._selector_open = True
        for label, _state, color in ACTIVITIES:
            b = ActivityBubble(label, color, self)
            b.clicked.connect(lambda _=False, lbl=label: self._on_pick(lbl))
            self._bubbles.append(b)
        self._relayout()

    def close_selector(self):
        self._selector_open = False
        for b in self._bubbles:
            b.deleteLater()
        self._bubbles = []
        self._relayout()

    def _on_pick(self, label: str):
        state = next((s for (l, s, _c) in ACTIVITIES if l == label), "idle")
        self.current_activity = label
        self.close_selector()
        self.set_state(state)
        self.activity_changed.emit(label)

    # --- state / pose ---
    def refresh_selector(self):
        """Re-read the state map (e.g. after Settings edits)."""
        self._selector = PoseSelector(self.settings.state_map())

    def set_state(self, state: str, silent: bool = False):
        self.current_state = state
        pose_key = self._selector.pick(state)
        if pose_key is None:
            pose_key = self._selector.pick("idle")
        fname = self._selector.filename(pose_key) if pose_key else None
        if fname:
            self._play(str(paths.poses_dir() / fname))

    def _play(self, path: str):
        if self._movie:
            self._movie.stop()
        self._movie = QMovie(path)
        self._movie.setCacheMode(QMovie.CacheAll)
        self.avatar.setMovie(self._movie)
        self._movie.start()

    def says(self, text: str, color: str = "#19e3ff"):
        self.bubble.set_text(text, color)
        self._relayout()

    def ask(self, text: str, color: str = "#a78bfa"):
        self.bubble.ask(text, color)
        self._relayout()
