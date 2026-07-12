"""
============================================================
Author:  Berk
Created: 2026-07-10
Purpose: Headless smoke tests for the Weekly Board view (ui.weekly_board_view).
Role:    Under QT_QPA_PLATFORM=offscreen, assert WeeklyBoardView builds + refresh()
         renders, nav controls work (prev/next/today), digest is gated to current week
         only, and completed count is bounded by completed_at (not updated).

Test classes:
- TestWeeklyBoardView - builds, renders, nav anchor, digest gating
- TestWeeklyBoardNav - prev/next/today shift anchor ±7d or reset to None
============================================================
"""
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox  # noqa: E402

from serenity.core.activity import ActivityEntry, ActivityLog, week_start_dt  # noqa: E402
from serenity.core.models import Todo, Note  # noqa: E402
from serenity.core.activity_store import ActivityStore  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.core.note_store import NoteStore  # noqa: E402
from serenity.core.diary import DiaryStore, DiaryLine  # noqa: E402
from serenity.core.settings import Settings  # noqa: E402
from serenity.ui.weekly_board_view import WeeklyBoardView  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def hrs(n):
    return timedelta(hours=n)


def _diary_card(view):
    """The diary section's own QFrame - always the last widget refresh() adds to
    _body when both note_store and diary_store are wired. Scoping findChildren()
    to this card (instead of the whole view) sidesteps stale widgets: refresh()
    only schedules the OLD cards for deleteLater() rather than deleting them
    synchronously, so without an event loop spin they would otherwise still be
    found as children of `view` alongside the fresh ones."""
    return view._body.itemAt(view._body.count() - 1).widget()


# Test week: Friday 2026-06-19 (current week = Mon 2026-06-15)
NOW = datetime(2026, 6, 19, 17, 30)
THIS_MON = datetime(2026, 6, 15, 9, 0)
LAST_MON = datetime(2026, 6, 8, 9, 0)


class TestWeeklyBoardView:
    def test_builds_empty(self, qapp, tmp_path):
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        view = WeeklyBoardView(activity_store, todo_store)
        view.refresh()  # must not raise on an empty store

    def test_renders_with_activity(self, qapp, tmp_path):
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        # Load activity data for testing
        activity_store._log = ActivityLog([
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(2))
        ])
        view = WeeklyBoardView(activity_store, todo_store)
        view.refresh()  # must not raise


class TestWeeklyBoardNav:
    def test_anchor_initialized_to_none(self, qapp, tmp_path):
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        view = WeeklyBoardView(activity_store, todo_store)
        assert view._anchor is None

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_go_prev_shifts_anchor_back_7_days(self, mock_datetime, qapp, tmp_path):
        # Mock datetime.now() to return NOW so _go_prev computes relative to that
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        view = WeeklyBoardView(activity_store, todo_store)
        assert view._anchor is None
        # First prev: from current week -> 1 week back
        view._go_prev()
        expected = week_start_dt(NOW) - timedelta(days=7)
        assert view._anchor == expected
        # Second prev: shift back another week
        view._go_prev()
        expected = expected - timedelta(days=7)
        assert view._anchor == expected

    def test_go_next_shifts_anchor_forward_7_days(self, qapp, tmp_path):
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        view = WeeklyBoardView(activity_store, todo_store)
        view._go_prev()
        start_anchor = view._anchor
        view._go_next()
        assert view._anchor == start_anchor + timedelta(days=7)

    def test_go_today_resets_anchor_to_none(self, qapp, tmp_path):
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        view = WeeklyBoardView(activity_store, todo_store)
        view._go_prev()
        assert view._anchor is not None
        view._go_today()
        assert view._anchor is None

    def test_nav_calls_refresh(self, qapp, tmp_path):
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        view = WeeklyBoardView(activity_store, todo_store)
        with patch.object(view, "refresh") as mock_refresh:
            view._go_prev()
            mock_refresh.assert_called_once()
        with patch.object(view, "refresh") as mock_refresh:
            view._go_next()
            mock_refresh.assert_called_once()
        with patch.object(view, "refresh") as mock_refresh:
            view._go_today()
            mock_refresh.assert_called_once()

    def test_auto_open_resets_anchor_to_current_week(self, qapp, tmp_path, monkeypatch):
        """Auto-open (Friday refresh) must reset anchor from past week to current.

        When the user browsed a past week and left the app there, the Friday
        auto-open must show the CURRENT week (anchor=None), not the stale past week.
        """
        # Setup Shell with real state (following test_ui_diary_capture.py pattern)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import platform_win
        from serenity.core import paths
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
        from serenity.ui.shell import Shell
        sh = Shell()

        try:
            # Manually set board anchor to a past week (before now)
            sh.board_view._anchor = LAST_MON
            assert sh.board_view._anchor is not None

            # Monkeypatch should_auto_open_board to return True
            # (simulates Friday 17:30 auto-open window)
            monkeypatch.setattr(
                "serenity.core.activity.should_auto_open_board",
                lambda now, last_open: True
            )

            # Call the auto-open method - it should reset anchor to None
            sh._maybe_auto_open_board()

            # After auto-open, anchor should be reset to None (current week)
            assert sh.board_view._anchor is None
        finally:
            sh.tray.hide()


