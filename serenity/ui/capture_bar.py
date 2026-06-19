"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The bottom capture bar - mic + Quick note + Quick todo (matches the mockup).
Role:    Entry point for capture. The mic opens the cheatsheet + a recording state and
         a conversational slot-filling demo via the mascot bubble (Phase-1 UI only -
         no real STT). Quick note / todo open the modals.

Classes:
- CaptureBar - mic toggle + two quick buttons; signals to the shell
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

from . import icons
from .theme import COLORS


class CaptureBar(QFrame):
    mic_toggled = Signal(bool)             # recording on/off
    quick_note = Signal()
    quick_todo = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("capture")
        self.recording = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(11)

        self.mic = QPushButton()
        self.mic.setIcon(icons.icon("mic", COLORS["ink"], 18))
        self.mic.setFixedSize(40, 40)
        self.mic.setCursor(Qt.PointingHandCursor)
        self.mic.setToolTip("Mic - opens the voice grammar cheatsheet")
        self._style_mic()
        self.mic.clicked.connect(self._toggle_mic)
        lay.addWidget(self.mic)

        note_btn = QPushButton("Quick note")
        note_btn.setIcon(icons.icon("note", COLORS["ink2"], 13))
        note_btn.setObjectName("ghost")
        note_btn.setCursor(Qt.PointingHandCursor)
        note_btn.clicked.connect(self.quick_note.emit)
        lay.addWidget(note_btn, 1)

        todo_btn = QPushButton("Quick todo")
        todo_btn.setIcon(icons.icon("plus", COLORS["ink2"], 13))
        todo_btn.setObjectName("ghost")
        todo_btn.setCursor(Qt.PointingHandCursor)
        todo_btn.clicked.connect(self.quick_todo.emit)
        lay.addWidget(todo_btn, 1)

    def _style_mic(self):
        if self.recording:
            self.mic.setStyleSheet(
                "QPushButton { border-radius:20px; border:none; "
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff3bd4, stop:1 #a78bfa); }"
            )
            self.mic.setIcon(icons.icon("mic", "#ffffff", 18))
        else:
            self.mic.setStyleSheet(
                f"QPushButton {{ border-radius:20px; border:1px solid {COLORS['line2']}; "
                f"background:{COLORS['panel3']}; }}"
                f"QPushButton:hover {{ border:1px solid {COLORS['accent']}; }}"
            )
            self.mic.setIcon(icons.icon("mic", COLORS["ink"], 18))

    def _toggle_mic(self):
        self.recording = not self.recording
        self._style_mic()
        self.mic_toggled.emit(self.recording)
