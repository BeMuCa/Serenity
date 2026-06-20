"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Graph tab - renders the todo dependency graph (core.depgraph.build_graph).
Role:    Draws the active todos as nodes (ready / in-progress / blocked styling) and the
         "blocks" dependencies as directed edges, read-only (spec sec 5 / sec 12). The pure
         graph build (nodes + edges, status classification) lives in core.depgraph; this view
         only lays them out in a QGraphicsScene and paints them. A clean empty-state shows
         when no todo declares a dependency, so the tab never looks broken.

Classes:
- GraphView - the dependency-graph canvas (refresh() rebuilds from the todo store)
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.depgraph import BLOCKED, IN_PROGRESS, READY, build_graph
from .theme import COLORS

# status -> (border color, fill tint) - reuses the app palette (no neon outside the stage).
_STATUS_STYLE = {
    READY: ("#86efac", "rgba(134,239,172,0.10)"),
    IN_PROGRESS: (COLORS["accent"], "rgba(167,139,250,0.14)"),
    BLOCKED: ("#fca5a5", "rgba(252,165,165,0.10)"),
}
_STATUS_LABEL = {READY: "ready", IN_PROGRESS: "in progress", BLOCKED: "blocked"}

_NODE_W = 168
_NODE_H = 44
_COL_GAP = 56
_ROW_GAP = 18


class GraphView(QWidget):
    def __init__(self, todo_store=None, parent=None):
        super().__init__(parent)
        self.todo_store = todo_store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QLabel("Dependency graph")
        head.setObjectName("sectLabel")
        lay.addWidget(head)

        # legend (single hyphen copy, no emoji)
        legend = QLabel("ready - green   |   in progress - violet   |   blocked - red")
        legend.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        lay.addWidget(legend)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setMinimumHeight(240)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setStyleSheet(
            f"QGraphicsView {{ background:{COLORS['panel2']}; "
            f"border:1px solid {COLORS['line']}; border-radius:10px; }}")
        lay.addWidget(self.view, 1)

        self.empty = QLabel(
            "No dependencies yet. Link todos with \"depends on\" and the graph "
            "draws ready / in-progress / blocked nodes here.")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color:{COLORS['ink3']}; font-size:12px;")
        lay.addWidget(self.empty)

        self.refresh()

    def refresh(self) -> None:
        """Rebuild the scene from the current todos (read-only)."""
        self.scene.clear()
        todos = self.todo_store.all() if self.todo_store is not None else []
        graph = build_graph(todos)

        # Only nodes that participate in a dependency are worth drawing; with no edges
        # at all, show the clean empty-state instead of a wall of disconnected boxes.
        if not graph.edges:
            self.view.hide()
            self.empty.show()
            return
        self.empty.hide()
        self.view.show()

        connected = {e.blocker for e in graph.edges} | {e.blocked for e in graph.edges}
        nodes = [n for n in graph.nodes if n.id in connected]

        # Simple layered layout: blockers (no incoming "blocks" edge) on the left,
        # everything that is blocked to the right of it. Two columns is enough to read.
        blocked_ids = {e.blocked for e in graph.edges}
        col0 = [n for n in nodes if n.id not in blocked_ids]   # roots (block others)
        col1 = [n for n in nodes if n.id in blocked_ids]       # dependents
        if not col0:                                           # cycle / all blocked
            col0, col1 = nodes, []

        pos: dict[str, QPointF] = {}
        for col, group in enumerate((col0, col1)):
            x = col * (_NODE_W + _COL_GAP)
            for row, node in enumerate(group):
                y = row * (_NODE_H + _ROW_GAP)
                pos[node.id] = QPointF(x, y)

        # edges first (under the nodes)
        for edge in graph.edges:
            if edge.blocker in pos and edge.blocked in pos:
                self._draw_edge(pos[edge.blocker], pos[edge.blocked])
        # then the node boxes
        node_by_id = {n.id: n for n in nodes}
        for node_id, p in pos.items():
            self._draw_node(node_by_id[node_id], p)

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-16, -16, 16, 16))

    def _draw_node(self, node, top_left: QPointF) -> None:
        border, fill = _STATUS_STYLE.get(node.status, (COLORS["ink2"], COLORS["panel3"]))
        rect = self.scene.addRect(
            top_left.x(), top_left.y(), _NODE_W, _NODE_H,
            QPen(QColor(border), 1.5), QBrush(QColor(_rgba_to_qcolor(fill))))
        rect.setZValue(1)
        title = node.title if len(node.title) <= 26 else node.title[:25] + "…"
        text = self.scene.addText(title)
        text.setDefaultTextColor(QColor(COLORS["ink"]))
        font = text.font()
        font.setPointSize(9)
        text.setFont(font)
        text.setPos(top_left.x() + 9, top_left.y() + 5)
        text.setZValue(2)
        status = self.scene.addText(_STATUS_LABEL.get(node.status, node.status))
        status.setDefaultTextColor(QColor(border))
        sfont = status.font()
        sfont.setPointSize(7)
        status.setFont(sfont)
        status.setPos(top_left.x() + 9, top_left.y() + 23)
        status.setZValue(2)

    def _draw_edge(self, frm: QPointF, to: QPointF) -> None:
        # connect right-middle of the blocker to left-middle of the blocked
        x1, y1 = frm.x() + _NODE_W, frm.y() + _NODE_H / 2
        x2, y2 = to.x(), to.y() + _NODE_H / 2
        pen = QPen(QColor(COLORS["ink3"]), 1.4)
        self.scene.addLine(x1, y1, x2, y2, pen)
        # a small arrowhead at the blocked end
        self._arrowhead(x2, y2, pen)

    def _arrowhead(self, x: float, y: float, pen: QPen) -> None:
        size = 6
        head = QPolygonF([
            QPointF(x, y),
            QPointF(x - size, y - size / 2),
            QPointF(x - size, y + size / 2),
        ])
        self.scene.addPolygon(head, pen, QBrush(QColor(COLORS["ink3"])))


def _rgba_to_qcolor(rgba: str) -> QColor:
    """Parse an 'rgba(r,g,b,a)' string (a in 0..1) into a QColor."""
    inner = rgba[rgba.find("(") + 1:rgba.find(")")]
    parts = [p.strip() for p in inner.split(",")]
    try:
        r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
        a = int(float(parts[3]) * 255) if len(parts) > 3 else 255
    except (ValueError, IndexError):
        return QColor(0, 0, 0, 0)
    return QColor(r, g, b, a)
