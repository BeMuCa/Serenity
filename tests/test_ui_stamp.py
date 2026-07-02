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
