"""
============================================================
Author:  Berk
Created: 2026-07-01
Purpose: UI tests for the Phase B context toggle (mascot selector + shell flip).
Role:    Under QT_QPA_PLATFORM=offscreen, assert the ring filters by context,
         rebuilds on an open-ring flip, emits the toggle signal, and (Task 5)
         the shell keeps every context surface in sync.

Test classes:
- TestMascotContext - selector filtering + open-ring rebuild + context bubble
- TestShellContext - flip/persist, mood-pose-only-when-idle, invalid coerce,
  title-bar+tray sync (flip + boot), in-ring + mini-window entry points
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from serenity.core import states
from serenity.core.settings import Settings
from serenity.ui.mascot_stage import MascotStage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.vault_path = str(tmp_path / "vault")
    s._path = tmp_path / "settings.json"
    return s


class TestMascotContext:
    def test_open_selector_shows_only_current_context(self, qapp, settings):
        settings.current_context = "private"
        m = MascotStage(settings)
        m.open_selector()
        labels = [b.activity for b in m._bubbles]
        assert "Chilling" in labels and "Coding" not in labels   # private set (+ Idle + context bubble)

    def test_flip_while_open_rebuilds_ring(self, qapp, settings):
        settings.current_context = "business"
        m = MascotStage(settings)
        m.open_selector()
        assert "Coding" in [b.activity for b in m._bubbles]
        settings.current_context = "private"                     # simulate a flip
        m.refresh_selector()
        assert m._selector_open                                  # ring stays open
        labels = [b.activity for b in m._bubbles]
        assert "Chilling" in labels and "Coding" not in labels   # rebuilt for the new context

    def test_context_bubble_emits_signal(self, qapp, settings):
        m = MascotStage(settings)
        fired = []
        m.context_toggle_requested.connect(lambda: fired.append(True))
        m.open_selector()
        ctx_bubble = next(b for b in m._bubbles if b.activity.startswith("→"))  # "-> Private"
        ctx_bubble.click()
        assert fired == [True]


class TestShellContext:
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

    def test_toggle_flips_and_persists(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh.toggle_context()
            assert sh.settings.context() == "private"
            assert Settings.load(sh.settings._path).context() == "private"   # saved to disk
        finally:
            sh.tray.hide()

    def test_mood_pose_only_when_idle(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            assert sh.activity_store.running() is None
            sh.set_context("private")
            assert sh.mascot.current_state == "chilling"    # private mood applied when idle
            sh.set_context("business")
            assert sh.mascot.current_state == "idle"        # business mood when idle (non-vacuous: was chilling)
            sh.activity_store.start("Coding")               # now tracking
            sh.set_context("private")
            assert sh.mascot.current_state == "idle"        # unchanged - span running, no mood flip
        finally:
            sh.tray.hide()

    def test_in_ring_bubble_flips_via_shell(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh.mascot.context_toggle_requested.emit()       # the real Shell._wire() connection
            assert sh.settings.context() == "private"
        finally:
            sh.tray.hide()

    def test_mini_mascot_mood_posed_on_flip(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            mini = sh._ensure_mini()                        # mini exists BEFORE the flip
            sh.set_context("private")
            assert mini.mascot.current_state == "chilling"  # _mascots() includes the mini
        finally:
            sh.tray.hide()

    def test_mini_created_after_flip_shows_context_mood(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh.set_context("private")                       # flip while NO mini exists
            mini = sh._ensure_mini()                        # created AFTER the flip
            assert mini.mascot.current_state == "chilling"  # _ensure_mini applies the mood
        finally:
            sh.tray.hide()

    def test_invalid_context_coerced(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh.set_context("bogus")                          # must not KeyError
            assert sh.settings.context() == "business"
        finally:
            sh.tray.hide()

    def test_title_bar_and_tray_synced_on_flip(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh.set_context("private")
            assert sh.title_bar.context_btn.isChecked()      # title-bar reflects private
            assert sh._context_action.isChecked()            # tray action reflects private
        finally:
            sh.tray.hide()

    def test_startup_applies_persisted_context_mood(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import platform_win
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.core import paths
        persisted = Settings()
        persisted._path = paths.config_dir() / "settings.json"
        persisted.current_context = "private"
        persisted.vault_path = str(tmp_path / "v")
        persisted.save()
        from serenity.ui.shell import Shell
        sh = Shell()
        try:
            assert sh.mascot.current_state == "chilling"     # booted with the private mood pose
            assert sh._context_action.text() == "Switch to Business"  # tray synced at boot
            assert sh._context_action.isChecked()                     # (not blank/unchecked)
            assert sh.title_bar.context_btn.isChecked()               # title-bar too
        finally:
            sh.tray.hide()