class TestWeeklyBoardDigestGating:
    def test_digest_not_generated_for_past_week(self, qapp, tmp_path):
        """Browsing a non-empty past week must NOT call generate_digest (no model load).

        This test proves the is_current_week gate works by using a NON-EMPTY past week
        whose board signature differs from the current week. Without the gate, generate_digest
        would be called; WITH the gate, it is suppressed. Empty past weeks would suppress
        digest regardless (cache hit on matching signature), making the test vacuous.
        """
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)

        # Add activity to PAST week (LAST_MON) with content
        activity_store._log = ActivityLog([
            ActivityEntry("Development", LAST_MON, LAST_MON + hrs(3))
        ])

        mock_llm = MagicMock()
        mock_llm.available = True

        view = WeeklyBoardView(activity_store, todo_store, llm=mock_llm)
        # Navigate to past week (which now has activity)
        view._go_prev()
        assert view._anchor is not None

        # Clear the cached digest to force a fresh check on the next refresh.
        # The past week board signature differs from current week (has 3h activity vs 0h),
        # so WITHOUT the is_current_week gate, generate_digest WOULD be called.
        # WITH the gate, it must be suppressed.
        view._digest_sig = None
        view._digest = ""

        with patch("serenity.ui.weekly_board_view.generate_digest") as mock_digest:
            view.refresh()
            # Must NOT call generate_digest for past week, even though content differs
            mock_digest.assert_not_called()

    def test_digest_generated_for_current_week(self, qapp, tmp_path):
        """Viewing current week (anchor=None) must call generate_digest if LLM available."""
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        mock_llm = MagicMock()
        mock_llm.available = True

        view = WeeklyBoardView(activity_store, todo_store, llm=mock_llm)
        assert view._anchor is None  # Current week

        with patch("serenity.ui.weekly_board_view.generate_digest") as mock_digest:
            mock_digest.return_value = "Test digest"
            # Clear the cached digest to force regeneration
            view._digest_sig = None
            view._digest = ""
            view.refresh()
            # Must call generate_digest for current week
            mock_digest.assert_called_once()


class TestWeeklyBoardCompletedBounding:
    def test_completed_count_bounded_by_completed_at(self, qapp, tmp_path):
        """_completed_this_week must count todos by completed_at (not updated) in anchored week.

        - Week 1: todo A completed in week 1 -> count=1
        - Week 2: todo B completed in week 2 -> count=1
        - Edit todo A in week 2 (updated=week 2, completed_at=week 1) -> viewing week 2 still
          counts it as NOT in week 2 (it was completed in week 1).
        """
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)

        # Create todos with explicit completed_at times
        todo_a = Todo(title="Task A", completed_at=LAST_MON + hrs(2))
        todo_b = Todo(title="Task B", completed_at=THIS_MON + hrs(1))
        todo_store.add(todo_a)
        todo_store.add(todo_b)

        # Mark them done
        todo_a.done = True
        todo_a.updated = THIS_MON + hrs(5)  # Edited in current week but completed in last week
        todo_store.update(todo_a)

        todo_b.done = True
        todo_b.updated = THIS_MON + hrs(3)
        todo_store.update(todo_b)

        view = WeeklyBoardView(activity_store, todo_store)

        # View current week (anchor=None): should count only todo_b (completed_at in current week)
        count_current = view._completed_this_week(NOW)
        assert count_current == 1, f"Expected 1, got {count_current}"

        # View past week: anchor to LAST_MON and verify only todo_a is counted
        view._anchor = LAST_MON
        count_past = view._completed_this_week(NOW)  # now is irrelevant since anchor is set
        assert count_past == 1, f"Expected 1, got {count_past}"


