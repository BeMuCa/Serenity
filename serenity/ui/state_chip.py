"""
============================================================
Author:  Berk
Created: 2026-07-03
Purpose: The deselectable "current state" filter chip (Phase C).
Role:    One pill chip shared by the Todos and Notes views. The Shell drives it
         (set_state/clear via the views' set_state_filter); checking/unchecking
         toggles the state axis of the list post-filter. Session-only UI state -
         never persisted.

Classes:
- StateFilterChip - card row holding one checkable pill; active_key() feeds visible()
============================================================
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget


class StateFilterChip(QWidget):
    """A checkable pill showing the running activity; checked = state axis ON."""

    toggled_filter = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key: Optional[str] = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QFrame()
        row.setObjectName("card")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(3, 3, 3, 3)
        self.btn = QPushButton()
        self.btn.setObjectName("pill")
        self.btn.setCheckable(True)
        self.btn.setToolTip("Only items tagged with the running activity (uncheck to show all)")
        self.btn.toggled.connect(lambda _checked: self.toggled_filter.emit())
        rl.addWidget(self.btn)
        rl.addStretch(1)
        lay.addWidget(row)
        self.hide()

    def set_state(self, key: str, label: str, color: str, checked: bool) -> None:
        """Show the chip for the running activity (label + registry color)."""
        self._key = key
        self.btn.setText(f"● {label}")
        self.btn.setStyleSheet(f"color:{color};")
        self.btn.setChecked(checked)
        self.show()

    def clear(self) -> None:
        """Idle / unmappable label: hide the chip; the state axis goes inert (R2)."""
        self._key = None
        self.btn.setChecked(False)
        self.hide()

    def active_key(self) -> Optional[str]:
        """The state key to filter by, or None when the axis is off."""
        return self._key if (not self.isHidden() and self.btn.isChecked()) else None
