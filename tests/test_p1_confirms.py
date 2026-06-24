"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: Headless guards for the P1 confirm dialogs before IRREVERSIBLE actions.
Role:    Proves the new confirm gates exist and actually gate the destructive call
         in TrashView (purge / 'Delete forever') and SettingsWindow (remove clone).
         The QMessageBox prompts themselves are interactive, so each test monkeypatches
         QMessageBox.question to simulate the user's Yes / No choice and asserts that
         declining leaves the item intact while accepting destroys it. Skips cleanly
         when PySide6 cannot start offscreen.

Test classes:
- TestTrashPurgeConfirm - decline keeps the trashed note; accept purges it
- TestRemoveCloneConfirm - decline keeps the clone; accept removes it
============================================================
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from serenity.core.note_store import NoteStore  # noqa: E402
from serenity.core.settings import Settings  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.core.voice_clones import CloneRegistry  # noqa: E402
from serenity.ui.settings_window import SettingsWindow  # noqa: E402
from serenity.ui.trash_view import TrashView  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestTrashPurgeConfirm:
    def _trashed_view(self, tmp_path):
        """A TrashView holding one soft-deleted note ready to be purged."""
        vault = tmp_path / "vault"
        todo_store = TodoStore(vault)
        note_store = NoteStore(vault, index_path=tmp_path / "notes.db")
        note = note_store.create("Doomed note", "body")
        note_store.soft_delete(note.id)
        assert len(note_store.trash()) == 1
        return TrashView(todo_store, note_store), note_store, note.id

    def test_decline_does_not_purge(self, qapp, tmp_path, monkeypatch):
        view, note_store, note_id = self._trashed_view(tmp_path)
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Cancel)
        view._purge_note(note_id)
        # Declined: the note must still be in the trash, not gone.
        assert len(note_store.trash()) == 1

    def test_accept_purges(self, qapp, tmp_path, monkeypatch):
        view, note_store, note_id = self._trashed_view(tmp_path)
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        view._purge_note(note_id)
        assert len(note_store.trash()) == 0

    def test_confirm_guard_default_is_cancel(self, qapp, tmp_path, monkeypatch):
        """The guard method exists and passes Cancel as the default button."""
        view, _store, _id = self._trashed_view(tmp_path)
        captured = {}

        def fake_question(parent, title, text, buttons=0, default=0):
            captured["default"] = default
            return QMessageBox.Cancel

        monkeypatch.setattr(QMessageBox, "question", fake_question)
        assert view._confirm_purge() is False
        assert captured["default"] == QMessageBox.Cancel


class TestRemoveCloneConfirm:
    def _window_with_clone(self, tmp_path):
        """A SettingsWindow whose clone registry has one (no-copy) clone selected."""
        settings = Settings()
        settings.vault_path = str(tmp_path / "vault")
        settings.voices_dir = str(tmp_path / "voices")
        win = SettingsWindow(settings)
        # Seed a clone without touching disk (copy=False), then mirror it into the list.
        clip = tmp_path / "ref.wav"
        clip.write_bytes(b"")
        clone = win.clones.add("Berk", "de", clip, copy=False)
        win._refresh_clone_list()
        win.clone_list.setCurrentRow(0)
        return win, clone.voice_id

    def test_decline_does_not_remove(self, qapp, tmp_path, monkeypatch):
        win, voice_id = self._window_with_clone(tmp_path)
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.No)
        win._remove_clone()
        assert win.clones.get(voice_id) is not None

    def test_accept_removes(self, qapp, tmp_path, monkeypatch):
        win, voice_id = self._window_with_clone(tmp_path)
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        win._remove_clone()
        assert win.clones.get(voice_id) is None

    def test_confirm_default_is_no(self, qapp, tmp_path, monkeypatch):
        """Remove-clone confirm passes No as the default button."""
        win, voice_id = self._window_with_clone(tmp_path)
        captured = {}

        def fake_question(parent, title, text, buttons=0, default=0):
            captured["default"] = default
            return QMessageBox.No

        monkeypatch.setattr(QMessageBox, "question", fake_question)
        win._remove_clone()
        assert captured["default"] == QMessageBox.No
        assert win.clones.get(voice_id) is not None
