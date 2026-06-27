"""
============================================================
Author:  Berk
Created: 2026-06-27
Purpose: ExpandedPanel - a frameless Serenity-themed left-docked pop-out window foundation.
Role:    The reusable shell for the Notes-expand editor now (hosts a NoteEditorPanel) and the
         future Calendar-expand. Owns the chrome only: a header row (title + close), the
         left-docking on show (platform_win.dock_left_of, anchored to the dock), and the close
         routing - both the X button and Esc emit closeRequested so the hosted content widget
         can run its own dirty/Save/Discard/Cancel check. Carries no draft/commit logic.

Classes:
- ExpandedPanel - frameless Qt.Tool themed window hosting one content widget beside the dock
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import platform_win
from .theme import COLORS, stylesheet


class ExpandedPanel(QWidget):
    """A frameless, always-on-top themed window docked flush-left of an anchor (the dock).

    closeRequested is the single close channel: the X button and Esc both emit it (P2-12) so the
    content widget decides whether to actually close (e.g. a dirty-prompt). The panel does not
    close itself on those events; the host calls close() once the content resolves."""

    closeRequested = Signal()

    def __init__(self, title: str, content: QWidget, anchor, parent=None):
        super().__init__(parent)
        self._anchor = anchor
        self._content = content   # the hosted widget (e.g. NoteEditorPanel) - the host wires its close
        self.setObjectName("dock")
        self.setWindowTitle("Serenity")
        # frameless tool window, always on top - mirrors the shell (shell.py:201-203).
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setStyleSheet(stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header row: title + close (X). The close button routes through closeRequested, never
        # a bare close(), so the content widget's dirty check always runs first.
        header = QWidget()
        header.setObjectName("titleBar")
        header.setFixedHeight(42)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 8, 0)
        hl.setSpacing(8)
        self._title_label = QLabel(title)
        self._title_label.setObjectName("brand")
        hl.addWidget(self._title_label)
        hl.addStretch(1)
        self._close_btn = QPushButton("✕")  # ✕
        self._close_btn.setObjectName("iconbtn")
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setToolTip("Close")
        self._close_btn.clicked.connect(self.closeRequested.emit)
        hl.addWidget(self._close_btn)
        root.addWidget(header)

        root.addWidget(content, 1)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def showEvent(self, e):
        # dock flush-left of the anchor (the right-edge dock) on every show, so a re-show after a
        # mode switch re-anchors to the dock's current screen (P3-4).
        super().showEvent(e)
        platform_win.dock_left_of(self, self._anchor)

    def keyPressEvent(self, e):
        # frameless widgets get no automatic Esc-to-close; wire it to the one close channel.
        if e.key() == Qt.Key_Escape:
            self.closeRequested.emit()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        # restore focus to the dock guarded: the anchor's C++ object may already be deleted on a
        # quit teardown, which raises RuntimeError on any access (P3-5).
        try:
            if self._anchor is not None and self._anchor.isVisible():
                self._anchor.activateWindow()
        except RuntimeError:
            pass
        super().closeEvent(e)
