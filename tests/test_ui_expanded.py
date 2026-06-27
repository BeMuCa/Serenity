"""
============================================================
Author:  Berk
Created: 2026-06-27
Purpose: Headless smoke tests for the Notes-expand UI foundation (dock_left_of + ExpandedPanel).
Role:    Under QT_QPA_PLATFORM=offscreen, assert platform_win.dock_left_of places a panel flush
         LEFT of an anchor on the anchor's screen and clamps/reduces width to keep the header on
         screen (P2-13), and that ExpandedPanel docks-left on show, routes both the X button and
         Esc through closeRequested (P2-12), and survives a torn-down anchor on close (P3-5).

Test classes:
- TestDockLeftOf - geometry: flush-left when room, left-clamp + width reduce when off-screen
- TestExpandedPanel - builds, docks left on show, Esc/close emit closeRequested, torn-down anchor
============================================================
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from serenity.ui import platform_win  # noqa: E402
from serenity.ui.expanded_panel import ExpandedPanel  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _screen_geo():
    screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry()


class TestDockLeftOf:
    def test_flush_left_when_room(self, qapp):
        geo = _screen_geo()
        anchor = QWidget()
        # anchor flush against the right edge (like the dock), narrow panel that fits to its left
        width = 400
        anchor.setGeometry(geo.right() - 348 + 1, geo.top(), 348, geo.height())
        panel = QWidget()
        assert platform_win.dock_left_of(panel, anchor, width) is True
        assert panel.x() == anchor.x() - width
        assert panel.width() == width

    def test_clamps_left_edge_and_reduces_width_when_off_screen(self, qapp):
        geo = _screen_geo()
        anchor = QWidget()
        # anchor near the LEFT edge so a wide panel to its left would run off-screen
        anchor.setGeometry(geo.left() + 100, geo.top(), 200, geo.height())
        panel = QWidget()
        width = 1000  # far wider than the 100px gap to the left edge
        assert platform_win.dock_left_of(panel, anchor, width) is True
        assert panel.x() >= geo.left()
        # width reduced so the panel's right edge still ends at the anchor's left edge
        assert panel.width() <= anchor.x() - geo.left()
        assert panel.x() + panel.width() == anchor.x()

    def test_returns_false_on_bad_anchor(self, qapp):
        # a non-widget anchor must not raise; guarded -> False
        assert platform_win.dock_left_of(QWidget(), object(), 300) is False


class TestExpandedPanel:
    def _panel(self, anchor=None):
        if anchor is None:
            geo = _screen_geo()
            anchor = QWidget()
            anchor.setGeometry(geo.right() - 348 + 1, geo.top(), 348, geo.height())
            anchor.show()
        content = QLabel("body")
        return ExpandedPanel("My Note", content, anchor), anchor

    def test_builds_and_sets_title(self, qapp):
        panel, _ = self._panel()
        panel.set_title("Renamed")
        assert "Renamed" in panel._title_label.text()

    def test_docks_left_on_show(self, qapp):
        panel, anchor = self._panel()
        panel.show()
        # full height of the anchor's screen, flush left of the anchor (room exists)
        assert panel.x() + panel.width() == anchor.x()

    def test_close_button_emits_close_requested(self, qapp):
        panel, _ = self._panel()
        seen = []
        panel.closeRequested.connect(lambda: seen.append(True))
        panel._close_btn.click()
        assert seen == [True]

    def test_escape_emits_close_requested(self, qapp):
        panel, _ = self._panel()
        seen = []
        panel.closeRequested.connect(lambda: seen.append(True))
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        panel.keyPressEvent(ev)
        assert seen == [True]

    def test_close_with_torn_down_anchor_does_not_raise(self, qapp):
        panel, anchor = self._panel()
        panel.show()
        anchor.deleteLater()
        anchor.close()
        # restore-focus path must swallow the deleted-C++-object RuntimeError (P3-5)
        panel.close()
