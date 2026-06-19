"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Graph tab - a Phase-1 placeholder for the dependency-graph visualization.
Role:    Holds the tab slot and explains what lands here in Phase 2 (todo dependency
         graph: ready / in-progress / blocked nodes). Wired entry point, no fake data.

Classes:
- GraphView - placeholder canvas with a legend
============================================================
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .theme import COLORS


class GraphView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QLabel("Dependency graph")
        head.setObjectName("sectLabel")
        lay.addWidget(head)
        canvas = QFrame()
        canvas.setObjectName("card")
        canvas.setMinimumHeight(240)
        cl = QVBoxLayout(canvas)
        msg = QLabel(
            "The todo dependency graph (ready / in-progress / blocked nodes, "
            "\"blocks\" edges) renders here in Phase 2. Phase 1 ships the tab and "
            "the data model so the graph slots in without rework."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color:{COLORS['ink3']}; font-size:12px;")
        cl.addStretch(1)
        cl.addWidget(msg)
        cl.addStretch(1)
        lay.addWidget(canvas)
        lay.addStretch(1)
