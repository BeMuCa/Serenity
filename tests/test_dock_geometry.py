"""
============================================================
Author:  Berk
Created: 2026-08-12
Purpose: Verify the dock sizes itself to the screen it is actually ON (not always the
         primary one) and re-adapts when that screen changes - monitors of different
         heights, a monitor plugged in, or a resolution change.
Role:    Headless regression for ui/platform_win.dock_right + keep_docked. Sizing to the
         PRIMARY screen while the compositor places the window on a SHORTER one pushes the
         top of the dock (where the mascot stands) off-screen.

Test classes:
- TestDockRightUsesTheWindowsScreen - the window's own screen wins over the primary
- TestKeepDocked - a screen change re-applies the dock geometry
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from serenity.ui import platform_win  # noqa: E402


class _FakeScreen:
    """Stands in for a QScreen: only availableGeometry() is consulted for placement."""

    def __init__(self, rect: QRect):
        self._rect = rect

    def availableGeometry(self) -> QRect:      # noqa: N802 (Qt API shape)
        return self._rect


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class TestDockRightUsesTheWindowsScreen:
    def test_height_follows_the_passed_screen(self, qapp):
        w = QWidget()
        tall = _FakeScreen(QRect(0, 0, 1920, 2160))
        assert platform_win.dock_right(w, 348, screen=tall)
        assert w.height() == 2160

    def test_a_shorter_second_screen_gives_a_shorter_dock(self, qapp):
        w = QWidget()
        short = _FakeScreen(QRect(1920, 0, 1280, 1024))
        assert platform_win.dock_right(w, 348, screen=short)
        assert w.height() == 1024

    def test_it_sits_flush_against_that_screens_right_edge(self, qapp):
        w = QWidget()
        second = _FakeScreen(QRect(1920, 0, 1280, 1024))
        platform_win.dock_right(w, 348, screen=second)
        # right edge of the screen == right edge of the window (Qt right() is inclusive)
        assert w.geometry().right() == 1920 + 1280 - 1

    def test_top_matches_the_screens_top(self, qapp):
        w = QWidget()
        offset = _FakeScreen(QRect(0, 300, 1920, 700))
        platform_win.dock_right(w, 348, screen=offset)
        assert w.geometry().top() == 300

    def test_a_missing_screen_is_a_no_op_not_a_crash(self, qapp):
        assert platform_win.dock_right(QWidget(), 348, screen=object()) is False


class TestKeepDocked:
    def test_a_screen_change_re_docks_the_window(self, qapp):
        w = QWidget()
        first = _FakeScreen(QRect(0, 0, 1920, 2160))
        second = _FakeScreen(QRect(1920, 0, 1280, 1024))
        current = {"screen": first}
        redock = platform_win.keep_docked(w, 348, screen_provider=lambda: current["screen"])
        redock()
        assert w.height() == 2160
        current["screen"] = second
        redock()
        assert w.height() == 1024

    def test_it_survives_a_provider_that_returns_nothing(self, qapp):
        w = QWidget()
        redock = platform_win.keep_docked(w, 348, screen_provider=lambda: None)
        redock()        # must not raise: a monitor can vanish between signal and slot
