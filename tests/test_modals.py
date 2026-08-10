"""
============================================================
Author:  Berk
Created: 2026-06-29
Purpose: Headless tests for ui.modals.QuickTodoDialog (default_due + when-only parse + save guard).
Role:    Under QT_QPA_PLATFORM=offscreen, assert the Calendar-expand slice-(b) write path:
         when default_due is set, the WHEN field alone places the todo (a date token in the
         title never hijacks placement); a typed when wins; the default_due=None path keeps
         the legacy combined title+when parse; and a save OSError leaves no phantom + keeps
         the modal open with an inline error (added not emitted).

Test classes:
- TestQuickTodoDialogDefaultDue - H4 when-only parse precedence + None regression
- TestQuickTodoDialogSaveGuard   - H2 OSError guard (phantom undo, error label, no emit)
============================================================
"""
import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.settings import Settings  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.modals import QuickTodoDialog  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class TestQuickTodoDialogDefaultDue:
    def test_blank_when_uses_slot_title_date_token_ignored(self, qapp, tmp_path):
        # H4: default_due set + blank when + a date token in the title -> slot wins, title bleed-free
        store = TodoStore(tmp_path)
        slot = datetime(2026, 7, 1, 9, 0)
        dlg = QuickTodoDialog(store, Settings(), default_due=slot)
        dlg.title.setText("Call Tom Monday")
        dlg.when.setText("")
        added: list = []
        dlg.added.connect(added.append)
        dlg._save()
        assert len(added) == 1
        assert added[0].due == slot

    def test_typed_when_wins_and_title_date_token_ignored(self, qapp, tmp_path):
        # H4: a typed when overrides the slot AND a date token in the TITLE is ignored (when-only
        # parse). Title carries its own "tomorrow" to kill a combined-parse mutant; assert the
        # CONCRETE resolved value (== parse of the when field), not a weak != slot.
        from serenity.core.parser import parse_capture
        store = TodoStore(tmp_path)
        slot = datetime(2026, 7, 1, 9, 0)
        dlg = QuickTodoDialog(store, Settings(), default_due=slot)
        dlg.title.setText("Call Tom tomorrow")     # title date token must NOT set the due
        dlg.when.setText("friday 3pm")
        added: list = []
        dlg.added.connect(added.append)
        dlg._save()
        assert len(added) == 1
        assert added[0].due == parse_capture("friday 3pm").date   # the when field alone places it
        assert added[0].due != slot

    def test_default_due_none_combined_parse_unchanged(self, qapp, tmp_path):
        # regression: default_due=None keeps the legacy combined title+when parse
        store = TodoStore(tmp_path)
        dlg = QuickTodoDialog(store, Settings())
        dlg.title.setText("Call Tom")
        dlg.when.setText("tomorrow 5pm")
        added: list = []
        dlg.added.connect(added.append)
        dlg._save()
        assert len(added) == 1
        assert added[0].due is not None


class TestQuickTodoDialogSaveGuard:
    def test_add_oserror_no_phantom_no_emit_error_shown(self, qapp, tmp_path):
        # H2: add() OSError -> phantom removed from _todos, modal stays open, added not emitted
        store = TodoStore(tmp_path)

        def boom(todo, persist=True):
            store._todos.append(todo)   # add appends before save(); mimic the in-memory append
            raise OSError("disk full")

        store.add = boom
        dlg = QuickTodoDialog(store, Settings(), default_due=datetime(2026, 7, 1, 9, 0))
        dlg.title.setText("Doomed")
        added: list = []
        dlg.added.connect(added.append)
        accepted: list = []
        dlg.accepted.connect(lambda: accepted.append(1))
        dlg._save()
        assert added == []
        assert accepted == []
        assert len(store._todos) == 0           # phantom undone
        assert dlg._error.isVisibleTo(dlg)
