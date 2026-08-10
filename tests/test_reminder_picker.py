"""
============================================================
Author:  Berk
Created: 2026-07-08
Purpose: Headless tests for ui.reminder_picker.ReminderPicker (due binding, armable, fired dimming).
Role:    Under QT_QPA_PLATFORM=offscreen, assert the picker shows/hides/dims rungs based on
         due date and armed/fired state. Tests cover: no due (all disabled + hint), due too
         soon (all disabled + hint), due 2h out (exactly [60,30,5] enabled), toggling emits
         changed, fired rungs carry dimmed style/property.

Test classes:
- TestReminderPickerBasic  - no due, due too soon, due with armable rungs
- TestReminderPickerSignal - changed signal on toggle
- TestReminderPickerFired  - dimmed style on fired rungs
============================================================
"""

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.ui.reminder_picker import ReminderPicker  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class TestReminderPickerBasic:
    def test_no_due_all_disabled_hint(self, qapp):
        """No due date -> all 5 checkboxes disabled, hint shown."""
        picker = ReminderPicker(due_provider=lambda: None)
        picker.refresh()

        for cb in picker.checkboxes.values():
            assert not cb.isEnabled()
        assert "Set a due date" in picker.hint.text()

    def test_due_too_soon_all_disabled_hint(self, qapp):
        """Due < 5 min out -> all disabled, 'too soon' hint."""
        now = datetime.now()
        due_in_2min = now + timedelta(minutes=2)
        picker = ReminderPicker(due_provider=lambda: due_in_2min)
        picker.refresh()

        for cb in picker.checkboxes.values():
            assert not cb.isEnabled()
        assert "too soon" in picker.hint.text()

    def test_due_2h_out_enables_60_30_5(self, qapp):
        """Due 2h out -> [60, 30, 5] enabled, [10080, 1440] disabled."""
        now = datetime.now()
        due_in_2h = now + timedelta(hours=2)
        picker = ReminderPicker(due_provider=lambda: due_in_2h)
        picker.refresh()

        # 60, 30, 5 min rungs are in the future; 10080 (week) and 1440 (day) are past
        assert picker.checkboxes[60].isEnabled()
        assert picker.checkboxes[30].isEnabled()
        assert picker.checkboxes[5].isEnabled()
        assert not picker.checkboxes[10080].isEnabled()
        assert not picker.checkboxes[1440].isEnabled()


class TestReminderPickerSignal:
    def test_toggle_emits_changed_with_selection(self, qapp):
        """Toggling a checkbox emits changed with selected() offsets."""
        now = datetime.now()
        due_in_2h = now + timedelta(hours=2)
        picker = ReminderPicker(due_provider=lambda: due_in_2h)
        picker.refresh()

        emissions = []
        picker.changed.connect(emissions.append)

        # Toggle the 1-hour rung on
        picker.checkboxes[60].setChecked(True)
        assert len(emissions) == 1
        assert emissions[-1] == [60]

        # Toggle the 30-min rung on
        picker.checkboxes[30].setChecked(True)
        assert len(emissions) == 2
        assert emissions[-1] == [60, 30]

        # Toggle the 1-hour rung off
        picker.checkboxes[60].setChecked(False)
        assert len(emissions) == 3
        assert emissions[-1] == [30]


