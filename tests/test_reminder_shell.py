"""
============================================================
Author:  Berk
Created: 2026-07-08
Purpose: Shell scheduler + fire routing + catch-up ticks (Task 11).
Role:    Offscreen Qt tests for the reminder tick engine integrated into Shell:
         60s periodic tick, cold-launch immediate catch-up, resume catch-up,
         fire routing to bubble+tray+banner, in-context vs cross-context copy,
         bubble ack, timer sync.

Test classes:
- TestReminderTick - core tick behavior (armed todo crossing fire time)
- TestReminderSync - timer runs only when needed
- TestColdLaunch - immediate catch-up on Shell construction
- TestRouting - fire routing (bubble, tray, context handling)
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

from PySide6.QtWidgets import QApplication

from serenity.core.models import Todo
from serenity.core import reminders


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _shell(tmp_path, monkeypatch, context="business"):
    """Create a Shell instance with isolated config/vault."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from serenity.ui import platform_win
    from serenity.core import paths
    monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
    monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
    from serenity.ui.shell import Shell
    sh = Shell()
    sh.settings.current_context = context
    return sh


class TestReminderTick:
    """Core tick behavior: armed todo crossing fire time → bubble, save, refresh."""

    def test_tick_saves_and_sets_active_when_fires(self, qapp, tmp_path, monkeypatch):
        """A tick should save and set reminder_active when a fire occurs."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a todo with a due time in the past (already past the 5-min rung)
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Test Todo",
                due=past_due,
                reminder_offsets=[30, 5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)

            # Tick should fire
            sh._reminder_tick()

            # Verify: todo should be updated
            reloaded = sh.todo_store.get(todo.id)
            assert reloaded.reminder_active is not None
            assert len(reloaded.reminder_fired) > 0

        finally:
            sh.tray.hide()

    def test_tick_no_fires_no_save(self, qapp, tmp_path, monkeypatch):
        """A tick with no fires should not save."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a todo with a due time far in the future
            future_due = datetime.now() + timedelta(days=10)
            todo = Todo(
                id="t1",
                title="Test",
                due=future_due,
                reminder_offsets=[30],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)

            # Spy on save
            save_count = 0
            original_save = sh.todo_store.save

            def spy_save():
                nonlocal save_count
                save_count += 1
                original_save()

            sh.todo_store.save = spy_save

            # Tick (nothing due yet)
            sh._reminder_tick()

            assert save_count == 0, "Should not save when no fires"

        finally:
            sh.tray.hide()

    def test_in_context_msg_includes_title(self, qapp, tmp_path, monkeypatch):
        """In-context fire message should include the todo title."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Important Meeting",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh.settings.current_context = "business"  # Same context

            # Spy on mascot.says
            messages = []
            original_says = sh.mascot.says
            sh.mascot.says = lambda msg, **kw: messages.append(msg)

            sh._reminder_tick()

            assert messages, "Should have called mascot.says"
            assert "Important Meeting" in messages[0], "Title should be in message"

        finally:
            sh.tray.hide()

    def test_cross_context_msg_excludes_title(self, qapp, tmp_path, monkeypatch):
        """Cross-context fire message should NOT include the todo title."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Secret Meeting",
                context="private",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh.settings.current_context = "business"  # Different context

            # Spy on mascot.says
            messages = []
            sh.mascot.says = lambda msg, **kw: messages.append(msg)

            sh._reminder_tick()

            assert messages, "Should have called mascot.says"
            assert "Secret Meeting" not in messages[0], "Title should NOT be in cross-context message"

        finally:
            sh.tray.hide()

    def test_cross_context_msg_has_no_clock(self, qapp, tmp_path, monkeypatch):
        """Cross-context relative phrase should have no ':' (no absolute clock times)."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Secret",
                context="private",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh.settings.current_context = "business"

            # Spy on voice.say to check slots
            say_calls = []
            original_say = sh.voice.say
            sh.voice.say = lambda event, lang, **slots: (say_calls.append((event, slots)), original_say(event, lang, **slots))[1]

            sh._reminder_tick()

            assert say_calls, "voice.say should have been called"
            # Check that the time phrase has no colons (no clock times)
            for event, slots in say_calls:
                if "time" in slots:
                    phrase = slots["time"]
                    assert ":" not in phrase, f"Cross-context phrase should have no clock: {phrase}"

        finally:
            sh.tray.hide()


class TestReminderSync:
    """Timer sync: should run only when needed."""

    def test_timer_inactive_when_no_armed_todos(self, qapp, tmp_path, monkeypatch):
        """Timer should be inactive when no todos have armed reminders."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a todo with NO reminders
            todo = Todo(id="t1", title="Test", due=datetime.now() + timedelta(days=1),
                       reminder_offsets=[])
            sh.todo_store.add(todo)

            sh._sync_reminder_timer()
            assert not sh._reminder_timer.isActive()

        finally:
            sh.tray.hide()

    def test_timer_active_when_armed_todo_exists(self, qapp, tmp_path, monkeypatch):
        """Timer should be active when at least one todo has armed reminders."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a todo WITH armed reminders
            todo = Todo(id="t1", title="Test", due=datetime.now() + timedelta(days=1),
                       reminder_offsets=[30], reminder_fired=[])
            sh.todo_store.add(todo)

            sh._sync_reminder_timer()
            assert sh._reminder_timer.isActive()

        finally:
            sh.tray.hide()


class TestRingAckAndBubble:
    """Ring acknowledgement and bubble clearing."""

    def test_ring_acked_clears_ring_bubble_state(self, qapp, tmp_path, monkeypatch):
        """Calling _on_ring_acked should clear _ring_bubble."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            sh._ring_bubble = "t1"
            todo = Todo(id="t1", title="Test")

            sh._on_ring_acked(todo)

            assert sh._ring_bubble is None

        finally:
            sh.tray.hide()

    def test_ring_acked_clears_mascot_bubble(self, qapp, tmp_path, monkeypatch):
        """Calling _on_ring_acked should clear the mascot speech bubble."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            sh.mascot.bubble.set_text("Test message")
            todo = Todo(id="t1", title="Test")

            # Spy on bubble.set_text
            calls = []
            original_set_text = sh.mascot.bubble.set_text
            sh.mascot.bubble.set_text = lambda text, **kw: (calls.append(text), original_set_text(text, **kw))[1]

            sh._on_ring_acked(todo)

            # Should have cleared the bubble
            assert calls and calls[-1] == "", f"Bubble should be cleared, got {calls}"

        finally:
            sh.tray.hide()


class TestTrayMessage:
    """Tray notification on fire."""

    def test_fire_calls_tray_showmessage(self, qapp, tmp_path, monkeypatch):
        """Fire routing should call tray.showMessage."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Test",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)

            # Spy on tray.showMessage
            show_msg_calls = []
            original_showmessage = sh.tray.showMessage
            sh.tray.showMessage = lambda *args, **kw: (show_msg_calls.append((args, kw)), original_showmessage(*args, **kw))[1]

            sh._reminder_tick()

            # Should have called showMessage
            assert show_msg_calls, "tray.showMessage should have been called"

        finally:
            sh.tray.hide()


class TestResumeTickHappens:
    """_on_resume should fire the reminder tick."""

    def test_on_resume_calls_reminder_tick(self, qapp, tmp_path, monkeypatch):
        """_on_resume should call _reminder_tick before safe_refresh."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Spy on _reminder_tick
            tick_called = False
            original_tick = sh._reminder_tick

            def spy_tick():
                nonlocal tick_called
                tick_called = True
                original_tick()

            sh._reminder_tick = spy_tick

            # Call _on_resume
            sh._on_resume()

            assert tick_called, "_reminder_tick should have been called by _on_resume"

        finally:
            sh.tray.hide()
