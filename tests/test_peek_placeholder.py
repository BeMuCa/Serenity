"""
============================================================
Author:  Berk
Created: 2026-07-03
Purpose: Tests for the privacy-blurred urgency-peek placeholder widget.
Role:    Guards the blurred surface's content rules (R-E/R-F: relative time only,
         never title/None/elapsed-seconds, no tooltip), the tick protocol (R-B) and
         the two-click armed confirm (R-D) headless.

Test classes:
- TestPlaceholderText - the three R-E content forms + privacy assertions
- TestPlaceholderTick - needs_tick/tick keep the countdown live, overdue flip
- TestArmedConfirm - click -> armed -> gate -> reveal_requested; auto-disarm
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from serenity.core.models import Todo
from serenity.ui.peek_placeholder import PeekPlaceholder

NOW = datetime(2026, 7, 3, 12, 0, 0)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _texts(w):
    return [l.text() for l in w.findChildren(QLabel)]


class TestPlaceholderText:
    def test_due_form(self, qapp):
        t = Todo(title="secret meeting", context="private", due=NOW + timedelta(minutes=47))
        w = PeekPlaceholder(t, now=NOW)
        joined = " ".join(_texts(w))
        assert "⏰ in 47 min · 🔒 Private item" in joined

    def test_timer_running_form_no_elapsed_seconds(self, qapp):
        t = Todo(title="secret", context="private", timer_running_since=NOW, timer_seconds=754)
        w = PeekPlaceholder(t, now=NOW)
        joined = " ".join(_texts(w))
        assert "▶ running · 🔒 Private item" in joined
        assert "⏰" not in joined and "754" not in joined and "None" not in joined

    def test_in_progress_form(self, qapp):
        t = Todo(title="secret", context="business", in_progress=True)
        w = PeekPlaceholder(t, now=NOW)
        assert "● in progress · 🔒 Business item" in " ".join(_texts(w))

    def test_privacy_no_title_tooltip_accessible(self, qapp):
        t = Todo(title="fire the intern", context="private", tags=["hr"],
                 category="meeting", due=NOW + timedelta(hours=1))
        w = PeekPlaceholder(t, now=NOW)
        joined = " ".join(_texts(w))
        assert "fire the intern" not in joined and "hr" not in joined and "meeting" not in joined
        assert w.toolTip() == "" and w.accessibleName() == ""
        assert all(l.toolTip() == "" for l in w.findChildren(QLabel))


class TestPlaceholderTick:
    def test_needs_tick_true_while_shown(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(hours=1))
        assert PeekPlaceholder(t, now=NOW).needs_tick() is True

    def test_tick_updates_countdown_and_overdue_flip(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(minutes=30))
        w = PeekPlaceholder(t, now=NOW)
        w.tick(NOW + timedelta(minutes=20))
        assert "in 10 min" in " ".join(_texts(w))
        w.tick(NOW + timedelta(minutes=42))
        assert "overdue 12 min" in " ".join(_texts(w))


class TestArmedConfirm:
    def _widget(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(hours=1))
        w = PeekPlaceholder(t, now=NOW)
        fired = []
        w.reveal_requested.connect(lambda: fired.append(True))
        return w, fired

    def test_first_click_arms_never_reveals(self, qapp):
        w, fired = self._widget(qapp)
        w.mousePressEvent(None)
        assert fired == []
        assert "Switch to Private?" in " ".join(_texts(w))
        assert w._disarm_timer.isActive()

    def test_click_within_doubleclick_interval_ignored(self, qapp, monkeypatch):
        w, fired = self._widget(qapp)
        w.mousePressEvent(None)                       # arm
        monkeypatch.setattr(w, "_confirm_gate_open", lambda: False)
        w.mousePressEvent(None)                       # rapid second click (double-click)
        assert fired == []                            # armed but never flips

    def test_deliberate_second_click_reveals_once(self, qapp, monkeypatch):
        w, fired = self._widget(qapp)
        w.mousePressEvent(None)
        monkeypatch.setattr(w, "_confirm_gate_open", lambda: True)
        w.mousePressEvent(None)
        assert fired == [True]

    def test_auto_disarm_restores_blurred_text(self, qapp):
        w, fired = self._widget(qapp)
        w.mousePressEvent(None)
        w._disarm()                                   # what the 3s timer fires
        joined = " ".join(_texts(w))
        assert "Switch to" not in joined and "🔒 Private item" in joined
        assert fired == []

    def test_tick_while_armed_keeps_confirm_text(self, qapp):
        w, fired = self._widget(qapp)
        w.mousePressEvent(None)
        w.tick(NOW + timedelta(minutes=5))
        assert "Switch to Private?" in " ".join(_texts(w))   # tick never clobbers the prompt


class TestArmedConfirmUnmocked:
    """QA rerun: the R-D gate itself must be exercised un-mocked - a deleted/flipped
    gate or a missing _arm_clock.start() must fail these."""

    def _widget(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(hours=1))
        w = PeekPlaceholder(t, now=NOW)
        fired = []
        w.reveal_requested.connect(lambda: fired.append(True))
        return w, fired

    def test_rapid_double_click_never_flips_real_gate(self, qapp):
        old = QApplication.doubleClickInterval()
        QApplication.setDoubleClickInterval(100000)      # any human-speed click is "rapid"
        try:
            w, fired = self._widget(qapp)
            w.mousePressEvent(None)                      # arm
            w.mousePressEvent(None)                      # immediate second click, REAL gate
            assert fired == []
            assert "Switch to Private?" in " ".join(_texts(w))   # still armed, never flipped
        finally:
            QApplication.setDoubleClickInterval(old)

    def test_deliberate_confirm_fires_real_gate(self, qapp):
        import time
        old = QApplication.doubleClickInterval()
        QApplication.setDoubleClickInterval(1)           # any pause counts as deliberate
        try:
            w, fired = self._widget(qapp)
            w.mousePressEvent(None)
            time.sleep(0.05)
            w.mousePressEvent(None)                      # REAL gate, past the interval
            assert fired == [True]
        finally:
            QApplication.setDoubleClickInterval(old)

    def test_auto_disarm_wiring_and_interval(self, qapp):
        from serenity.ui.peek_placeholder import DISARM_MS
        w, fired = self._widget(qapp)
        w.mousePressEvent(None)
        assert w._disarm_timer.isSingleShot()
        assert w._disarm_timer.interval() == DISARM_MS
        w._disarm_timer.timeout.emit()                   # the WIRING, not _disarm() directly
        joined = " ".join(_texts(w))
        assert "Switch to" not in joined and "🔒 Private item" in joined
        assert fired == []

    def test_due_wins_over_running_timer_form(self, qapp):
        # branch order: a due-dated todo with a running timer shows the countdown form
        t = Todo(title="s", context="private", due=NOW + timedelta(hours=1),
                 timer_running_since=NOW)
        w = PeekPlaceholder(t, now=NOW)
        joined = " ".join(_texts(w))
        assert "⏰ in 1 h" in joined and "▶ running" not in joined

    def test_dueless_placeholder_does_not_need_tick(self, qapp):
        # static R-E forms must not keep the view's 1s tick timer alive
        t = Todo(title="s", context="private", timer_running_since=NOW)
        assert PeekPlaceholder(t, now=NOW).needs_tick() is False
