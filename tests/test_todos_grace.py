"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: Regression tests for the done-grace (FEATURE 5) + linked-note (FEATURE 4) bugs found
         by the session bug-sweep: the grace timer must survive a list rebuild, fire to complete,
         cancel on un-tick; a trashed linked note must not resolve; the subtask path must sync
         the main checkbox.
Role:    Headless (QT_QPA_PLATFORM=offscreen) UI tests over serenity.ui.todos_view, guarding that
         the grace timer lives on TodosView (not the ephemeral TodoCard) so refresh() can't drop a
         pending completion.

Test classes:
- TestDoneGrace - grace survives refresh / fires / cancels on un-tick / subtask path arms+syncs
- TestLinkedNoteTrashed - _linked_note skips a soft-deleted (trashed) note
============================================================
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from serenity.core.models import SubTask, Todo  # noqa: E402
from serenity.core.note_store import NoteStore  # noqa: E402
from serenity.core.settings import Settings  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.todos_view import TodosView  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.vault_path = str(tmp_path / "vault")
    s.undo_seconds = 60  # long window so the timer never fires mid-test; we fire it explicitly
    return s


class TestDoneGrace:
    def test_grace_survives_refresh(self, qapp, tmp_path, settings):
        # The HIGH bug: arming grace then rebuilding the list (add/edit/voice-capture) must NOT
        # drop the pending completion. The timer lives on the view, keyed by id.
        store = TodoStore(tmp_path)
        store.add(Todo(title="Alpha"))
        view = TodosView(store, settings)
        card = view._cards[0]
        tid = card.todo.id

        card.check.setChecked(True)                 # arm grace
        assert tid in view._grace_timers

        view.refresh()                              # simulate adding a todo / editing a card
        assert tid in view._grace_timers            # SURVIVED the rebuild (was lost before)
        assert view._cards[0].check.isChecked()     # pending state re-shown on the fresh card

    def test_grace_fire_completes(self, qapp, tmp_path, settings):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Alpha"))
        view = TodosView(store, settings)
        tid = view._cards[0].todo.id

        view._cards[0].check.setChecked(True)
        view._grace_fire(tid)                       # window elapsed
        assert store.get(tid).done is True
        assert all(t.id != tid for t in store.active())
        assert tid not in view._grace_timers

    def test_uncheck_cancels_grace(self, qapp, tmp_path, settings):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Alpha"))
        view = TodosView(store, settings)
        card = view._cards[0]
        tid = card.todo.id

        card.check.setChecked(True)
        assert tid in view._grace_timers
        card.check.setChecked(False)                # un-tick within the window
        assert tid not in view._grace_timers
        assert store.get(tid).done is False

    def test_all_subtasks_done_syncs_checkbox_and_arms(self, qapp, tmp_path, settings):
        # The subtask path must check the main box (the undo handle) and arm grace.
        store = TodoStore(tmp_path)
        store.add(Todo(title="T", subtasks=[SubTask(text="a"), SubTask(text="b")]))
        view = TodosView(store, settings)
        card = view._cards[0]
        card.todo.subtasks[0].done = True           # only the last tick is the all-done event
        card._on_subtask(card.todo.subtasks[1], True, QLabel())
        assert card.check.isChecked()               # box synced (so un-ticking it cancels)
        assert card.todo.id in view._grace_timers    # grace armed


class TestLinkedNoteTrashed:
    def test_linked_note_skips_trashed(self, qapp, tmp_path, settings):
        store = TodoStore(tmp_path)
        note_store = NoteStore(tmp_path)
        todo = Todo(title="Meet")
        store.add(todo)
        view = TodosView(store, settings, note_store=note_store)
        card = view._cards[0]

        note = note_store.create("Prep", body="x")
        card.todo.linked_note_ids.append(note.id)
        store.update(card.todo)
        assert card._linked_note() is not None        # resolves while live

        note_store.soft_delete(note.id)
        assert card._linked_note() is None            # trashed -> skipped (was resolved before)
