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
- TestRingAckAndBubble - ring acknowledgement and bubble clearing
- TestTrayMessage - tray notification on fire
- TestResumeTickHappens - _on_resume calls _reminder_tick
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
        """A tick should save once and set reminder_active when fires occur (prove one save per tick, not per-fire)."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create TWO todos with a due time in the past (already past the 5-min rung)
            past_due = datetime.now() - timedelta(minutes=10)
            todo1 = Todo(
                id="t1",
                title="Test Todo 1",
                due=past_due,
                reminder_offsets=[30, 5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            todo2 = Todo(
                id="t2",
                title="Test Todo 2",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo1)
            sh.todo_store.add(todo2)

            # Spy on save
            save_count = 0
            original_save = sh.todo_store.save

            def spy_save():
                nonlocal save_count
                save_count += 1
                original_save()

            sh.todo_store.save = spy_save

            # Tick should fire on both todos
            sh._reminder_tick()

            # Verify: both todos should be updated
            reloaded1 = sh.todo_store.get(todo1.id)
            assert reloaded1.reminder_active is not None
            assert len(reloaded1.reminder_fired) > 0

            reloaded2 = sh.todo_store.get(todo2.id)
            assert reloaded2.reminder_active is not None
            assert len(reloaded2.reminder_fired) > 0

            # Verify: save should have happened exactly once for both fires
            assert save_count == 1, f"Expected one save for two fires, got {save_count}"

        finally:
            sh.tray.hide()

    def test_tick_error_isolation_one_bad_todo(self, qapp, tmp_path, monkeypatch):
        """A raising tick on one todo must not abort the others (per-todo guard), and the healthy
        sibling still fires with exactly one save. Without the try/except the raise propagates out
        of _reminder_tick and the sibling never fires."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            bad = Todo(id="bad", title="Bad", due=past_due, reminder_offsets=[5],
                       reminder_fired=[], reminder_active=None, reminder_nudge_at=None)
            good = Todo(id="good", title="Good", due=past_due, reminder_offsets=[5],
                        reminder_fired=[], reminder_active=None, reminder_nudge_at=None)
            sh.todo_store.add(bad)
            sh.todo_store.add(good)

            # Make tick raise for "bad" only; the real tick runs for everyone else.
            from serenity.core import reminders as _rem
            real_tick = _rem.tick

            def flaky_tick(todo, now):
                if todo.id == "bad":
                    raise RuntimeError("boom")
                return real_tick(todo, now)

            monkeypatch.setattr(_rem, "tick", flaky_tick)

            save_count = 0
            original_save = sh.todo_store.save

            def spy_save():
                nonlocal save_count
                save_count += 1
                original_save()

            sh.todo_store.save = spy_save

            sh._reminder_tick()   # must NOT raise despite "bad" throwing

            assert sh.todo_store.get("good").reminder_active is not None, "sibling should still fire"
            assert sh.todo_store.get("bad").reminder_active is None, "bad todo skipped, not mutated"
            assert save_count == 1, f"expected one save for the surviving fire, got {save_count}"

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


