"""
============================================================
Author:  Berk
Created: 2026-07-03
Purpose: UI tests for the Phase C creation-time stamp (state_tag + context).
Role:    Under QT_QPA_PLATFORM=offscreen, assert Shell.stamp() reads the running
         span + global context, every direct creation funnel stamps at save time,
         and the voice/NL capture path applies its parse-time snapshot (R10/R11).

Test classes:
- TestShellStamp - stamp() values, add-bar save-time stamp, capture snapshot
- TestModalStamp - QuickTodoDialog / QuickNoteDialog stamp at _save()
- (the capture-bar quick-todo path opens CaptureBubble; see test_capture_bubble.py)
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from serenity.core.settings import Settings
from serenity.core.note_store import NoteStore
from serenity.core.todo_store import TodoStore
from serenity.ui.modals import QuickNoteDialog, QuickTodoDialog


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class TestShellStamp:
    def _shell(self, tmp_path, monkeypatch, context="business"):
        # isolate config + vault (so a running span never leaks between tests) + no real autostart
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import platform_win
        from serenity.core import paths
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
        from serenity.ui.shell import Shell
        sh = Shell()
        sh.settings.current_context = context
        return sh

    def test_stamp_reads_running_and_context(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Working")
            assert sh.stamp() == ("working", "business")
            sh._on_activity("Idle")
            assert sh.stamp() == (None, "business")
        finally:
            sh.tray.hide()

    def test_stamp_unmappable_label_is_none(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch)
        try:
            sh.activity_store.start("NoSuchLabel")     # a span whose label left the registry
            assert sh.stamp()[0] is None
        finally:
            sh.tray.hide()

    def test_add_bar_stamps_at_save(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Coding")
            sh.todos_view.add_input.setText("write tests")
            sh.todos_view._add()
            t = sh.todo_store.all()[-1]
            assert (t.state_tag, t.context) == ("coding", "business")
        finally:
            sh.tray.hide()

    def test_capture_snapshot_survives_switch(self, qapp, tmp_path, monkeypatch):
        # R10: the stamp is snapshotted when the capture is parsed (_pending set); a
        # mid-slot-fill context flip or activity switch never changes the committed stamp.
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Working")
            sh._demo_capture("Erinnerung Zahnarzt anrufen")     # todo intent, date missing -> asks
            assert sh._pending is not None
            sh.set_context("private")
            sh._on_activity("Gaming")
            sh._on_slot_answer("morgen")                        # fills the date -> commits
            t = sh.todo_store.all()[-1]
            assert (t.state_tag, t.context) == ("working", "business")   # snapshot, not "now"
            assert sh._pending_stamp is None                    # cleared with the commit
        finally:
            sh.tray.hide()

    def test_voice_note_commit_stamps(self, qapp, tmp_path, monkeypatch):
        sh = self._shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Meeting")
            from serenity.core.parser import parse_capture
            cap = parse_capture("Notiz Ideen für das Board")     # note intent, complete
            sh._pending = cap
            sh._pending_stamp = sh.stamp()
            sh._commit_capture(cap)
            n = sh.note_store.all_active()[0]
            assert (n.state_tag, n.context) == ("meeting", "business")
        finally:
            sh.tray.hide()


class TestModalStamp:
    def test_quick_todo_stamps_at_save(self, qapp, tmp_path):
        store = TodoStore(tmp_path / "vault")
        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = QuickTodoDialog(store, s, stamp=lambda: ("working", "private"))
        dlg.title.setText("quick one")
        dlg._save()
        t = store.all()[-1]
        assert (t.state_tag, t.context) == ("working", "private")

    def test_quick_note_stamps_at_save(self, qapp, tmp_path):
        store = NoteStore(tmp_path / "vault")
        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = QuickNoteDialog(store, s, stamp=lambda: (None, "business"))
        dlg.title.setText("quick note")
        dlg.body.setPlainText("body")
        dlg._save()
        n = store.all_active()[0]
        assert (n.state_tag, n.context) == (None, "business")

    def test_dialogs_without_stamp_stay_unstamped(self, qapp, tmp_path):
        # back-compat: existing callers/tests that pass no stamp keep working
        store = TodoStore(tmp_path / "vault")
        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = QuickTodoDialog(store, s)
        dlg.title.setText("plain")
        dlg._save()
        t = store.all()[-1]
        assert (t.state_tag, t.context) == (None, None)

    def test_quick_todo_reads_stamp_at_save_not_construction(self, qapp, tmp_path):
        # R10: the stamp is read inside _save, never cached at construction.
        store = TodoStore(tmp_path / "vault")
        s = Settings(); s._path = tmp_path / "settings.json"
        cell = {"v": ("working", "business")}
        dlg = QuickTodoDialog(store, s, stamp=lambda: cell["v"])
        cell["v"] = ("coding", "private")             # change AFTER construction
        dlg.title.setText("x")
        dlg._save()
        t = store.all()[-1]
        assert (t.state_tag, t.context) == ("coding", "private")

    def test_quick_note_reads_stamp_at_save_not_construction(self, qapp, tmp_path):
        store = NoteStore(tmp_path / "vault")
        s = Settings(); s._path = tmp_path / "settings.json"
        cell = {"v": ("working", "business")}
        dlg = QuickNoteDialog(store, s, stamp=lambda: cell["v"])
        cell["v"] = ("coding", "private")
        dlg.title.setText("x"); dlg.body.setPlainText("b")
        dlg._save()
        n = store.all_active()[0]
        assert (n.state_tag, n.context) == ("coding", "private")


class TestShellFunnelStampThreading:
    """R11: the shell threads stamp=self.stamp into its quick dialogs, and no in-app
    creation funnel produces context=None (the spec-mandated sweep)."""

    def _shell(self, tmp_path, monkeypatch, context="business"):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import platform_win
        from serenity.core import paths
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
        from serenity.ui.shell import Shell
        sh = Shell()
        sh.settings.current_context = context
        return sh

    def test_open_quick_todo_threads_shell_stamp(self, qapp, tmp_path, monkeypatch):
        """The capture-bar path now opens the in-dock CaptureBubble (the dialog stays only
        for calendar slot-create), but it must still thread the shell's bound stamp."""
        got = {}

        class _Fake:
            def __init__(self, store, settings, parent=None, stamp=None):
                got["stamp"] = stamp
                class _S:
                    def connect(self, *a): pass
                self.added = _S()
            def isVisible(self): return False
            def open_above(self, anchor): got["anchor"] = anchor

        monkeypatch.setattr("serenity.ui.capture_bubble.CaptureBubble", _Fake)
        sh = self._shell(tmp_path, monkeypatch)
        try:
            sh._open_quick_todo()
            assert got["stamp"].__self__ is sh and got["stamp"].__func__ is type(sh).stamp
            assert got["anchor"] is sh.capture.todo_btn        # anchored to its own button
        finally:
            sh.tray.hide()

    def test_open_quick_note_threads_shell_stamp(self, qapp, tmp_path, monkeypatch):
        got = {}

        class _Fake:
            def __init__(self, store, settings, parent=None, stamp=None):
                got["stamp"] = stamp
                class _S:
                    def connect(self, *a): pass
                self.saved = _S()
            def exec(self): pass

        monkeypatch.setattr("serenity.ui.shell.QuickNoteDialog", _Fake)
        sh = self._shell(tmp_path, monkeypatch)
        try:
            sh._open_quick_note()
            assert got["stamp"].__self__ is sh and got["stamp"].__func__ is type(sh).stamp
        finally:
            sh.tray.hide()

    def test_no_in_app_funnel_produces_context_none(self, qapp, tmp_path, monkeypatch):
        # Drive the real funnels (add-bar, capture todo+note) with an activity + context set,
        # then assert every created item carries a concrete context (R11 sweep).
        from serenity.core.parser import parse_capture
        sh = self._shell(tmp_path, monkeypatch, "private")
        try:
            sh._on_activity("Gaming")
            sh.todos_view.add_input.setText("play")
            sh.todos_view._add()
            sh._demo_capture("Erinnerung Zahnarzt anrufen"); sh._on_slot_answer("morgen")
            cap = parse_capture("Notiz eine idee")
            sh._pending, sh._pending_stamp = cap, sh.stamp()
            sh._commit_capture(cap)
            assert all(t.context is not None for t in sh.todo_store.all())
            assert all(n.context is not None for n in sh.note_store.all_active())
        finally:
            sh.tray.hide()


