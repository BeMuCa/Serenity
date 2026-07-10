"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Weekly Performance Board tab (renders core.weekly_board.build_board).
Role:    Friday's Wochen-Board (spec sec 10): time per activity this week vs last with a
         trend arrow, the completed-todo count, and the plain optimization hints. Pure-logic
         lives in core.weekly_board.build_board / core.activity; this view only renders the
         WeeklyBoard it is handed. The shell auto-opens this tab once a day Fri 17-18h
         (core.activity.should_auto_open_board) and has Serenity read the digest aloud.

         Job 6 adds the AI weekly digest (core.digest.generate_digest): when a usable
         core.llm.LLMEngine is injected, a short friendly comment in Serenity's voice is
         shown at the TOP of the board and exposed via digest_text() for the mascot to read;
         when no engine is wired / it is unavailable, both the card and digest_text() degrade
         to the board's deterministic hint - so there is always a comment. The LLM is only
         called when the board is built/refreshed (i.e. when the tab is opened), never at idle.

Classes:
- WeeklyBoardView - the board tab (refresh() rebuilds from the activity store + todos)
============================================================
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.activity import week_start_dt
from ..core.digest import _fmt_hms, generate_digest
from ..core.weekly_board import WeeklyBoard, build_board
from .theme import COLORS


def _trend(delta: int) -> tuple[str, str]:
    """A single-glyph trend marker + color for a week-over-week delta (no emoji)."""
    if delta > 0:
        return f"up {_fmt_hms(delta)}", "#86efac"
    if delta < 0:
        return f"down {_fmt_hms(-delta)}", "#fca5a5"
    return "no change", COLORS["ink3"]


