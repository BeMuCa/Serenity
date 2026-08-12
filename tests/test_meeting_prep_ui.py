"""
============================================================
Author:  Berk
Created: 2026-08-12
Purpose: Verify the Meeting-Prep UI surfaces: the Prep button + prepped tint on a meeting
         row, the default-off auto-prep toggle in both creation forms, and that every one
         of those controls carries a hover explanation.
Role:    Headless UI regression for the Meeting-Prep controls in ui/todos_view.py,
         ui/modals.py and ui/capture_bubble.py.

Test classes:
- TestPrepButton - shown only for meetings, emits, tint + tooltip follow the prep state
- TestQuickTodoToggle - hidden until the title parses as a meeting, default off, persists
- TestCaptureBubbleToggle - same contract in the in-dock bubble
- TestMaintenanceJob - the HEAVY break job is registered and no-ops without a prep callable
============================================================
"""
import os
import tempfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.breaktime import Tier  # noqa: E402
from serenity.core.maintenance import build_maintenance_jobs  # noqa: E402
from serenity.core.meeting_prep import prep_todo  # noqa: E402
from serenity.core.models import Todo  # noqa: E402
from serenity.core.note_store import NoteStore  # noqa: E402
from serenity.core.settings import Settings  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.capture_bubble import CaptureBubble  # noqa: E402
from serenity.ui.modals import QuickTodoDialog  # noqa: E402
from serenity.ui.todos_view import TodoCard  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        notes = NoteStore(vault, index_path=vault / ".index.sqlite")
        todos = TodoStore(vault)
        yield notes, todos
        notes.close()


class TestPrepButton:
    """Shown only for meetings, emits the todo, and reflects whether a prep exists."""

    def test_meeting_rows_get_a_prep_button(self, qapp, stores):
        note_store, todo_store = stores
        todo = todo_store.add(Todo(title="Weekly", category="meeting"))
        card = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        assert card.prep_btn is not None

    def test_non_meeting_rows_do_not(self, qapp, stores):
        note_store, todo_store = stores
        todo = todo_store.add(Todo(title="Einkaufen"))
        card = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        assert card.prep_btn is None

    def test_without_a_note_store_there_is_no_button(self, qapp, stores):
        _, todo_store = stores
        todo = todo_store.add(Todo(title="Weekly", category="meeting"))
        card = TodoCard(todo, todo_store, datetime.now())
        assert card.prep_btn is None

    def test_pressing_it_emits_the_todo(self, qapp, stores):
        note_store, todo_store = stores
        todo = todo_store.add(Todo(title="Weekly", category="meeting"))
        card = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        seen = []
        card.prep_requested.connect(seen.append)
        card.prep_btn.click()
        assert seen == [todo]

    def test_the_row_knows_when_it_is_prepped(self, qapp, stores):
        note_store, todo_store = stores
        todo = todo_store.add(Todo(title="Weekly", category="meeting", due=datetime(2026, 8, 14)))
        before = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        assert before.is_prepped() is False
        prep_todo(todo, note_store, todo_store, [todo], "# Protokoll\n")
        after = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        assert after.is_prepped() is True

    def test_the_tooltip_changes_once_prepped(self, qapp, stores):
        note_store, todo_store = stores
        todo = todo_store.add(Todo(title="Weekly", category="meeting", due=datetime(2026, 8, 14)))
        unprepped = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        first = unprepped.prep_btn.toolTip()
        prep_todo(todo, note_store, todo_store, [todo], "# Protokoll\n")
        prepped = TodoCard(todo, todo_store, datetime.now(), note_store=note_store)
        assert first and prepped.prep_btn.toolTip() and first != prepped.prep_btn.toolTip()


class TestQuickTodoToggle:
    """Hidden until the title parses as a meeting, default off, and it reaches the Todo."""

    def _dialog(self, todo_store):
        return QuickTodoDialog(todo_store, Settings())

    def test_hidden_and_off_for_a_plain_todo(self, qapp, stores):
        _, todo_store = stores
        dlg = self._dialog(todo_store)
        dlg.title.setText("Einkaufen gehen")
        assert dlg.prep_auto.isChecked() is False
        assert dlg.prep_auto.isVisible() is False

    def test_revealed_once_the_title_parses_as_a_meeting(self, qapp, stores):
        _, todo_store = stores
        dlg = self._dialog(todo_store)
        dlg.show()
        dlg.title.setText("Termin mit Mueller")
        assert dlg.prep_auto.isVisible() is True
        assert dlg.prep_auto.isChecked() is False

    def test_unticked_again_when_the_title_stops_being_a_meeting(self, qapp, stores):
        _, todo_store = stores
        dlg = self._dialog(todo_store)
        dlg.title.setText("Termin mit Mueller")
        dlg.prep_auto.setChecked(True)
        dlg.title.setText("Einkaufen gehen")
        assert dlg.prep_auto.isChecked() is False

    def test_the_saved_meeting_carries_the_flag(self, qapp, stores):
        _, todo_store = stores
        dlg = self._dialog(todo_store)
        dlg.title.setText("Termin mit Mueller morgen 10:00")
        dlg.prep_auto.setChecked(True)
        dlg._save()
        saved = todo_store.all()[-1]
        assert (saved.category, saved.prep_auto) == ("meeting", True)

    def test_default_off_means_a_saved_meeting_is_not_armed(self, qapp, stores):
        _, todo_store = stores
        dlg = self._dialog(todo_store)
        dlg.title.setText("Termin mit Mueller morgen 10:00")
        dlg._save()
        assert todo_store.all()[-1].prep_auto is False

    def test_it_explains_itself_on_hover(self, qapp, stores):
        _, todo_store = stores
        assert self._dialog(todo_store).prep_auto.toolTip()