class TestDerivedStamp:
    def test_prep_note_inherits_todo_stamp(self, qapp, tmp_path):
        # R12: the prep/protocol note belongs to its todo's world, not to "now".
        from datetime import datetime
        from serenity.core.models import Todo
        from serenity.ui.todos_view import TodoCard
        ts = TodoStore(tmp_path / "vault")
        ns = NoteStore(tmp_path / "vault")
        todo = ts.add(Todo(title="meet", state_tag="meeting", context="business"))
        card = TodoCard(todo, ts, datetime.now(), note_store=ns)
        card._on_note_btn()
        note = ns.get(todo.linked_note_ids[0])
        assert (note.state_tag, note.context) == ("meeting", "business")

    def test_save_as_new_keeps_stamp(self, qapp, tmp_path, monkeypatch):
        # R12: pop-out recovery re-save carries the old note's stamp.
        from PySide6.QtWidgets import QMessageBox
        from serenity.ui.note_editor_panel import NoteEditorPanel
        ns = NoteStore(tmp_path / "vault")
        note = ns.create("gone soon", body="b", state_tag="working", context="business")
        panel = NoteEditorPanel(note, ns)
        panel.body.setPlainText("orphaned edit")
        ns.purge(note.id)                          # vanish under the panel
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Yes))
        panel.commit()                             # -> _save_as_new, accepted
        new = ns.get(panel.note_id)
        assert new.id != note.id
        assert (new.state_tag, new.context) == ("working", "business")
