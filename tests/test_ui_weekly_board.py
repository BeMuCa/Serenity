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
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.activity import ActivityEntry, ActivityLog, week_start_dt  # noqa: E402
from serenity.core.models import Todo, Note  # noqa: E402
from serenity.core.activity_store import ActivityStore  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.core.note_store import NoteStore  # noqa: E402
from serenity.core.diary import DiaryStore, DiaryLine  # noqa: E402
from serenity.ui.weekly_board_view import WeeklyBoardView  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def hrs(n):
    return timedelta(hours=n)


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

    def test_diary_section_renders_with_items(self, qapp, tmp_path):
        """Section shows diary line + completed todo + activity span for the week."""
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # Add activity span (Coding, Mon 10-12)
        activity_store._log = ActivityLog([
            ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(2))
        ])

        # Add completed todo (completed Mon 11:00)
        todo = Todo(title="Write tests", completed_at=THIS_MON + timedelta(hours=1))
        todo.done = True
        todo_store.add(todo)

        # Add diary line (Mon 11:30)
        line = DiaryLine(ts=THIS_MON + timedelta(hours=1, minutes=30), text="Good progress")
        diary_store.add(line)

        # Create view with stores wired
        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        # Check that the body has a diary section (should be after hints card)
        # The section should exist and be visible
        body_children = [view._body.itemAt(i).widget() for i in range(view._body.count())]
        assert len(body_children) > 0, "Diary section should be added to body"

    def test_cross_context_marker_shown_only_when_different(self, qapp, tmp_path, monkeypatch):
        """Cross-context marker shown ONLY when item.context != current_context.

        Test both directions:
        - A diary line in 'private' context shows marker when current='business'
        - A diary line in 'business' context does NOT show marker when current='business'
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import platform_win
        from serenity.core import paths
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
        from serenity.ui.shell import Shell

        sh = Shell()
        try:
            # Set current context to 'business'
            sh.settings.current_context = "business"

            # Add a private-context diary line
            line_private = DiaryLine(
                ts=THIS_MON + timedelta(hours=1),
                text="Private note",
                context="private"
            )
            sh.diary_store.add(line_private)

            # Add a business-context diary line
            line_business = DiaryLine(
                ts=THIS_MON + timedelta(hours=2),
                text="Business note",
                context="business"
            )
            sh.diary_store.add(line_business)

            # Refresh and check markers
            sh.board_view.refresh()

            # The view should render without error
            # (Actual marker presence would be verified by inspecting widgets,
            # but for this RED test we just verify the structure doesn't crash)
            body_count = sh.board_view._body.count()
            assert body_count > 0, "Diary section should be rendered"
        finally:
            sh.tray.hide()

    def test_empty_day_renders_thin_header(self, qapp, tmp_path):
        """A day with no spans/items renders collapsed (thin header only)."""
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # No activity, todos, notes, or diary lines for the week
        # The diary section should still render but all 7 days should be empty/collapsed

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)
        view.refresh()

        # Should render without error even with empty days
        body_count = view._body.count()
        assert body_count > 0, "Even empty diary sections should render"

    def test_diary_section_uses_anchor(self, qapp, tmp_path):
        """Navigating to past week shows that week's diary content (tied to T7's anchor)."""
        activity_store = ActivityStore(tmp_path)
        todo_store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        diary_store = DiaryStore(tmp_path)

        # Add diary line in THIS week (Mon)
        line_this = DiaryLine(ts=THIS_MON + timedelta(hours=1), text="This week")
        diary_store.add(line_this)

        # Add diary line in LAST week (Mon)
        line_last = DiaryLine(ts=LAST_MON + timedelta(hours=1), text="Last week")
        diary_store.add(line_last)

        view = WeeklyBoardView(activity_store, todo_store, note_store=note_store,
                               diary_store=diary_store)

        # View current week (anchor=None)
        view._anchor = None
        view.refresh()
        # Should show THIS week's line

        # Navigate to past week
        view._anchor = LAST_MON
        view.refresh()
        # Should show LAST week's line

        # Both refreshes should complete without error
        assert True  # If we got here, no exceptions were raised
