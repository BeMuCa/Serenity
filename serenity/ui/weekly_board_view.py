"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Weekly Performance Board tab (renders core.weekly_board.build_board).
Role:    Friday's Wochen-Board (spec sec 10): time per activity this week vs last with a
         trend arrow, the completed-todo count, and the plain optimization hints. Pure-logic
         lives in core.weekly_board.build_board / core.activity; this view only renders the
         WeeklyBoard it is handed. The shell auto-opens this tab once a day Fri 17-18h
         (core.activity.should_auto_open_board) and has Serenity read a hint aloud.

Classes:
- WeeklyBoardView - the board tab (refresh() rebuilds from the activity store + todos)
============================================================
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.activity import week_start_dt
from ..core.weekly_board import WeeklyBoard, build_board
from .theme import COLORS


def _fmt_hms(seconds: int) -> str:
    """Whole seconds -> a compact 'Xh Ym' / 'Ym' label."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _trend(delta: int) -> tuple[str, str]:
    """A single-glyph trend marker + color for a week-over-week delta (no emoji)."""
    if delta > 0:
        return f"up {_fmt_hms(delta)}", "#86efac"
    if delta < 0:
        return f"down {_fmt_hms(-delta)}", "#fca5a5"
    return "no change", COLORS["ink3"]


class WeeklyBoardView(QWidget):
    """Renders the weekly board: per-activity time, trend, completed count, hints."""

    def __init__(self, activity_store, todo_store, parent=None):
        super().__init__(parent)
        self.activity_store = activity_store
        self.todo_store = todo_store
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        head = QLabel("Weekly performance")
        head.setObjectName("sectLabel")
        self._lay.addWidget(head)
        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        self._lay.addLayout(self._body)
        self._lay.addStretch(1)
        self.refresh()

    # --- data ---
    def build(self, now: datetime | None = None) -> WeeklyBoard:
        """Build the board from the persisted log + this week's completed-todo count."""
        now = now or datetime.now()
        entries = self.activity_store.log().entries()
        completed = self._completed_this_week(now)
        return build_board(entries, now, completed_this_week=completed)

    def _completed_this_week(self, now: datetime) -> int:
        """Count done todos updated since Monday 00:00 (the activity week window)."""
        start = week_start_dt(now)
        count = 0
        for t in self.todo_store.all():
            if t.done and t.updated is not None and t.updated >= start:
                count += 1
        return count

    # --- rendering ---
    def refresh(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        board = self.build()
        self._body.addWidget(self._summary_card(board))
        if board.categories:
            self._body.addWidget(self._categories_card(board))
        self._body.addWidget(self._hints_card(board))

    def _summary_card(self, board: WeeklyBoard) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        row = QHBoxLayout()
        total = QLabel(f"Tracked: {_fmt_hms(board.total_seconds)}")
        total.setStyleSheet(f"color:{COLORS['ink']}; font-size:14px; font-weight:600;")
        done = QLabel(f"Completed todos: {board.completed}")
        done.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
        row.addWidget(total)
        row.addStretch(1)
        row.addWidget(done)
        lay.addLayout(row)
        text, color = _trend(board.total_delta)
        trend = QLabel(f"Total vs last week: {text}")
        trend.setStyleSheet(f"color:{color}; font-size:11px;")
        lay.addWidget(trend)
        return card

    def _categories_card(self, board: WeeklyBoard) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)
        title = QLabel("Time per activity")
        title.setObjectName("sectLabel")
        lay.addWidget(title)
        for stat in board.categories:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(stat.category)
            name.setStyleSheet(f"color:{COLORS['ink']}; font-size:12px;")
            secs = QLabel(_fmt_hms(stat.seconds))
            secs.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
            text, color = _trend(stat.delta)
            delta = QLabel(text)
            delta.setStyleSheet(f"color:{color}; font-size:10.5px;")
            row.addWidget(name, 1)
            row.addWidget(delta)
            row.addWidget(secs)
            lay.addLayout(row)
        return card

    def _hints_card(self, board: WeeklyBoard) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)
        title = QLabel("Hints")
        title.setObjectName("sectLabel")
        lay.addWidget(title)
        hints = board.hints or ["Nothing to report yet - keep tracking your activities."]
        for h in hints:
            lab = QLabel("- " + h)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11.5px;")
            lay.addWidget(lab)
        return card