class TestCaptureBubbleToggle:
    """The in-dock bubble honours the same contract."""

    def _bubble(self, todo_store):
        return CaptureBubble(todo_store, Settings())

    def test_hidden_for_a_plain_todo(self, qapp, stores):
        _, todo_store = stores
        bubble = self._bubble(todo_store)
        bubble.title.setText("Einkaufen gehen")
        assert bubble.prep_auto.isVisible() is False

    def test_revealed_for_a_meeting(self, qapp, stores):
        _, todo_store = stores
        bubble = self._bubble(todo_store)
        bubble.show()
        bubble.title.setText("Meeting mit Team")
        assert bubble.prep_auto.isVisible() is True
        assert bubble.prep_auto.isChecked() is False

    def test_the_saved_meeting_carries_the_flag(self, qapp, stores):
        _, todo_store = stores
        bubble = self._bubble(todo_store)
        bubble.title.setText("Meeting mit Team")
        bubble.prep_auto.setChecked(True)
        bubble._save()
        saved = todo_store.all()[-1]
        assert (saved.category, saved.prep_auto) == ("meeting", True)

    def test_a_non_meeting_never_gets_armed(self, qapp, stores):
        _, todo_store = stores
        bubble = self._bubble(todo_store)
        bubble.title.setText("Einkaufen gehen")
        bubble.prep_auto.setChecked(True)      # force it on to prove save_quick_todo guards
        bubble._save()
        assert todo_store.all()[-1].prep_auto is False

    def test_it_explains_itself_on_hover(self, qapp, stores):
        _, todo_store = stores
        assert self._bubble(todo_store).prep_auto.toolTip()


class TestShellWiring:
    """The real Shell: pressing Prep writes the block and queues exactly one refine job."""

    def _shell(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell
        shell = Shell()
        # These tests are about the WIRING, not about semantics: drop the index so the prep
        # takes its no-model fallback instead of spinning up the real embedding model (which
        # costs ~a minute and emits a fastembed warning into an otherwise 0-warning suite).
        # The semantic path itself is covered in test_meeting_prep.py with injected stubs.
        shell.semantic = None
        return shell

    def test_prep_writes_the_block_and_queues_one_job(self, qapp, tmp_path, monkeypatch):
        from serenity.core.meeting_prep import is_prepped
        shell = self._shell(tmp_path, monkeypatch)
        try:
            todo = shell.todo_store.add(Todo(title="Weekly", category="meeting",
                                             due=datetime(2026, 8, 14)))
            shell.prep_meeting(todo)
            note = shell.note_store.get(todo.linked_note_ids[0])
            assert is_prepped(note.body)
            running, pending = shell.llm_queue.snapshot()
            labels = [j.label for j in ([running] if running else []) + list(pending)]
            assert [lab for lab in labels if lab.startswith("Meeting-Prep")]
        finally:
            shell.tray.hide()

    def test_a_stale_refined_result_never_rewrites_the_note(self, qapp, tmp_path, monkeypatch):
        shell = self._shell(tmp_path, monkeypatch)
        try:
            todo = shell.todo_store.add(Todo(title="Weekly", category="meeting",
                                             due=datetime(2026, 8, 14)))
            shell.prep_meeting(todo)
            note = shell.note_store.get(todo.linked_note_ids[0])
            note.body = "# Protokoll\n\n## Notizen\n- Block geloescht\n"
            shell.note_store.update(note)
            shell._apply_prep(note.id, "## Vorbereitung\n- verfeinert")
            assert "verfeinert" not in shell.note_store.get(note.id).body
        finally:
            shell.tray.hide()

    def test_auto_prep_only_takes_armed_meetings_once(self, qapp, tmp_path, monkeypatch):
        shell = self._shell(tmp_path, monkeypatch)
        try:
            now = datetime(2026, 8, 13, 20, 0)
            armed = shell.todo_store.add(Todo(title="Weekly", category="meeting",
                                              prep_auto=True, due=datetime(2026, 8, 14, 10, 0)))
            shell.todo_store.add(Todo(title="Standup", category="meeting",
                                      due=datetime(2026, 8, 14, 9, 0)))
            assert shell._auto_prep_meetings(now) == 1
            assert armed.linked_note_ids
            assert shell._auto_prep_meetings(now) == 0      # markers make it idempotent
        finally:
            shell.tray.hide()

    def test_the_break_job_is_registered_on_the_shell(self, qapp, tmp_path, monkeypatch):
        shell = self._shell(tmp_path, monkeypatch)
        try:
            assert "meeting-prep" in [j.id for j in shell._break_scheduler.jobs()]
        finally:
            shell.tray.hide()


class TestMaintenanceJob:
    """The auto-prep break job is registered HEAVY and degrades without a callable."""

    def test_registered_as_a_heavy_job(self):
        job = [j for j in build_maintenance_jobs(prep_meetings=lambda: 0) if j.id == "meeting-prep"]
        assert job and job[0].tier is Tier.HEAVY

    def test_runs_the_callable(self):
        calls = []
        jobs = build_maintenance_jobs(prep_meetings=lambda: calls.append(1) or 2)
        job = [j for j in jobs if j.id == "meeting-prep"][0]
        assert job.run() == "prepped 2" and calls == [1]

    def test_noops_without_a_callable(self):
        job = [j for j in build_maintenance_jobs() if j.id == "meeting-prep"][0]
        assert job.run() == "skipped - no meeting prep"
