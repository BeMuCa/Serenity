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

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.activity import week_start_dt
from ..core.digest import _fmt_hms, generate_digest
from ..core.diary import build_diary_week, DiaryLine
from ..core.ranking import is_cross_context
from ..core.states import color_for_label
from ..core.weekly_board import WeeklyBoard, build_board
from . import icons
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

    def __init__(self, activity_store, todo_store, llm=None, parent=None, note_store=None,
                 diary_store=None, settings=None, stamp=None):
        super().__init__(parent)
        self.activity_store = activity_store
        self.todo_store = todo_store
        # Optional local-LLM engine (core.llm.LLMEngine). None / unavailable -> the digest
        # degrades to the board's deterministic hint. The shell injects its engine if it has
        # one; tests inject a StubLLM. Never called at idle - only when the board is built.
        self.llm = llm
        # Optional stores for diary section (T8): when both present, build and render the
        # diary week section below the hints card. When either is None, skip the section.
        self.note_store = note_store
        self.diary_store = diary_store
        # Optional settings for current context (for cross-context markers). When None,
        # defaults to "business" context.
        self.settings = settings
        # Optional callable to stamp diary lines (T9): when provided, called at commit-time
        # to get (state_tag, context); when None, treated as (None, None).
        self._stamp = stamp
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
        # P3-1b: re-arm timer for safe_refresh's defer guard (mirrors todos_view's
        # TodosView._boundary_timer) - retried shortly after a deferred refresh so an
        # in-flight diary-line edit still gets picked up once it closes.
        self._refresh_defer_timer = QTimer(self)
        self._refresh_defer_timer.setSingleShot(True)
        self._refresh_defer_timer.timeout.connect(self.safe_refresh)
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
        # T8: Diary section (below hints card) when both stores are wired
        if self.diary_store is not None and self.note_store is not None:
            self._body.addWidget(self._diary_section(now, is_current_week))

    def safe_refresh(self) -> None:
        """refresh() for input-UNCORRELATED triggers (Friday auto-open, a diary commit
        from the capture bar): mirrors todos_view.TodosView.safe_refresh (P3-1b).

        A bare refresh() deleteLater's every body widget, destroying an in-flight inline
        diary-line edit (or a half-typed capture line) and its typed text. When a diary-line
        editor or the diary capture input is focused, defer to a short timer instead of
        tearing the section down under the user's hands."""
        from PySide6.QtWidgets import QApplication
        focus = QApplication.focusWidget()
        editing = isinstance(focus, QLineEdit) and focus.objectName() in ("diaryLineEditor", "diaryInput")
        if editing:
            self._refresh_defer_timer.start(2000)
            return
        self.refresh()

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

    def _diary_section(self, now: datetime, is_current_week: bool) -> QFrame:
        """T8: Render the diary section — collapsible days with woven items + cross-context marker.
        T9: Adds input widget at top with empty-guard (P3-2), current-week only (M2): a past-week
        capture would still be stamped ts=now() by _commit_diary_line and file under the CURRENT
        week, vanishing from the viewed week - so the input only appears when viewing this week.

        Builds per-day groups from activity spans, completed todos, created notes, and diary
        lines. Each day is collapsible (thin header when empty). Items are woven into spans
        or placed in untracked. Cross-context marker shown when item.context != current_context.
        """
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        title = QLabel("Diary")
        title.setObjectName("sectLabel")
        lay.addWidget(title)

        # T9: Input widget at top (when stores are wired and viewing the current week)
        if self.diary_store is not None and is_current_week:
            self._diary_input = QLineEdit()
            self._diary_input.setObjectName("diaryInput")  # marker for safe_refresh's defer guard
            self._diary_input.setPlaceholderText("What did you do?")
            self._diary_input.returnPressed.connect(self._commit_diary_line)
            lay.addWidget(self._diary_input)
        else:
            self._diary_input = None

        # Get current context for cross-context marker check
        ctx = self.settings.context() if self.settings else "business"

        # Build the diary week structure
        entries = self.activity_store.log().entries()
        todos = [t for t in self.todo_store.all() if not t.deleted]
        notes = self.note_store.all_active()  # Already excludes deleted
        lines = self.diary_store.all()

        days = build_diary_week(entries, todos, notes, lines, self._anchor or now, now)

        # Render each day (Mon-Sun). Empty days still render their date header (a
        # thin header, per the docstring above) - only the spans/items below it
        # are skipped when there is nothing to weave.
        for day in days:
            day_header = QLabel(day.date.strftime("%a, %b %d"))
            day_header.setObjectName("diaryDayHeader")
            day_header.setStyleSheet(f"color:{COLORS['ink']}; font-size:12.5px; font-weight:600;")
            lay.addWidget(day_header)

            if not day.spans and not day.untracked:
                continue  # thin header only - nothing to weave for this day

            # Render spans for this day
            for span in day.spans:
                self._render_span(lay, span, ctx)

            # Untracked items (no covering span)
            if day.untracked:
                self._render_untracked_group(lay, day.untracked, ctx)

        return card

    def _commit_diary_line(self) -> None:
        """T9: Commit a diary line from the input widget with empty-guard (P3-2).

        Strip the input text; if empty, return (no-op, no ghost line). Otherwise, stamp
        the line with state_tag/context, add it to diary_store, and refresh the section
        (which rebuilds a fresh, empty input) so the new line appears.
        """
        if not self.diary_store:
            return
        text = self._diary_input.text().strip()
        if not text:
            return
        st, ctx = self._stamp() if self._stamp else (None, None)
        self.diary_store.add(DiaryLine(ts=datetime.now(), text=text, state_tag=st, context=ctx))
        self.refresh()

    def _render_span(self, parent_lay: QVBoxLayout, span, ctx: str) -> None:
        """Render one activity span: category label + time range + color dot + woven items."""
        # Span header: category, time range, color dot
        span_header = QHBoxLayout()
        span_header.setContentsMargins(12, 0, 0, 0)
        span_header.setSpacing(8)

        # Color dot (registry color for category)
        color = color_for_label(span.category)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:10px;")
        span_header.addWidget(dot)

        # Category label
        cat_label = QLabel(span.category)
        cat_label.setStyleSheet(f"color:{COLORS['ink']}; font-size:12px;")
        span_header.addWidget(cat_label)

        # Time range (start–end)
        time_str = f"{span.start.strftime('%H:%M')}–{span.end.strftime('%H:%M')}"
        time_label = QLabel(time_str)
        time_label.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11px;")
        span_header.addWidget(time_label)
        span_header.addStretch(1)

        parent_lay.addLayout(span_header)

        # Render items within the span
        for item in span.items:
            self._render_item(parent_lay, item, ctx)

    def _render_untracked_group(self, parent_lay: QVBoxLayout, items, ctx: str) -> None:
        """Render untracked items (no covering span)."""
        header = QLabel("Untracked")
        header.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11px; font-weight:500;")
        parent_lay.addWidget(header)

        for item in items:
            self._render_item(parent_lay, item, ctx)

    def _render_item(self, parent_lay: QVBoxLayout, item, ctx: str) -> None:
        """Render one woven item (todo/note/diary) with icon, text, and cross-context marker.

        Diary-kind items ONLY (T10) get inline edit (double-click the text) + a delete
        button - a woven todo/note has no DiaryStore line here for edit/delete to target."""
        row = QHBoxLayout()
        row.setContentsMargins(24, 2, 0, 2)
        row.setSpacing(6)

        # Icon: ✓ for todo, + for note, ✎ for diary
        icon_map = {
            "todo": "✓",
            "note": "+",
            "diary": "✎",
        }
        icon_str = icon_map.get(item.kind, "")
        icon = QLabel(icon_str)
        icon.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11px;")
        row.addWidget(icon)

        # Item text
        text = QLabel(item.text)
        text.setWordWrap(True)
        text.setStyleSheet(f"color:{COLORS['ink']}; font-size:11px;")
        row.addWidget(text, 1)

        # Cross-context marker (P3-3): show ONLY when is_cross_context returns True
        if is_cross_context(item, ctx):
            marker = QLabel("✦")
            marker.setStyleSheet(f"color:#f59e0b; font-size:9px;")
            marker.setToolTip(f"From context: {item.context}")
            row.addWidget(marker)

        # Inline edit + delete (T10): diary-kind items only.
        if item.kind == "diary":
            text.setToolTip("Double-click to edit")
            text.mouseDoubleClickEvent = lambda e, r=row, t=text, i=item: (
                self._edit_diary_line(r, t, i))
            del_btn = QPushButton()
            del_btn.setObjectName("iconbtn")
            del_btn.setIcon(icons.icon("trash", COLORS["ink3"], 11))
            del_btn.setFixedSize(18, 18)
            del_btn.setToolTip("Delete")
            del_btn.clicked.connect(lambda _=False, i=item: self._delete_diary_line(i.id))
            row.addWidget(del_btn)

        parent_lay.addLayout(row)

    def _edit_diary_line(self, row: QHBoxLayout, label: QLabel, item) -> None:
        """Swap a diary line's text label for a line edit; commit on Enter/focus-out.

        Text-only via diary_store.edit() (never touches ts/state_tag/context, T10). An
        empty commit is a no-op - keeps the original line rather than blanking it."""
        editor = QLineEdit(item.text)
        editor.setObjectName("diaryLineEditor")  # marker for safe_refresh's defer guard
        editor.setStyleSheet("font-size:11px;")
        idx = row.indexOf(label)
        row.takeAt(idx)
        label.hide()
        row.insertWidget(idx, editor, 1)
        editor.setFocus()
        editor.selectAll()

        def commit():
            text = editor.text().strip()
            if text:
                self.diary_store.edit(item.id, text)
            self.refresh()

        editor.editingFinished.connect(commit)

    def _delete_diary_line(self, line_id: str) -> None:
        """Delete a diary line after an explicit confirm (irreversible, T10)."""
        if not self._confirm_delete_diary():
            return
        self.diary_store.delete(line_id)
        self.refresh()

    def _confirm_delete_diary(self) -> bool:
        """Ask before deleting a diary line. True only on an explicit Yes.

        Mirrors trash_view._confirm_purge - a single misclick must not destroy the line."""
        reply = QMessageBox.question(
            self,
            "Delete line?",
            "Delete this diary line? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return reply == QMessageBox.Yes
