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
        w = PeekPlaceholder(t, "Private", now=NOW)
        joined = " ".join(_texts(w))
        assert "⏰ in 47 min · 🔒 Private item" in joined

    def test_timer_running_form_no_elapsed_seconds(self, qapp):
        t = Todo(title="secret", context="private", timer_running_since=NOW, timer_seconds=754)
        w = PeekPlaceholder(t, "Private", now=NOW)
        joined = " ".join(_texts(w))
        assert "▶ running · 🔒 Private item" in joined
        assert "⏰" not in joined and "754" not in joined and "None" not in joined

    def test_in_progress_form(self, qapp):
        t = Todo(title="secret", context="business", in_progress=True)
        w = PeekPlaceholder(t, "Business", now=NOW)
        assert "● in progress · 🔒 Business item" in " ".join(_texts(w))

    def test_privacy_no_title_tooltip_accessible(self, qapp):
        t = Todo(title="fire the intern", context="private", tags=["hr"],
                 category="meeting", due=NOW + timedelta(hours=1))
        w = PeekPlaceholder(t, "Private", now=NOW)
        joined = " ".join(_texts(w))
        assert "fire the intern" not in joined and "hr" not in joined and "meeting" not in joined
        assert w.toolTip() == "" and w.accessibleName() == ""
        assert all(l.toolTip() == "" for l in w.findChildren(QLabel))


class TestPlaceholderTick:
    def test_needs_tick_true_while_shown(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(hours=1))
        assert PeekPlaceholder(t, "Private", now=NOW).needs_tick() is True

    def test_tick_updates_countdown_and_overdue_flip(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(minutes=30))
        w = PeekPlaceholder(t, "Private", now=NOW)
        w.tick(NOW + timedelta(minutes=20))
        assert "in 10 min" in " ".join(_texts(w))
        w.tick(NOW + timedelta(minutes=42))
        assert "overdue 12 min" in " ".join(_texts(w))


class TestArmedConfirm:
    def _widget(self, qapp):
        t = Todo(title="s", context="private", due=NOW + timedelta(hours=1))
        w = PeekPlaceholder(t, "Private", now=NOW)
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
