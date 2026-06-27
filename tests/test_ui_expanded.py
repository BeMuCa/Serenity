"""
============================================================
Author:  Berk
Created: 2026-06-27
Purpose: Headless smoke tests for the Notes-expand UI foundation (dock_left_of + ExpandedPanel).
Role:    Under QT_QPA_PLATFORM=offscreen, assert platform_win.dock_left_of places a panel flush
         LEFT of an anchor on the anchor's screen and clamps/reduces width to keep the header on
         screen (P2-13), and that ExpandedPanel docks-left on show, routes both the X button and
         Esc through closeRequested (P2-12), and survives a torn-down anchor on close (P3-5).

Test classes:
- TestDockLeftOf - geometry: flush-left when room, left-clamp + width reduce when off-screen
- TestExpandedPanel - builds, docks left on show, Esc/close emit closeRequested, torn-down anchor
- TestNoteEditorPanel - the note editor: build/seed, dirty, commit, invalid-YAML, close-dirty,
  recover prompt, open-in-OS bool-gated hand-off (decisions delegated to core.note_draft)
============================================================
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget  # noqa: E402

from serenity.core.note_store import NoteStore  # noqa: E402
from serenity.ui import platform_win  # noqa: E402
from serenity.ui.expanded_panel import ExpandedPanel  # noqa: E402
from serenity.ui.note_editor_panel import NoteEditorPanel  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _screen_geo():
    screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry()


class TestDockLeftOf:
    def test_flush_left_when_room(self, qapp):
        geo = _screen_geo()
        anchor = QWidget()
        # anchor flush against the right edge (like the dock), narrow panel that fits to its left
        width = 400
        anchor.setGeometry(geo.right() - 348 + 1, geo.top(), 348, geo.height())
        panel = QWidget()
        assert platform_win.dock_left_of(panel, anchor, width) is True
        assert panel.x() == anchor.x() - width
        assert panel.width() == width

    def test_clamps_left_edge_and_reduces_width_when_off_screen(self, qapp):
        geo = _screen_geo()
        anchor = QWidget()
        # anchor near the LEFT edge so a wide panel to its left would run off-screen
        anchor.setGeometry(geo.left() + 100, geo.top(), 200, geo.height())
        panel = QWidget()
        width = 1000  # far wider than the 100px gap to the left edge
        assert platform_win.dock_left_of(panel, anchor, width) is True
        assert panel.x() >= geo.left()
        # width reduced so the panel's right edge still ends at the anchor's left edge
        assert panel.width() <= anchor.x() - geo.left()
        assert panel.x() + panel.width() == anchor.x()

    def test_returns_false_on_bad_anchor(self, qapp):
        # a non-widget anchor must not raise; guarded -> False
        assert platform_win.dock_left_of(QWidget(), object(), 300) is False


class TestExpandedPanel:
    def _panel(self, anchor=None):
        if anchor is None:
            geo = _screen_geo()
            anchor = QWidget()
            anchor.setGeometry(geo.right() - 348 + 1, geo.top(), 348, geo.height())
            anchor.show()
        content = QLabel("body")
        return ExpandedPanel("My Note", content, anchor), anchor

    def test_builds_and_sets_title(self, qapp):
        panel, _ = self._panel()
        panel.set_title("Renamed")
        assert "Renamed" in panel._title_label.text()

    def test_docks_left_on_show(self, qapp):
        panel, anchor = self._panel()
        panel.show()
        # full height of the anchor's screen, flush left of the anchor (room exists)
        assert panel.x() + panel.width() == anchor.x()

    def test_close_button_emits_close_requested(self, qapp):
        panel, _ = self._panel()
        seen = []
        panel.closeRequested.connect(lambda: seen.append(True))
        panel._close_btn.click()
        assert seen == [True]

    def test_escape_emits_close_requested(self, qapp):
        panel, _ = self._panel()
        seen = []
        panel.closeRequested.connect(lambda: seen.append(True))
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        panel.keyPressEvent(ev)
        assert seen == [True]

    def test_close_with_torn_down_anchor_does_not_raise(self, qapp):
        panel, anchor = self._panel()
        panel.show()
        anchor.deleteLater()
        anchor.close()
        # restore-focus path must swallow the deleted-C++-object RuntimeError (P3-5)
        panel.close()


class TestNoteEditorPanel:
    """Smoke tests for the note editor: every decision is delegated to core.note_draft;
    the panel only renders the outcomes. One behaviour per test (offscreen, openUrl mocked)."""

    def _store_note(self, tmp_path):
        store = NoteStore(tmp_path, index_path=tmp_path / "i.sqlite")
        note = store.create("Meeting", "First line.\nSecond line.", tags=["work"])
        return store, note

    def test_builds_and_seeds_body_and_frontmatter(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        assert panel.note_id == note.id
        assert panel.body.toPlainText() == note.body
        # the raw-YAML sub-editor is seeded from the loaded note's front-matter (P1-6)
        assert f"id: {note.id}" in panel.fm_edit.toPlainText()
        assert "title: Meeting" in panel.fm_edit.toPlainText()

    def test_typing_flips_dirty_and_writes_draft(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        assert panel._dirty is False
        panel.body.setPlainText("Edited body")
        assert panel._dirty is True
        # debounce slot writes the .draft sidecar (P2-5); fire it directly
        panel._flush_draft()
        from serenity.core import note_draft as nd
        from pathlib import Path
        assert Path(nd.draft_path(note.path)).exists()

    def test_commit_writes_via_store_emits_committed_and_deletes_draft(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel.body.setPlainText("Committed body")
        panel._flush_draft()
        seen = []
        panel.committed.connect(seen.append)
        panel.commit()
        assert seen == [note.id]
        assert store.get(note.id).body == "Committed body"
        from serenity.core import note_draft as nd
        from pathlib import Path
        assert not Path(nd.draft_path(note.path)).exists()  # draft deleted last (P2-1)

    def test_commit_stops_timer_first(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel.body.setPlainText("x")
        panel._timer.start()
        panel.commit()
        assert not panel._timer.isActive()  # stop() is the first line of commit (P2-3)

    def test_invalid_frontmatter_keeps_panel_open_with_error(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel._show_frontmatter(True)
        panel.fm_edit.setPlainText("id: [unclosed")  # invalid YAML -> NoteDraftInvalid
        panel._mark_dirty()
        closed = []
        panel.committed.connect(lambda _id: closed.append(_id))
        panel.commit()
        assert closed == []                       # no commit emitted
        assert not panel._error.isHidden()        # inline error shown (P1-1)
        assert panel._error.text()                # with a message
        # store untouched
        assert store.get(note.id).body == note.body

    def test_commit_on_purged_note_offers_save_as_new(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel.body.setPlainText("orphaned edit")
        store.purge(note.id)                       # vanish under the panel (P1-10)
        # decline the save-as-new offer
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Cancel))
        seen = []
        panel.committed.connect(seen.append)
        panel.commit()
        assert seen == []                          # not committed in place

    def test_close_while_dirty_prompts_and_discard_drops_draft(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel.body.setPlainText("dirty edit")
        panel._flush_draft()
        from serenity.core import note_draft as nd
        from pathlib import Path
        assert Path(nd.draft_path(note.path)).exists()
        asked = []
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: (asked.append(True), QMessageBox.Discard)[1]))
        accepted = panel.handle_close()            # Discard -> ok to close, draft removed (P2-12)
        assert asked == [True]
        assert accepted is True
        assert not Path(nd.draft_path(note.path)).exists()

    def test_close_while_dirty_cancel_keeps_open(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel.body.setPlainText("dirty edit")
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Cancel))
        accepted = panel.handle_close()
        assert accepted is False                   # default Cancel keeps the panel open (P2-12)

    def test_plain_close_when_clean_does_not_delete_draft(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)        # clean open, no draft yet
        # a draft appears from another surface AFTER open; this clean panel must not delete it
        from serenity.core import note_draft as nd
        from pathlib import Path
        nd.write_draft(note.path, "id: " + note.id, "leftover")
        assert panel._dirty is False
        assert panel.handle_close() is True
        assert Path(nd.draft_path(note.path)).exists()  # plain close never deletes (P2-12)

    def test_recover_prompts_on_recoverable_draft(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        # a divergent draft on disk -> recover() returns "recoverable"
        from serenity.core import note_draft as nd
        nd.write_draft(note.path, f"id: {note.id}\ntitle: Meeting", "RECOVERED body")
        asked = []
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: (asked.append(True), QMessageBox.Yes)[1]))
        panel = NoteEditorPanel(note, store)
        assert asked == [True]                     # prompted on open (P2-2)
        assert "RECOVERED body" in panel.body.toPlainText()  # accepted -> draft loaded

    def test_recover_decline_discards_draft(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        from serenity.core import note_draft as nd
        from pathlib import Path
        nd.write_draft(note.path, f"id: {note.id}\ntitle: Meeting", "RECOVERED body")
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.No))
        NoteEditorPanel(note, store)
        assert not Path(nd.draft_path(note.path)).exists()  # decline == discard (P2-2)

    def test_open_in_os_closes_only_when_openurl_true(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        from PySide6.QtGui import QDesktopServices
        monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: True))
        closed = []
        panel.closeRequested.connect(lambda: closed.append(True))
        panel.open_in_os()
        assert closed == [True]                    # only closes on True (P3-3)

    def test_open_in_os_keeps_open_when_openurl_false(self, qapp, tmp_path, monkeypatch):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        from PySide6.QtGui import QDesktopServices
        monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: False))
        closed = []
        panel.closeRequested.connect(lambda: closed.append(True))
        panel.open_in_os()
        assert closed == []                        # no close on False; inline notice (P3-3)
        assert not panel._error.isHidden()
        assert panel._error.text()

    def test_deleted_flip_acknowledged_non_blocking(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        panel._show_frontmatter(True)
        fm = panel.fm_edit.toPlainText().rstrip() + "\ndeleted: true"
        panel.fm_edit.setPlainText(fm)             # edit via the FM editor (P3-2)
        seen = []
        panel.committed.connect(seen.append)
        assert panel.commit() is True              # non-blocking: commit still succeeds
        assert seen == [note.id]
        assert store.get(note.id).deleted is True
        assert "Trash" in panel._error.text()      # acknowledgment, not a refusal

    def test_frontmatter_toggle_shows_sub_editor(self, qapp, tmp_path):
        store, note = self._store_note(tmp_path)
        panel = NoteEditorPanel(note, store)
        assert panel.fm_edit.isHidden() is True     # hidden until toggled
        panel._show_frontmatter(True)
        assert panel.fm_edit.isHidden() is False