class TestReminderPickerFired:
    def test_fired_rung_dimmed_but_toggleable(self, qapp):
        """Fired rungs get dimmed style but stay enabled and toggleable."""
        now = datetime.now()
        due_in_2h = now + timedelta(hours=2)
        picker = ReminderPicker(
            due_provider=lambda: due_in_2h,
            initial=[60],
            fired=[60],  # 60-min rung already fired
        )
        picker.refresh()

        # The 60-min checkbox should be:
        # - enabled (it's armable)
        # - dimmed (it's in fired)
        # - checked (it's in initial)
        assert picker.checkboxes[60].isEnabled()
        assert picker.checkboxes[60].property("dimmed") is True
        assert picker.checkboxes[60].isChecked()

        # Toggling it off and on again should work
        emissions = []
        picker.changed.connect(emissions.append)
        picker.checkboxes[60].setChecked(False)
        assert emissions[-1] == []
        picker.checkboxes[60].setChecked(True)
        assert emissions[-1] == [60]

    def test_fired_rung_dimmed_property_visible_in_stylesheet(self, qapp):
        """Dimmed property is actually set and a stylesheet rule exists to consume it."""
        now = datetime.now()
        due_in_2h = now + timedelta(hours=2)
        picker = ReminderPicker(
            due_provider=lambda: due_in_2h,
            initial=[60],
            fired=[60],
        )
        picker.refresh()

        # Verify the dimmed property is set
        assert picker.checkboxes[60].property("dimmed") is True
        # Verify the widget has a stylesheet that includes the dimmed rule
        ss = picker.styleSheet()
        assert 'dimmed="true"' in ss


class TestCardReminderPath:
    def test_card_reminder_btn_only_for_due_dated_todos(self, qapp, tmp_path):
        """TodoCard has reminder_btn only when todo.due is set."""
        from serenity.core.models import Todo
        from serenity.core.settings import Settings
        from serenity.core.todo_store import TodoStore
        from serenity.ui.todos_view import TodosView

        store = TodoStore(tmp_path)
        now = datetime.now()

        # Due-dated todo: reminder_btn should exist
        due_todo = Todo(title="Do this", due=now + timedelta(days=1))
        store.add(due_todo)
        view = TodosView(store, Settings())
        card = next((c for c in view._cards if c.todo.id == due_todo.id), None)
        assert card is not None
        assert card.reminder_btn is not None

        # Due-less todo: reminder_btn should be None
        no_due_todo = Todo(title="Do that")
        store.add(no_due_todo)
        view.refresh()
        no_due_card = next((c for c in view._cards if c.todo.id == no_due_todo.id), None)
        assert no_due_card is not None
        assert no_due_card.reminder_btn is None

    def test_card_reminder_commit_end_to_end(self, qapp, tmp_path, monkeypatch):
        """E2E via the REAL popover commit path: _on_reminder_btn -> menu.aboutToHide ->
        _commit_on_close -> view._on_reminders_changed (store.save). Not a hand-rolled arm+emit."""
        from PySide6.QtWidgets import QMenu
        from serenity.core.models import Todo
        from serenity.core.settings import Settings
        from serenity.core.todo_store import TodoStore
        from serenity.ui.todos_view import TodosView

        store = TodoStore(tmp_path)
        now = datetime.now()
        due_todo = Todo(title="With reminder", due=now + timedelta(days=2))
        store.add(due_todo)

        view = TodosView(store, Settings())
        card = next((c for c in view._cards if c.todo.id == due_todo.id), None)
        assert card is not None
        assert card.reminder_btn is not None

        # Drive the real popover without a blocking modal exec. PySide ignores a monkeypatch of
        # the C++ QMenu.exec, so swap the QMenu NAME in todos_view for a subclass whose overridden
        # exec PySide honors: it reaches the picker _on_reminder_btn built, checks the 1-day rung,
        # and fires aboutToHide (the signal the card wires its commit to).
        from serenity.ui import todos_view as tv_mod

        class _NoBlockMenu(QMenu):
            def exec(self, *a, **k):
                picker = self.actions()[0].defaultWidget()
                picker.checkboxes[1440].setChecked(True)
                self.aboutToHide.emit()
                return None

        monkeypatch.setattr(tv_mod, "QMenu", _NoBlockMenu)

        card._on_reminder_btn()

        # Fresh store -> proves the commit actually reached disk via the real wiring.
        reloaded = TodoStore(tmp_path).get(due_todo.id)
        assert reloaded is not None
        assert reloaded.reminder_offsets == [1440]