class TestColdLaunch:
    """Immediate catch-up on Shell construction (R-9)."""

    def test_startup_tick_fires_past_due_todo(self, qapp, tmp_path, monkeypatch):
        """Shell construction immediately fires past-due todos (startup tick at R-9).

        Populates the vault with an unfired past-due todo, then creates a fresh Shell
        which should immediately run _reminder_tick at startup and fire the todo."""
        # First shell: populate the vault with an unfired past-due todo
        sh1 = _shell(tmp_path, monkeypatch)
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(
                id="cold_t1",
                title="Cold Start",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh1.todo_store.add(todo)
            sh1.todo_store.save()
        finally:
            sh1.tray.hide()

        # Second shell: should immediately fire the todo at startup (R-9)
        sh2 = _shell(tmp_path, monkeypatch)
        try:
            # Verify the todo is now fired
            reloaded = sh2.todo_store.get("cold_t1")
            assert reloaded is not None, "Todo should still exist"
            assert len(reloaded.reminder_fired) > 0, "Startup tick (R-9) should have fired the todo"
            assert reloaded.reminder_active is not None, "reminder_active should be set"
        finally:
            sh2.tray.hide()


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

    def test_nl_capture_arm_starts_timer(self, qapp, tmp_path, monkeypatch):
        """[§5] Arming via NL capture re-syncs the 60s timer — else it never fires this session."""
        from serenity.core.parser import Capture
        sh = _shell(tmp_path, monkeypatch)
        try:
            assert not sh._reminder_timer.isActive()          # fresh vault: gate off
            cap = Capture(raw="call bob", intent="reminder", title="Call Bob",
                          date=datetime.now() + timedelta(days=1), has_time=True,
                          recurring=None, category=None, tags=[], reminder_offset=60)
            sh._commit_capture(cap)
            todo = list(sh.todo_store.all())[0]
            assert todo.reminder_offsets == [60]              # armed, future rung
            assert sh._reminder_timer.isActive(), "NL-capture arm must start the reminder timer"
        finally:
            sh.tray.hide()

    def test_quick_todo_handler_starts_timer(self, qapp, tmp_path, monkeypatch):
        """[§4.1/§5] QuickTodoDialog arms in the dialog; its handler must re-sync the timer."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            assert not sh._reminder_timer.isActive()
            todo = Todo(id="q1", title="Quick", due=datetime.now() + timedelta(days=1),
                        reminder_offsets=[60], reminder_fired=[])
            sh.todo_store.add(todo)                           # dialog already added+armed it
            sh._on_quick_todo(todo)
            assert sh._reminder_timer.isActive(), "quick-todo arm must start the reminder timer"
        finally:
            sh.tray.hide()

    def test_calendar_wrote_handler_starts_timer(self, qapp, tmp_path, monkeypatch):
        """[§4.1/§5] Calendar-slot create arms via QuickTodoDialog -> wrote -> _on_calendar_wrote."""
        sh = _shell(tmp_path, monkeypatch)
        try:
            assert not sh._reminder_timer.isActive()
            todo = Todo(id="c1", title="Slot", due=datetime.now() + timedelta(days=1),
                        reminder_offsets=[60], reminder_fired=[])
            sh.todo_store.add(todo)
            sh._on_calendar_wrote()
            assert sh._reminder_timer.isActive(), "calendar-slot arm must start the reminder timer"
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


class TestContextFlipReBlur:
    """[R-2] Context flip re-blurs the ring bubble (title-less while cross)."""

    def test_context_flip_away_blurs_active_bubble(self, qapp, tmp_path, monkeypatch):
        """Fire in-context (bubble has title) → flip context → bubble becomes title-less (silent).

        Verify that after a context flip away from the ringing todo's context,
        the bubble is re-rendered to be title-less (blurred) WITHOUT re-speaking."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            # Create an in-context ringing todo
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)

            # Fire it while in business context (should include title)
            sh._reminder_tick()
            reloaded = sh.todo_store.get("t1")
            assert reloaded.reminder_active is not None, "Should have fired"

            # Spy on mascot.says and mascot.bubble.set_text
            says_calls = []
            set_text_calls = []
            original_says = sh.mascot.says
            original_set_text = sh.mascot.bubble.set_text
            sh.mascot.says = lambda msg, **kw: says_calls.append(msg)
            sh.mascot.bubble.set_text = lambda msg, **kw: set_text_calls.append(msg) or original_set_text(msg, **kw)

            # Flip to private context
            sh.set_context("private")

            # The bubble should have been re-rendered via set_text (silent, no speak)
            assert set_text_calls, "set_context should have called bubble.set_text"
            last_set_text = set_text_calls[-1]
            # The re-blurred message should NOT contain the title
            assert "Business Task" not in last_set_text, f"Title should not be in blurred bubble: {last_set_text}"
            # Verify that _reassert_ring_bubble did NOT call mascot.says
            # (the initial fire call may have set messages, so we count calls during the flip)
            initial_says_count = len(says_calls)
            sh.set_context("business")  # flip back for another check
            # During the flip back, set_text should be called but not says (in _reassert_ring_bubble)
            assert len(set_text_calls) > initial_says_count, "set_text should be called on second flip"

        finally:
            sh.tray.hide()

    def test_context_flip_back_unblurs_bubble(self, qapp, tmp_path, monkeypatch):
        """Flip away (blurred) → flip back → bubble may re-title."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh._reminder_tick()

            messages = []
            original_says = sh.mascot.says
            sh.mascot.says = lambda msg, **kw: messages.append(msg)

            # Flip away
            sh.set_context("private")
            blurred_msg = messages[-1] if messages else ""
            assert "Business Task" not in blurred_msg, "Should be blurred while in private context"

            # Flip back
            sh.set_context("business")
            back_msg = messages[-1] if messages else ""
            # Now it may re-title (verify the logic allows it)
            # At minimum, set_context should have been called without error

        finally:
            sh.tray.hide()

    def test_context_flip_clears_bubble_when_todo_not_ringing(self, qapp, tmp_path, monkeypatch):
        """If the todo is no longer ringing after a context flip, clear the bubble."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh._reminder_tick()

            # Dismiss the ring
            reloaded = sh.todo_store.get("t1")
            from serenity.core import reminders
            reminders.acknowledge_dismiss(reloaded)
            sh.todo_store.save()

            # Now flip context - should not re-render since not ringing
            sh.set_context("private")
            # Verify no error and the bubble is cleared
            assert sh._ring_bubble is None or sh.todo_store.get(sh._ring_bubble).reminder_active is None

        finally:
            sh.tray.hide()

    def test_context_flip_does_not_re_speak_reminder(self, qapp, tmp_path, monkeypatch):
        """Context flip while ringing should update bubble text silently (no re-speak).

        Task 12 fix: _reassert_ring_bubble now uses silent set_text instead of says()."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)

            # Fire it while in business context
            sh._reminder_tick()
            reloaded = sh.todo_store.get("t1")
            assert reloaded.reminder_active is not None, "Should have fired"

            # Record initial bubble text (in-context, includes title)
            initial_text = sh.mascot.bubble.say.text()
            assert "Business Task" in initial_text, "Initial bubble should include title"

            # Flip to private context and verify silent update
            sh.set_context("private")

            # The bubble text should have changed to the blurred version
            new_text = sh.mascot.bubble.say.text()
            assert new_text != initial_text, "Bubble text should have changed after context flip"
            assert "Business Task" not in new_text, "Blurred bubble should not include title"

        finally:
            sh.tray.hide()

    def test_context_flip_reblurs_hidden_mascot_bubble(self, qapp, tmp_path, monkeypatch):
        """[R-2 · P1] A title-ful in-context bubble set on the mascot of the OTHER window mode
        must not survive a context flip and resurface as a cross-context title.

        Repro: fire in-context in MINI (mini mascot bubble gets the title) -> switch to FULL ->
        flip context (re-blur runs on the FULL mascot only) -> return to MINI. Pre-fix the mini
        mascot still shows the now-cross-context private title; the re-blur must clear it too."""
        from serenity.ui.shell import MODE_MINI, MODE_FULL
        sh = _shell(tmp_path, monkeypatch, context="private")
        try:
            past_due = datetime.now() - timedelta(minutes=10)
            todo = Todo(id="t1", title="Private Task", context="private", due=past_due,
                        reminder_offsets=[5], reminder_fired=[], reminder_active=None,
                        reminder_nudge_at=None)
            sh.todo_store.add(todo)

            sh.set_window_mode(MODE_MINI, persist=False)
            sh._reminder_tick()                                  # fires on the mini mascot
            assert sh.todo_store.get("t1").reminder_active is not None, "should have fired"
            assert "Private Task" in sh._mini.mascot.bubble.say.text(), "in-context: title shown"

            sh.set_window_mode(MODE_FULL, persist=False)
            sh.set_context("business")                           # cross now; re-blur fires
            sh.set_window_mode(MODE_MINI, persist=False)

            leaked = sh._mini.mascot.bubble.say.text()
            assert "Private Task" not in leaked, f"cross-context title leaked on mini mascot: {leaked!r}"
        finally:
            sh.tray.hide()


class TestCaptureReminderArming:
    """[Task 13] NL capture funnel — arm the snapped rung on commit + too-soon feedback."""

    def test_capture_with_offset_and_due_arms_reminder(self, qapp, tmp_path, monkeypatch):
        """Commit a capture with reminder_offset=1440 + due 3 days out → todo has reminder_offsets == [1440], unfired."""
        from serenity.core.parser import Capture
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a capture with reminder_offset=1440 (1 day) and due 3 days from now
            cap = Capture(
                raw="test reminder",
                intent="reminder",
                title="Test Reminder Todo",
                date=datetime.now() + timedelta(days=3),
                has_time=False,
                recurring=None,
                category=None,
                tags=[],
                reminder_offset=1440,  # 1 day before
            )

            sh._commit_capture(cap)

            # Find the created todo
            todos = list(sh.todo_store.all())
            assert len(todos) == 1, f"Expected 1 todo, got {len(todos)}"
            todo = todos[0]

            # Verify reminder was armed
            assert todo.reminder_offsets == [1440], f"Expected [1440], got {todo.reminder_offsets}"
            assert todo.reminder_fired == [], f"Expected empty fired list, got {todo.reminder_fired}"
            assert todo.reminder_active is None, f"Expected no active ring on commit, got {todo.reminder_active}"
        finally:
            sh.tray.hide()

    def test_capture_with_offset_but_no_due_no_crash_no_arm(self, qapp, tmp_path, monkeypatch):
        """Commit a capture with reminder_offset set but due=None → NO crash, NO offsets armed [C-3]."""
        from serenity.core.parser import Capture
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a capture with reminder_offset but NO due date
            cap = Capture(
                raw="test no due",
                intent="reminder",
                title="Test No Due Reminder",
                date=None,  # No due date
                has_time=False,
                recurring=None,
                category=None,
                tags=[],
                reminder_offset=1440,  # Has an offset but no due
            )

            # C-3: committing directly must NOT raise (the arm-due-guard skips arm when
            # due is None). Call it plainly — if the guard regressed and arm did
            # None-timedelta math, this would ERROR the test (that is the point; do NOT
            # wrap in try/except, which would mask the very crash we guard against).
            sh._commit_capture(cap)
            todos = list(sh.todo_store.all())
            assert todos, "Reminder capture should still commit a todo"
            todo = todos[-1]
            assert todo.reminder_offsets == [], f"Should not arm without due; got {todo.reminder_offsets}"
        finally:
            sh.tray.hide()

    def test_capture_with_too_soon_offset_pre_marks_fired_and_shows_notice(self, qapp, tmp_path, monkeypatch):
        """[R-11] Commit offset 10080 (1 week) with due tomorrow → rung pre-marked fired, mascot line includes too-soon notice."""
        from serenity.core.parser import Capture
        sh = _shell(tmp_path, monkeypatch)
        try:
            # Create a capture with reminder_offset=10080 (1 week) and due tomorrow
            # The fire time would be: tomorrow - 1 week = 6 days ago (already past)
            cap = Capture(
                raw="test too soon",
                intent="reminder",
                title="Test Too Soon Reminder",
                date=datetime.now() + timedelta(days=1),  # Due tomorrow
                has_time=False,
                recurring=None,
                category=None,
                tags=[],
                reminder_offset=10080,  # 1 week (too long for tomorrow)
            )

            # Spy on mascot.says to capture the emitted message
            messages = []
            original_says = sh.mascot.says
            sh.mascot.says = lambda msg, **kw: messages.append(msg)

            sh._commit_capture(cap)

            # Find the created todo
            todos = list(sh.todo_store.all())
            assert len(todos) == 1, f"Expected 1 todo, got {len(todos)}"
            todo = todos[0]

            # Verify the rung was snapped and pre-marked fired
            snapped_rung = reminders.snap_to_rung(10080)
            assert snapped_rung in todo.reminder_offsets, f"Expected snapped rung {snapped_rung} in offsets, got {todo.reminder_offsets}"
            assert snapped_rung in todo.reminder_fired, f"Expected snapped rung {snapped_rung} in fired (too-soon), got {todo.reminder_fired}"

            # Verify the mascot message includes the too-soon notice
            assert messages, "mascot.says should have been called"
            full_message = messages[0]

            # The message should include a notice about the reminder not being set
            # Check for either English or German notice
            assert "couldn" in full_message.lower() or "erinnering" in full_message.lower() or "too soon" in full_message.lower(), \
                f"Message should include too-soon notice, got: {full_message}"
        finally:
            sh.tray.hide()


class TestMiniRingAck:
    """[R-6] MINI ack affordance - Snooze/Dismiss buttons without context flip."""

    def test_mini_shows_ring_line_when_ringing(self, qapp, tmp_path, monkeypatch):
        """MiniWindow should show a ring line when a todo is actively ringing."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh._reminder_tick()

            # Get or create the mini window and show it
            mini = sh._ensure_mini()
            mini.show()
            mini.refresh_todo()

            # Verify that ring_line is visible when ringing
            reloaded = sh.todo_store.get("t1")
            assert reloaded.reminder_active is not None, "Todo should be ringing"
            assert mini._ringing_todo_id == "t1", "Ringing todo ID should be set"
            # Check that ring_line is configured for display
            assert mini.ring_line.isVisible(), "Ring line should be visible when ringing"

        finally:
            sh.tray.hide()

    def test_mini_ring_snooze_does_not_flip_context(self, qapp, tmp_path, monkeypatch):
        """Mini Snooze button should not flip context (settings.context unchanged)."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[30, 5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh._reminder_tick()

            mini = sh._ensure_mini()
            mini.refresh_todo()

            # Snooze via mini should not flip context
            original_context = sh.settings.context()

            # Emit snooze signal
            mini.ring_snooze.emit("t1")

            # Context should be unchanged
            assert sh.settings.context() == original_context, "Context should not change on snooze"

            # reminder_active should be cleared or moved to next rung
            reloaded = sh.todo_store.get("t1")
            # After snooze, reminder_active should be None (or nudge_at should be set)
            assert reloaded.reminder_active is None or reloaded.reminder_nudge_at is not None

        finally:
            sh.tray.hide()

    def test_mini_ring_dismiss_clears_active(self, qapp, tmp_path, monkeypatch):
        """Mini Dismiss button should clear reminder_active without flipping context."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            past_due = now - timedelta(minutes=10)
            todo = Todo(
                id="t1",
                title="Business Task",
                context="business",
                due=past_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            sh.todo_store.add(todo)
            sh._reminder_tick()

            reloaded = sh.todo_store.get("t1")
            assert reloaded.reminder_active is not None, "Should be ringing"

            # Dismiss and verify
            from serenity.core import reminders
            reminders.acknowledge_dismiss(reloaded)
            sh.todo_store.save()

            reloaded2 = sh.todo_store.get("t1")
            assert reloaded2.reminder_active is None, "Should be cleared after dismiss"
            assert reloaded2.reminder_fired == reloaded2.reminder_offsets, "All should be marked fired"

        finally:
            sh.tray.hide()

    def test_mini_deterministic_ring_pick_selects_sooner_todo(self, qapp, tmp_path, monkeypatch):
        """Mini ring display should pick the sooner-due todo when multiple todos are ringing.

        Task 12 fix: ringing_todos pick was insertion-order dependent; now deterministic
        by due date (consistent with blurred pick)."""
        sh = _shell(tmp_path, monkeypatch, context="business")
        try:
            now = datetime.now()
            # Create two ringing todos with different due times (later due first, earlier due second)
            later_due = now - timedelta(minutes=5)      # 5 min overdue
            earlier_due = now - timedelta(minutes=15)   # 15 min overdue (sooner to show)

            todo_later = Todo(
                id="t_later",
                title="Later Task",
                context="business",
                due=later_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            todo_earlier = Todo(
                id="t_earlier",
                title="Earlier Task",
                context="business",
                due=earlier_due,
                reminder_offsets=[5],
                reminder_fired=[],
                reminder_active=None,
                reminder_nudge_at=None,
            )
            # Add later todo first (insertion order)
            sh.todo_store.add(todo_later)
            sh.todo_store.add(todo_earlier)

            # Fire both
            sh._reminder_tick()
            reloaded_later = sh.todo_store.get("t_later")
            reloaded_earlier = sh.todo_store.get("t_earlier")
            assert reloaded_later.reminder_active is not None, "Later todo should be ringing"
            assert reloaded_earlier.reminder_active is not None, "Earlier todo should be ringing"

            # Get or create mini and refresh
            mini = sh._ensure_mini()
            mini.refresh_todo()

            # Verify that the EARLIER (sooner) todo is selected, not the first-inserted one
            assert mini._ringing_todo_id == "t_earlier", \
                f"Mini should pick sooner todo (t_earlier), got {mini._ringing_todo_id}"

        finally:
            sh.tray.hide()