class WeeklyBoardView(QWidget):
    """Renders the weekly board: per-activity time, trend, completed count, hints."""

    def __init__(self, activity_store, todo_store, llm=None, parent=None):
        super().__init__(parent)
        self.activity_store = activity_store
        self.todo_store = todo_store
        # Optional local-LLM engine (core.llm.LLMEngine). None / unavailable -> the digest
        # degrades to the board's deterministic hint. The shell injects its engine if it has
        # one; tests inject a StubLLM. Never called at idle - only when the board is built.
        self.llm = llm
        # Week anchor: None = current week, datetime = any day in target week. Used to browse
        # past weeks while keeping stats bounded to the anchored week only (P2-1).
        self._anchor: datetime | None = None
        # The last digest rendered, so the Friday auto-open flow can read it via the mascot
        # without rebuilding the board. Set by refresh(); falls back to a hint when no LLM.
        self._digest = ""
        # Warm-cache for the digest (mirrors core.tts_cache's hit/miss/invalidation): the
        # signature of the board the cached digest was authored from. switch_tab('board')
        # calls refresh() on EVERY board-tab click, and with a real LlamaCppLLM each
        # generate_digest is a multi-second inference on the Qt main thread - so we recompute
        # ONLY when the board content actually changed. None means "no digest cached yet".
        self._digest_sig = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)

        # --- header: prev/next nav, the week label, Today ---
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self._prev_btn = QPushButton("<")
        self._next_btn = QPushButton(">")
        self._today_btn = QPushButton("Today")
        self._label = QLabel("Weekly performance")
        self._label.setObjectName("sectLabel")
        for b in (self._prev_btn, self._next_btn, self._today_btn):
            b.setObjectName("tab")
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        self._today_btn.clicked.connect(self._go_today)
        header.addWidget(self._prev_btn)
        header.addWidget(self._label, 1)
        header.addWidget(self._next_btn)
        header.addWidget(self._today_btn)
        self._lay.addLayout(header)

        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        self._lay.addLayout(self._body)
        self._lay.addStretch(1)
        self.refresh()

    # --- week nav ---
    def _go_prev(self) -> None:
        """Shift the anchor back 7 days (or from None to previous week)."""
        if self._anchor is None:
            # From current week: go back to its Monday, then shift back another week
            self._anchor = week_start_dt(datetime.now()) - timedelta(days=7)
        else:
            self._anchor = self._anchor - timedelta(days=7)
        self.refresh()

    def _go_next(self) -> None:
        """Shift the anchor forward 7 days."""
        if self._anchor is None:
            # From current week: go forward to next week's Monday
            self._anchor = week_start_dt(datetime.now()) + timedelta(days=7)
        else:
            self._anchor = self._anchor + timedelta(days=7)
        self.refresh()

    def _go_today(self) -> None:
        """Reset anchor to None (current week)."""
        self._anchor = None
        self.refresh()

    # --- data ---
    def build(self, now: datetime | None = None) -> WeeklyBoard:
        """Build the board from the persisted log + this week's completed-todo count."""
        now = now or datetime.now()
        entries = self.activity_store.log().entries()
        completed = self._completed_this_week(now)
        return build_board(entries, now, completed_this_week=completed, anchor=self._anchor)

    def _completed_this_week(self, now: datetime) -> int:
        """Count done todos completed (by completed_at) in the anchored week.

        Window is [this_start, this_start+7d). Uses completed_at (not updated) so a todo
        edited in a later week but completed in this week is counted in the correct week (P2-1)."""
        this_start = week_start_dt(self._anchor or now)
        this_end = this_start + timedelta(days=7)
        count = 0
        for t in self.todo_store.all():
            if t.done and t.completed_at is not None and this_start <= t.completed_at < this_end:
                count += 1
        return count

    @staticmethod
    def _board_sig(board: WeeklyBoard) -> tuple:
        """A cheap, hashable signature of everything the digest is authored from.

        The digest depends only on the board numbers fed to board_facts (totals, the
        week-over-week deltas, the completed count, and each category's time + delta), so two
        boards with the same signature would produce the same comment. Used as the warm-cache
        key: a match is a cache hit (reuse the digest, skip the LLM), any change in tracked
        time / completed count / categories is a miss (re-author). Mirrors core.tts_cache,
        which keys its render on the exact final content."""
        return (
            board.total_seconds,
            board.prev_total_seconds,
            board.completed,
            tuple((c.category, c.seconds, c.prev_seconds) for c in board.categories),
        )

    def digest_text(self) -> str:
        """Serenity's current spoken weekly comment (the AI digest, or the degrade hint).

        The string the Friday auto-open flow reads aloud via the mascot. Populated by
        refresh(); when an LLM is wired this is the AI-authored comment, otherwise the
        board's deterministic hint - so it is always a usable, non-empty line."""
        return self._digest

    # --- rendering ---
    def refresh(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        board = self.build()
        # Update the week label with the anchored week range
        now = datetime.now()
        this_start = week_start_dt(self._anchor or now)
        this_end = this_start + timedelta(days=6)  # Monday to Sunday
        label_text = f"{this_start.strftime('%b %d')} – {this_end.strftime('%b %d')}"
        self._label.setText(label_text)

        # Only call generate_digest for the current week (anchor=None or anchored to this week).
        # Past weeks use the board's deterministic hints (no model load).
        is_current_week = self._anchor is None or week_start_dt(self._anchor) == week_start_dt(now)

        # Warm-cache the digest (mirrors core.tts_cache hit/miss/invalidation): refresh() runs
        # on EVERY board-tab click, and a real LLM digest is a multi-second main-thread
        # inference. Recompute ONLY when the board content changed; otherwise reuse the cached
        # comment. Invalidation is automatic - any change in tracked time / completed count /
        # categories changes the signature, forcing a re-author. Digest is NOT generated for
        # past weeks (is_current_week=False) to avoid model load when browsing history.
        sig = self._board_sig(board)
        if is_current_week and (sig != self._digest_sig or not self._digest):
            self._digest = generate_digest(board, self.llm)
            self._digest_sig = sig
        # Only show the dedicated digest card when the comment is AI-authored. In the degrade
        # path (no/unavailable LLM) the digest IS the board hints, which the hints card below
        # already lists - showing it twice would repeat the same sentences on one screen.
        ai = self.llm is not None and getattr(self.llm, "available", False)
        if ai and is_current_week:
            self._body.addWidget(self._digest_card())
        self._body.addWidget(self._summary_card(board))
        if board.categories:
            self._body.addWidget(self._categories_card(board))
        self._body.addWidget(self._hints_card(board))

    def _digest_card(self) -> QFrame:
        """Serenity's AI-authored weekly comment at the top of the board.

        Only added by refresh() when an LLM produced the comment; in the degrade path the
        hints card carries the same text, so this card is suppressed to avoid duplication."""
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)
        title = QLabel("Serenity's note")
        title.setObjectName("sectLabel")
        lay.addWidget(title)
        body = QLabel(self._digest)
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{COLORS['ink']}; font-size:12.5px;")
        lay.addWidget(body)
        return card

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
