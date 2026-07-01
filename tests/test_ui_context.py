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