class TestWeeklyBoardDiarySection:
    """Diary section renders below hints card: collapsible days + woven items + cross-context marker."""

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_diary_section_renders_with_items(self, mock_datetime, qapp, tmp_path):
        """Section shows diary line + completed todo + note + activity span, woven together."""
        # Pin datetime.now() to NOW so THIS_MON falls in the "current week" (anchor=None).
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # Add activity span (Coding, Mon 09:00-11:00)
        activity_store._log = ActivityLog([
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(2))
        ])

        # Add completed todo (completed Mon 10:00, inside the span)
        todo = Todo(title="Write tests", completed_at=THIS_MON + timedelta(hours=1))
        todo.done = True
        todo_store.add(todo)

        # Add a note (created Mon 10:20, inside the span). create() stamps `created`
        # with datetime.now(), so backdate it into the test week afterwards.
        note = note_store.create(title="Drafted outline")
        note.created = THIS_MON + timedelta(hours=1, minutes=20)

        # Add diary line (Mon 10:30, inside the span)
        line = DiaryLine(ts=THIS_MON + timedelta(hours=1, minutes=30), text="Good progress")
        diary_store.add(line)

        # Create view with stores wired
        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        texts = [lab.text() for lab in _diary_card(view).findChildren(QLabel)]

        # Span header: category label + time range render
        assert "Coding" in texts
        assert "09:00–11:00" in texts

        # Woven items: icon + title, for the todo (✓), note (+), and diary line (✎)
        assert "✓" in texts and "Write tests" in texts
        assert "+" in texts and "Drafted outline" in texts
        assert "✎" in texts and "Good progress" in texts

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_cross_context_marker_shown_only_when_different(self, mock_datetime, qapp, tmp_path):
        """Cross-context marker shown ONLY when item.context != current_context.

        Test both directions:
        - A diary line in 'private' context shows marker when current='business'
        - A diary line in 'business' context does NOT show marker when current='business'
        """
        # Pin datetime.now() to NOW so THIS_MON falls in the "current week" (anchor=None).
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)
        settings = Settings()
        settings.current_context = "business"

        # A private-context line (cross-context vs. current "business") -> marker shown
        line_private = DiaryLine(
            ts=THIS_MON + timedelta(hours=1),
            text="Private note",
            context="private",
        )
        diary_store.add(line_private)

        # A business-context line (matches current context) -> marker NOT shown
        line_business = DiaryLine(
            ts=THIS_MON + timedelta(hours=2),
            text="Business note",
            context="business",
        )
        diary_store.add(line_business)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store, settings=settings)
        view.refresh()

        labels = _diary_card(view).findChildren(QLabel)
        # Both item texts must actually render (sanity: items were woven at all)
        texts = [lab.text() for lab in labels]
        assert "Private note" in texts
        assert "Business note" in texts

        # The marker glyph carries a tooltip naming the item's source context - use it to
        # tell which item(s) got a marker without depending on layout traversal.
        marker_tooltips = {lab.toolTip() for lab in labels if lab.text() == "✦"}
        assert "From context: private" in marker_tooltips
        assert "From context: business" not in marker_tooltips

    def test_empty_day_renders_thin_header(self, qapp, tmp_path):
        """A day with no spans/items still renders (a thin header), not omitted."""
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # No activity, todos, notes, or diary lines for the week: every one of the
        # 7 days is empty, so this exercises the thin-header collapse for all of them.
        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        labels = _diary_card(view).findChildren(QLabel)
        day_headers = [lab for lab in labels if lab.objectName() == "diaryDayHeader"]
        # Every day of the week still gets its thin header widget...
        assert len(day_headers) == 7
        # ...but with no span/item children underneath it (nothing to weave).
        texts = [lab.text() for lab in labels]
        assert "✓" not in texts
        assert "✎" not in texts
        assert "+" not in texts

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_diary_section_uses_anchor(self, mock_datetime, qapp, tmp_path):
        """Navigating to past week shows that week's diary content (tied to T7's anchor)."""
        # Pin datetime.now() to NOW so THIS_MON's week is the "current week" (anchor=None).
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # Add diary line in THIS week (Mon)
        line_this = DiaryLine(ts=THIS_MON + timedelta(hours=1), text="This week diary")
        diary_store.add(line_this)

        # Add diary line in LAST week (Mon)
        line_last = DiaryLine(ts=LAST_MON + timedelta(hours=1), text="Last week diary")
        diary_store.add(line_last)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)

        # View current week (anchor=None) -> shows THIS week's line, not LAST week's
        view._anchor = None
        view.refresh()
        texts = [lab.text() for lab in _diary_card(view).findChildren(QLabel)]
        assert "This week diary" in texts
        assert "Last week diary" not in texts

        # Navigate to past week -> shows LAST week's line, not THIS week's
        view._anchor = LAST_MON
        view.refresh()
        texts = [lab.text() for lab in _diary_card(view).findChildren(QLabel)]
        assert "Last week diary" in texts
        assert "This week diary" not in texts


