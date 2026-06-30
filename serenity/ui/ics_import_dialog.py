"""
============================================================
Author:  Berk
Created: 2026-06-30
Purpose: Dialog that previews an ICS ImportPlan before the user confirms import.
Role:    UI layer — shown after reconcile() produces an ImportPlan; nothing is
         applied to the store until the user clicks Import (QDialog.Accepted).
         Renders counts, capped rows (20 per section), per-update field diff,
         and a recurring-todo warning.

Classes:
- ImportPreviewDialog(plan, parent=None) — QDialog preview for an ImportPlan
============================================================
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

_ROW_CAP = 20


class ImportPreviewDialog(QDialog):
    """Preview an ICS ImportPlan; nothing is applied until the user clicks Import."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import calendar")
        self._plan = plan
        self._create_rows = min(len(plan.to_create), _ROW_CAP)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(self.summary_text()))
        body = QWidget(); col = QVBoxLayout(body)
        for ev in plan.to_create[:_ROW_CAP]:
            lbl = QLabel(f"+ {ev.title or '(untitled)'}"); lbl.setTextFormat(Qt.PlainText)
            col.addWidget(lbl)
        if len(plan.to_create) > _ROW_CAP:
            col.addWidget(QLabel(f"…and {len(plan.to_create) - _ROW_CAP} more"))
        for todo, ev in plan.to_update[:_ROW_CAP]:
            diff = self._diff(todo, ev)
            warn = "  ⟳ recurrence kept" if getattr(todo, "recurring", None) else ""
            lbl = QLabel(f"~ {ev.title or '(untitled)'} ({diff}){warn}"); lbl.setTextFormat(Qt.PlainText)
            col.addWidget(lbl)
        if len(plan.to_update) > _ROW_CAP:
            col.addWidget(QLabel(f"…and {len(plan.to_update) - _ROW_CAP} more"))
        for label, why in plan.skipped[:_ROW_CAP]:
            lbl = QLabel(f"– {label}: {why}"); lbl.setTextFormat(Qt.PlainText)
            col.addWidget(lbl)
        if len(plan.skipped) > _ROW_CAP:
            col.addWidget(QLabel(f"…and {len(plan.skipped) - _ROW_CAP} more"))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(body)
        root.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Import")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def summary_text(self) -> str:
        p = self._plan
        parts = [f"{len(p.to_create)} new", f"{len(p.to_update)} update(s)",
                 f"{len(p.skipped)} skipped"]
        return " · ".join(parts)

    def rendered_create_rows(self) -> int:
        return self._create_rows

    @staticmethod
    def _diff(todo, ev) -> str:
        out = []
        if todo.due != ev.when:
            due_str = todo.due.strftime("%Y-%m-%d %H:%M") if todo.due else "none"
            out.append(f"due {due_str} → {ev.when:%Y-%m-%d %H:%M}")
        if todo.title != ev.title:
            out.append(f"title → {ev.title!r}")
        if (todo.category or None) != (ev.category or None):
            out.append(f"category → {ev.category!r}")
        return "; ".join(out) or "no change"
