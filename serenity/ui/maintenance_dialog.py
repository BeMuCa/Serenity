"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Shared row-management behavior for the Notes-tab maintenance modals.
Role:    DuplicatesDialog (Job 3) and TagConsolidationDialog (Job 5) are independent QDialog
         subclasses that share the exact same scrollable-rows contract: each builds its own
         rows into `self.rows_box`, tracks a live `self._row_count`, and toggles an
         `self.empty_label` / `self.scroll` pair as rows are removed. This mixin owns the three
         pieces of logic that were byte-identical between them - eliding a label to a pixel
         budget, the session-only "dismiss" of a row, and the row removal + empty-state toggle -
         so a tweak to that behavior is made in one place instead of two.

         The mixin defines NO __init__: each dialog still creates rows_box / empty_label /
         scroll / _row_count in its own __init__; the mixin only reads and mutates those
         attributes. Mix it in BEFORE QDialog (so its methods take precedence on the dialog).

Classes:
- _MaintenanceRowsMixin - _elide / _dismiss_row / _remove_row over the rows_box contract
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame


class _MaintenanceRowsMixin:
    """Row-elide / dismiss / remove behavior shared by the maintenance dialogs.

    Expects the host dialog to provide, from its own __init__: `rows_box` (the QVBoxLayout the
    rows live in), `empty_label` (the centered empty-state QLabel), `scroll` (the QScrollArea
    wrapping the rows), and `_row_count` (the live count of resolved rows)."""

    def _elide(self, text: str, width: int) -> str:
        return QFontMetrics(self.font()).elidedText(text, Qt.ElideRight, width)

    def _dismiss_row(self, row: QFrame):
        """Session-only 'not now': drop this row. No persistence - re-scan next open."""
        self._remove_row(row)

    def _remove_row(self, row: QFrame):
        """Drop a row widget and update the empty-state when none remain."""
        row.setParent(None)
        row.deleteLater()
        self._row_count = max(0, self._row_count - 1)
        if self._row_count == 0:
            self.empty_label.setVisible(True)
            self.scroll.setVisible(False)   # free the central area for the empty message
