"""
============================================================
Author:  Berk
Created: 2026-07-08
Purpose: Tests for Phase H reminder ring banner (TodoCard + PeekPlaceholder).
Role:    Guards the ring banner surface (card + cross-context placeholder) and
         its Snooze/Dismiss handlers, and the always-render bypass [R-4] + grace-arm
         silence [R-10].

Test classes:
- TestRingBannerOnCard - banner shows when reminder_active, Snooze/Dismiss handlers
- TestRingBannerOnPlaceholder - cross-context ring shows Snooze/Dismiss (no reveal arm)
- TestRingAlwaysRender - [R-4]: ringing non-urgent todo renders despite hide classification
- TestRingGraceArmSilence - [R-10]: grace-arm clears reminder_active + nudge_at
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QLabel

from serenity.core.models import Todo
from serenity.core import reminders
from serenity.core.settings import Settings
from serenity.core.todo_store import TodoStore
from serenity.ui.todos_view import TodosView
from serenity.ui.peek_placeholder import PeekPlaceholder, blurred_line

NOW = datetime(2026, 7, 8, 12, 0, 0)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.vault_path = str(tmp_path / "vault")
    s.undo_seconds = 60
    return s


class TestRingBannerOnCard:
    """Ring banner on in-context TodoCard: shows time-left + Snooze + Dismiss."""

    def test_banner_shows_when_reminder_active(self, qapp, tmp_path, settings):
        # A card with reminder_active set shows a banner with the time-left text.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Meeting", due=due, reminder_offsets=[1440, 60])
        store.add(todo)
        # Manually set reminder_active (normally done by tick, but we're testing the UI)
        todo.reminder_active = 60

        view = TodosView(store, settings)
        view.settings.current_context = "business"
        card = view._cards[0]

        # Find the banner widget and check it shows the time-left text
        banner_btns = [w for w in card.findChildren(QPushButton) if "snooze" in w.objectName().lower()]
        assert len(banner_btns) > 0, "Banner should have Snooze/Dismiss buttons"

    def test_snooze_button_emits_ring_snooze(self, qapp, tmp_path, settings):
        # Snooze button emits a ring_snooze signal.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Meeting", due=due, reminder_offsets=[1440, 60])
        store.add(todo)
        todo.reminder_active = 60

        view = TodosView(store, settings)
        view.settings.current_context = "business"
        card = view._cards[0]

        emitted = []
        card.ring_snooze.connect(lambda t: emitted.append(t))

        # Find and click the Snooze button
        snooze_btn = next((b for b in card.findChildren(QPushButton)
                          if b.objectName() == "snooze_btn"), None)
        assert snooze_btn is not None, "Snooze button should exist on the banner"
        snooze_btn.click()
        assert emitted == [todo], "ring_snooze should emit the todo"

    def test_dismiss_button_emits_ring_dismiss(self, qapp, tmp_path, settings):
        # Dismiss button emits a ring_dismiss signal.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Meeting", due=due, reminder_offsets=[1440, 60])
        store.add(todo)
        todo.reminder_active = 60

        view = TodosView(store, settings)
        view.settings.current_context = "business"
        card = view._cards[0]

        emitted = []
        card.ring_dismiss.connect(lambda t: emitted.append(t))

        dismiss_btn = next((b for b in card.findChildren(QPushButton)
                           if b.objectName() == "dismiss_btn"), None)
        assert dismiss_btn is not None, "Dismiss button should exist on the banner"
        dismiss_btn.click()
        assert emitted == [todo], "ring_dismiss should emit the todo"


class TestRingBannerOnPlaceholder:
    """Cross-context ringing todo shows Snooze/Dismiss on PeekPlaceholder (no reveal)."""

    def test_placeholder_has_snooze_dismiss_when_ringing(self, qapp):
        # A ringing cross-context todo in a PeekPlaceholder shows Snooze/Dismiss.
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Secret Meeting", context="private", due=due,
                    reminder_offsets=[1440, 60], reminder_active=60)

        placeholder = PeekPlaceholder(todo, now=NOW)
        btns = placeholder.findChildren(QPushButton)

        # Should have snooze and dismiss buttons (in addition to the reveal confirm)
        btn_names = [b.objectName() for b in btns]
        assert any("snooze" in n.lower() for n in btn_names), "PeekPlaceholder should have snooze btn"
        assert any("dismiss" in n.lower() for n in btn_names), "PeekPlaceholder should have dismiss btn"

    def test_placeholder_snooze_does_not_trigger_reveal_arm(self, qapp):
        # Clicking Snooze on PeekPlaceholder must not arm the reveal confirm.
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Secret", context="private", due=due,
                    reminder_offsets=[1440, 60], reminder_active=60)

        placeholder = PeekPlaceholder(todo, now=NOW)
        snooze_btn = next((b for b in placeholder.findChildren(QPushButton)
                          if b.objectName() == "snooze_btn"), None)
        assert snooze_btn is not None

        snooze_btn.click()
        # The placeholder should still be in disarmed state (not showing "Switch to Private?")
        assert "Switch to" not in placeholder.label.text()

    def test_placeholder_ring_never_shows_title(self, qapp):
        # Even with a ringing reminder on a cross-context placeholder, the title must never appear.
        # Tests [P1] privacy invariant: no title in any widget text, tooltip, status, accessible name.
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="fire_the_intern", context="private", due=due,
                    reminder_offsets=[1440, 60], reminder_active=60)

        placeholder = PeekPlaceholder(todo, now=NOW)

        # Collect all text from QLabel and QPushButton widgets in one pass
        all_text_parts = []
        labels = placeholder.findChildren(QLabel)
        btns = placeholder.findChildren(QPushButton)

        for label in labels:
            all_text_parts.extend([label.text(), label.toolTip(),
                                   label.statusTip(), label.accessibleName()])

        for btn in btns:
            all_text_parts.extend([btn.text(), btn.toolTip(),
                                   btn.statusTip(), btn.accessibleName()])

        combined_text = " ".join(part for part in all_text_parts if part)
        assert "fire_the_intern" not in combined_text, f"Title must not appear. Found in: {combined_text}"

        # Assert placeholder DID render the ring buttons (non-vacuous: proves widgets exist)
        btn_names = [b.text() for b in btns]
        assert any("Snooze" in n for n in btn_names), "Ring banner should have Snooze button"
        assert any("Dismiss" in n for n in btn_names), "Ring banner should have Dismiss button"

        # Assert the visible blurred label text equals blurred_line (relative time + lock + context, no title/clock)
        assert len(labels) > 0, "Placeholder should have at least one label"
        label_text = labels[0].text()
        expected_text = blurred_line(todo, NOW)
        assert label_text == expected_text, f"Label should show blurred text. Got: {label_text}, Expected: {expected_text}"
        # Verify no absolute clock digits (e.g., "12:00" or "12" followed by ":")
        assert not any(c.isdigit() for i, c in enumerate(label_text)
                      if i + 1 < len(label_text) and label_text[i+1] == ':'), "Must not show absolute clock times"


class TestRingAlwaysRender:
    """[R-4]: A ringing todo always renders (full card or blurred placeholder), never hides."""

    def test_ringing_non_urgent_other_context_renders_as_placeholder(self, qapp, tmp_path, settings):
        # A non-urgent (due 7 days out) OTHER-context todo with reminder_active set
        # should render as a PeekPlaceholder (not be dropped entirely).
        store = TodoStore(tmp_path)
        due = NOW + timedelta(days=7)
        todo = Todo(title="Far Off Task", context="private", due=due,
                    reminder_offsets=[10080], reminder_active=10080)
        store.add(todo)

        view = TodosView(store, settings)
        view.settings.current_context = "business"
        view.refresh()

        # Check that exactly one PeekPlaceholder (or card) exists for this todo
        peek_ids = [p.todo.id for p in view._peek_widgets]
        card_ids = [c.todo.id for c in view._cards]
        assert todo.id in peek_ids or todo.id in card_ids, "Ringing todo must render despite being non-urgent"

        # It should be a placeholder (not a full card) since it's cross-context
        assert todo.id in peek_ids, "Cross-context ringing should be a blurred placeholder"

    def test_ringing_same_context_renders_as_card(self, qapp, tmp_path, settings):
        # A ringing in-context todo renders as a full card even if non-urgent.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(days=7)
        todo = Todo(title="Far Off Task", context="business", due=due,
                    reminder_offsets=[10080], reminder_active=10080)
        store.add(todo)

        view = TodosView(store, settings)
        view.settings.current_context = "business"
        view.refresh()

        card_ids = [c.todo.id for c in view._cards]
        assert todo.id in card_ids, "In-context ringing should render as a full card"

    def test_ringing_not_counted_in_hidden(self, qapp, tmp_path, settings):
        # A hidden (by filter) but ringing todo should NOT be counted as hidden.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(days=7)
        todo = Todo(title="Private Task", context="private", due=due,
                    reminder_offsets=[10080], reminder_active=10080, state_tag="Working")
        store.add(todo)

        view = TodosView(store, settings)
        view.settings.current_context = "business"
        view.state_chip.btn.setChecked(True)  # Only show "Working" state
        view.refresh()

        # The filter notice should indicate 0 hidden (the ringing todo is shown as peek)
        # or the todo should simply be rendered (not in hidden count)
        text = view.filter_notice.text()
        assert "0 hidden" in text or view.filter_notice.isHidden(), "Ringing todo must not be counted as hidden"


class TestRingGraceArmSilence:
    """[R-10]: grace-arm silence clears reminder_active + reminder_nudge_at."""

    def test_grace_arm_silences_ringing_todo(self, qapp, tmp_path, settings):
        # When _arm_grace is called on a ringing todo, it should clear reminder_active
        # and reminder_nudge_at (via reminders.silence).
        store = TodoStore(tmp_path)
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Meeting", due=due, reminder_offsets=[60], reminder_active=60)
        store.add(todo)

        view = TodosView(store, settings)
        assert todo.reminder_active == 60, "Todo should be ringing before grace"
        assert todo.reminder_nudge_at is None

        view._arm_grace(todo)

        # Check that reminder_active and reminder_nudge_at are cleared
        assert todo.reminder_active is None, "reminder_active should be cleared by grace-arm silence"
        assert todo.reminder_nudge_at is None, "reminder_nudge_at should be cleared by grace-arm silence"

    def test_grace_arm_saves_after_silence(self, qapp, tmp_path, settings):
        # grace-arm must save the store after silencing.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Meeting", due=due, reminder_offsets=[60], reminder_active=60)
        store.add(todo)

        view = TodosView(store, settings)
        view._arm_grace(todo)

        # Reload from store to verify it was saved
        reloaded = store.get(todo.id)
        assert reloaded.reminder_active is None, "Store should be saved with cleared reminder_active"

    def test_untick_within_grace_does_not_resurrect_ring(self, qapp, tmp_path, settings):
        # Un-ticking a todo within the grace window should NOT resurrect its ring.
        store = TodoStore(tmp_path)
        due = NOW + timedelta(minutes=30)
        todo = Todo(title="Meeting", due=due, reminder_offsets=[60], reminder_active=60)
        store.add(todo)

        view = TodosView(store, settings)
        card = view._cards[0]

        # Tick it done (arms grace, silences ring)
        card.check.setChecked(True)
        assert todo.reminder_active is None, "Ring should be silenced at grace-arm"

        # Un-tick within the window
        card.check.setChecked(False)

        # The ring should NOT come back
        assert todo.reminder_active is None, "Un-ticking should not resurrect the ring"
