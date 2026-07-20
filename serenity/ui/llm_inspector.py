"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: The LLM queue's working indicator (a click-to-open "thinking..." status line)
         and the hidden inspector panel (running + pending/paused jobs with per-job
         Pause/Resume/Prioritize + a global pause).
Role:    Dock-only UI surface for the LLM job queue (Infra A). Reads LlmQueue.snapshot();
         re-renders live on the worker's queueChanged signal (fold 11.11).

Classes:
- LlmStatusLine(QLabel) — shown only while busy; clicked -> open the inspector
- LlmInspector(QWidget) — snapshot list + controls that mutate the queue
============================================================
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..core.llm_queue import JobState, LlmQueue


class LlmStatusLine(QLabel):
    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("thinking…", parent)
        self.setObjectName("llmStatusLine")
        self.setCursor(Qt.PointingHandCursor)
        self.hide()                       # truly hidden when idle

    def set_busy(self, busy: bool) -> None:
        self.setVisible(bool(busy))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._emit_click()

    def _emit_click(self) -> None:
        self.clicked.emit()


class LlmInspector(QWidget):
    def __init__(self, queue: LlmQueue, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("LLM jobs")
        self._queue = queue
        self._root = QVBoxLayout(self)
        self._global_btn = QPushButton("Pause all", self)
        self._global_btn.clicked.connect(self._toggle_global)
        self._root.addWidget(self._global_btn)
        self._rows_box = QVBoxLayout()
        self._root.addLayout(self._rows_box)
        self._paused_all = False

    def render(self) -> None:
        while self._rows_box.count():
            item = self._rows_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        running, pending = self._queue.snapshot()
        if running is not None:
            self._rows_box.addWidget(self._row(running, controls=False))
        for view in pending:
            self._rows_box.addWidget(self._row(view, controls=True))

    def _row(self, view, controls: bool) -> QFrame:
        row = QFrame(self)
        lay = QHBoxLayout(row)
        lay.addWidget(QLabel(f"{view.label} — {view.state.value}", row))
        if controls:
            if view.state == JobState.PAUSED:
                b = QPushButton("Resume", row); b.clicked.connect(lambda: self._resume(view.id))
            else:
                b = QPushButton("Pause", row); b.clicked.connect(lambda: self._pause(view.id))
            lay.addWidget(b)
            pri = QPushButton("Play next", row)
            pri.clicked.connect(lambda: self._prioritize(view.id))
            lay.addWidget(pri)
        return row

    # --- control handlers: mutate the queue, then re-render ---
    def _pause(self, job_id: str) -> bool:
        ok = self._queue.pause(job_id); self.render(); return ok

    def _resume(self, job_id: str) -> bool:
        ok = self._queue.resume(job_id); self.render(); return ok

    def _prioritize(self, job_id: str) -> bool:
        ok = self._queue.prioritize(job_id); self.render(); return ok

    def _global_pause(self, paused: bool) -> None:
        self._paused_all = paused
        (self._queue.pause_all if paused else self._queue.resume_all)()
        self._global_btn.setText("Resume all" if paused else "Pause all")
        self.render()

    def _toggle_global(self) -> None:
        self._global_pause(not self._paused_all)

    # --- test helper ---
    def row_labels(self):
        running, pending = self._queue.snapshot()
        out = []
        if running is not None:
            out.append((running.label, running.state))
        out.extend((v.label, v.state) for v in pending)
        return out
