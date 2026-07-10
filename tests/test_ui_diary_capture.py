"""
============================================================
Author:  Berk
Created: 2026-07-10
Purpose: UI tests for Shell._commit_capture diary branch.
Role:    Under QT_QPA_PLATFORM=offscreen, assert a diary capture persists
         a DiaryLine with verbatim text + state_tag/context, refreshes the
         board view, skips tag-registry pollution, and handles empty text.

Test classes:
- TestDiaryCaptureIntegration - diary branch wiring
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock

from serenity.core.settings import Settings
from serenity.core.diary import DiaryStore, DiaryLine
from serenity.core.parser import parse_capture


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class TestDiaryCaptureIntegration:
    def _shell(self, tmp_path, monkeypatch, context="business"):
        # isolate config + vault (so a running span never leaks between tests) + no real autostart
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import platform_win
        from serenity.core import paths
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
        from serenity.ui.shell import Shell
        sh = Shell()
        sh.settings.current_context = context
        return sh

    def test_diary_capture_persists_line_with_stamp(self, qapp, tmp_path, monkeypatch):
        """A diary: capture persists a DiaryLine with verbatim text + state_tag/context."""
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Working")
            cap = parse_capture("diary: Update project roadmap")
            sh._pending = cap
            sh._pending_stamp = sh.stamp()
            sh._commit_capture(cap)

            # Check the line was persisted
            lines = sh.diary_store.all()
            assert len(lines) == 1
            line = lines[0]
            assert line.text == "Update project roadmap"
            assert line.state_tag == "working"
            assert line.context == "business"
        finally:
            sh.tray.hide()

    def test_diary_capture_no_tag_pollution(self, qapp, tmp_path, monkeypatch):
        """A diary capture with #hashtags does NOT add them to the tag registry."""
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            cap = parse_capture("diary: Planning #budget and #timeline for Q3")
            sh._pending = cap
            sh._pending_stamp = sh.stamp()

            # Record the initial tags
            initial_tags = set(sh.settings.tags)

            # Commit the diary capture
            sh._commit_capture(cap)

            # Verify no new tags were added
            final_tags = set(sh.settings.tags)
            assert final_tags == initial_tags
            assert "budget" not in final_tags
            assert "timeline" not in final_tags
        finally:
            sh.tray.hide()

    def test_diary_capture_empty_text_is_noop(self, qapp, tmp_path, monkeypatch):
        """A diary capture with blank verbatim persists NO line (no-op)."""
        sh = self._shell(tmp_path, monkeypatch)
        try:
            # Create a capture with empty verbatim
            cap = parse_capture("diary:")
            sh._pending = cap
            sh._pending_stamp = sh.stamp()
            sh._commit_capture(cap)

            # Nothing should be persisted
            lines = sh.diary_store.all()
            assert len(lines) == 0
        finally:
            sh.tray.hide()

    def test_diary_capture_refreshes_board_view(self, qapp, tmp_path, monkeypatch):
        """After a diary commit, the board view refresh is called."""
        sh = self._shell(tmp_path, monkeypatch)
        try:
            # Spy on board_view.refresh
            original_refresh = sh.board_view.refresh
            call_count = [0]

            def spy_refresh():
                call_count[0] += 1
                original_refresh()

            sh.board_view.refresh = spy_refresh

            cap = parse_capture("diary: Test the board refresh")
            sh._pending = cap
            sh._pending_stamp = sh.stamp()
            sh._commit_capture(cap)

            # board_view.refresh should have been called
            assert call_count[0] >= 1
        finally:
            sh.tray.hide()