class TestWeeklyBoardDiaryInput:
    """Diary input widget (T9): one-line at top of section, stamps on commit, empty-guard P3-2."""

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_non_blank_commit_adds_stamped_line(self, mock_datetime, qapp, tmp_path):
        """Type text + commit -> DiaryLine added to store with stamped state_tag/context,
        the section re-renders showing the new line, and the input ends up empty (the
        commit handler leans entirely on refresh() rebuilding a fresh QLineEdit - there
        is no separate .clear() call)."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # Inject a mock stamp function returning a known (state_tag, context) pair
        mock_stamp = MagicMock(return_value=("tag_x", "context_y"))

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store, stamp=mock_stamp)
        view.refresh()

        # Type text into the input and commit (simulate Enter key or button click)
        test_text = "Did some coding"
        view._diary_input.setText(test_text)
        view._commit_diary_line()  # trigger the commit handler

        # Verify the line was added to the store with the exact text and stamp
        all_lines = diary_store.all()
        assert len(all_lines) == 1, f"Expected 1 line, got {len(all_lines)}"
        added = all_lines[0]
        assert added.text == test_text, f"Expected text '{test_text}', got '{added.text}'"
        assert added.state_tag == "tag_x", f"Expected state_tag 'tag_x', got '{added.state_tag}'"
        assert added.context == "context_y", f"Expected context 'context_y', got '{added.context}'"

        # Render-after-commit: the section re-rendered and the new line's item label
        # is actually present (not just recorded in the store).
        texts = [lab.text() for lab in _diary_card(view).findChildren(QLabel)]
        assert test_text in texts, f"Expected rendered item for '{test_text}', got {texts}"

        # Input-empty end-state: after a successful commit the visible input is empty.
        assert view._diary_input.text() == "", "Input should be empty after a successful commit"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_blank_input_no_op(self, mock_datetime, qapp, tmp_path):
        """Empty input -> no line added to store, input stays empty."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        # Leave input empty and commit
        view._diary_input.setText("")
        before_count = len(diary_store.all())
        view._commit_diary_line()
        after_count = len(diary_store.all())

        # No line should be added
        assert after_count == before_count, f"Expected no change, got {before_count} -> {after_count}"
        assert view._diary_input.text() == "", "Input should remain empty"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_whitespace_input_no_op(self, mock_datetime, qapp, tmp_path):
        """Whitespace-only input -> no line added to store (strip() guard)."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        # Type only whitespace and commit
        view._diary_input.setText("   ")
        before_count = len(diary_store.all())
        view._commit_diary_line()
        after_count = len(diary_store.all())

        # No line should be added (stripped text is empty)
        assert after_count == before_count, f"Expected no change, got {before_count} -> {after_count}"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_diary_input_rendered_in_section(self, mock_datetime, qapp, tmp_path):
        """The input widget is visible in the diary section (QLineEdit at top)."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        # The input should exist and be accessible
        assert hasattr(view, "_diary_input"), "WeeklyBoardView should have _diary_input attribute"
        assert view._diary_input.placeholderText() == "What did you do?", \
            "Input placeholder should be 'What did you do?'"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_input_absent_on_past_week_present_on_current(self, mock_datetime, qapp, tmp_path):
        """M2: the capture input only appears on the CURRENT week - _commit_diary_line
        stamps ts=now(), so a line typed while browsing a PAST week would silently file
        under the current week and vanish from the viewed week (a misleading "failed
        save"); backdating is a non-goal (spec sec 7)."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)

        # Past week (anchored to LAST_MON's week) -> no capture input at all
        view._anchor = LAST_MON
        view.refresh()
        assert view._diary_input is None
        inputs = [w for w in _diary_card(view).findChildren(QLineEdit)
                  if w.objectName() == "diaryInput"]
        assert not inputs, "capture input must not render on a past-week view"

        # Current week (anchor=None) -> capture input present
        view._anchor = None
        view.refresh()
        assert view._diary_input is not None
        inputs = [w for w in _diary_card(view).findChildren(QLineEdit)
                  if w.objectName() == "diaryInput"]
        assert len(inputs) == 1, "capture input must render on the current-week view"


def _dblclick(widget) -> None:
    """Dispatch a real double-click event (not None - the overridden handler ignores
    its event arg, but the built-in QLabel handler it replaces does not, so a real
    QMouseEvent is required to exercise both the pre- and post-implementation paths
    without crashing). Mirrors test_ui_calendar_week.py's QMouseEvent construction."""
    from PySide6.QtCore import QEvent, QPoint, Qt as _Qt
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonDblClick, QPoint(2, 2), _Qt.LeftButton,
                      _Qt.LeftButton, _Qt.NoModifier)
    widget.mouseDoubleClickEvent(ev)


class TestWeeklyBoardDiaryEditDelete:
    """T10: inline edit + delete for diary-kind lines only, plus the safe_refresh
    defer guard (P3-1b) that protects an in-flight inline edit from an uncorrelated
    refresh (Friday auto-open, a diary commit from the capture bar)."""

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_edit_updates_text_never_restamps(self, mock_datetime, qapp, tmp_path):
        """Double-click the rendered line -> inline editor; committing a new value
        updates ONLY diary_store's text, leaving ts/state_tag/context untouched."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        original_ts = THIS_MON + timedelta(hours=1)
        line = DiaryLine(ts=original_ts, text="Original text",
                          state_tag="focused", context="business")
        diary_store.add(line)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        labels = _diary_card(view).findChildren(QLabel)
        target = next(lab for lab in labels if lab.text() == "Original text")
        _dblclick(target)  # simulate the double-click affordance

        editors = [e for e in _diary_card(view).findChildren(QLineEdit)
                   if e.objectName() == "diaryLineEditor"]
        assert len(editors) == 1, f"Expected exactly one inline editor, got {len(editors)}"
        editor = editors[0]
        editor.setText("Updated text")
        editor.editingFinished.emit()  # commit (mirrors Enter / focus-out)

        updated = diary_store.get(line.id)
        assert updated.text == "Updated text"
        assert updated.state_tag == "focused", "edit must never restamp state_tag"
        assert updated.context == "business", "edit must never restamp context"
        assert updated.ts == original_ts, "edit must never restamp ts"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_empty_edit_keeps_original_text(self, mock_datetime, qapp, tmp_path):
        """Committing a blank/whitespace edit is a no-op - never blanks the line."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        line = DiaryLine(ts=THIS_MON + timedelta(hours=1), text="Keep this")
        diary_store.add(line)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        labels = _diary_card(view).findChildren(QLabel)
        target = next(lab for lab in labels if lab.text() == "Keep this")
        _dblclick(target)

        editor = next(e for e in _diary_card(view).findChildren(QLineEdit)
                      if e.objectName() == "diaryLineEditor")
        editor.setText("   ")
        editor.editingFinished.emit()

        assert diary_store.get(line.id).text == "Keep this"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_delete_confirmed_removes_line(self, mock_datetime, qapp, tmp_path, monkeypatch):
        """An accepted confirm deletes the line from the store AND the rendered section."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        line = DiaryLine(ts=THIS_MON + timedelta(hours=1), text="Delete me")
        diary_store.add(line)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        confirm_calls = []
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: confirm_calls.append(True) or QMessageBox.Yes)

        view._delete_diary_line(line.id)

        assert len(confirm_calls) == 1, "the confirm must actually be invoked"
        assert diary_store.get(line.id) is None
        texts = [lab.text() for lab in _diary_card(view).findChildren(QLabel)]
        assert "Delete me" not in texts

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_delete_rejected_keeps_line(self, mock_datetime, qapp, tmp_path, monkeypatch):
        """A rejected confirm (Cancel) keeps the line in the store."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        line = DiaryLine(ts=THIS_MON + timedelta(hours=1), text="Keep me")
        diary_store.add(line)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)

        view._delete_diary_line(line.id)

        assert diary_store.get(line.id) is not None
        assert diary_store.get(line.id).text == "Keep me"

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_defer_guard_protects_open_editor(self, mock_datetime, qapp, tmp_path):
        """P3-1b (the key test): an UNCORRELATED safe_refresh() (e.g. Friday auto-open,
        a diary commit from the capture bar) must DEFER the teardown while a diary-line
        inline editor is focused, so the open editor + its uncommitted text survive."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        line = DiaryLine(ts=THIS_MON + timedelta(hours=1), text="In progress")
        diary_store.add(line)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()
        view.show()  # focus only registers on a shown widget under offscreen QPA
        qapp.processEvents()  # let window-activation settle its own default focus first
        try:
            labels = _diary_card(view).findChildren(QLabel)
            target = next(lab for lab in labels if lab.text() == "In progress")
            _dblclick(target)

            editor = next(e for e in _diary_card(view).findChildren(QLineEdit)
                          if e.objectName() == "diaryLineEditor")
            editor.setText("half-typed edit")
            editor.setFocus()
            qapp.processEvents()
            assert QApplication.focusWidget() is editor  # sanity: focus really landed

            view.safe_refresh()  # the uncorrelated trigger under test

            # The editor must still be alive with its uncommitted text - teardown deferred.
            assert editor.text() == "half-typed edit"
            still_present = [e for e in _diary_card(view).findChildren(QLineEdit)
                             if e.objectName() == "diaryLineEditor"]
            assert len(still_present) == 1 and still_present[0] is editor
        finally:
            view.hide()

    @patch("serenity.ui.weekly_board_view.datetime")
    def test_defer_guard_protects_diary_input(self, mock_datetime, qapp, tmp_path):
        """M1: an UNCORRELATED safe_refresh() (e.g. Friday auto-open) must also DEFER
        teardown while the diary CAPTURE input (_diary_input, distinct from the inline
        line editor above) is focused - a Friday auto-open mid-typing "What did you
        do?" must not destroy the unsaved text."""
        mock_datetime.now.return_value = NOW
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()
        view.show()  # focus only registers on a shown widget under offscreen QPA
        qapp.processEvents()
        try:
            view._diary_input.setText("half-typed capture")
            view._diary_input.setFocus()
            qapp.processEvents()
            assert QApplication.focusWidget() is view._diary_input  # sanity: focus landed

            old_input = view._diary_input
            view.safe_refresh()  # the uncorrelated trigger under test

            # The input must still be alive with its uncommitted text - teardown deferred.
            assert view._diary_input is old_input, "teardown must be deferred, not rebuilt"
            assert view._diary_input.text() == "half-typed capture"
        finally:
            view.hide()
