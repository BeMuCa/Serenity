"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: P1 durability tests for NoteStore — atomic .md writes + guarded mutate-after-success
         + a purge unlink-failure guard, so a crash/OSError never leaves a torn file or a
         memory/disk divergence that resurrects or vanishes a note on restart.
Role:    Guards serenity.core.note_store against the three notes-area P1 gaps in
         notes/5_Interaction_Flows.md (flows 9, 10, 11): (1) _write routes through
         paths.atomic_write_text; (2) a write OSError on soft_delete/restore/set_pinned
         leaves the in-memory Note/_notes/index UNCHANGED (no resurrection on reindex);
         (3) a purge unlink OSError does NOT drop the row/file so the file is not orphaned.
         Pure + headless: a real tmp vault, OSError forced by monkeypatching
         paths.atomic_write_text / Path.unlink to raise. No Qt.

Test classes:
- TestAtomicWrite      - _write goes through paths.atomic_write_text; no torn file on failure
- TestGuardedMutate    - soft_delete/restore/set_pinned re-raise + leave state unmutated on OSError
- TestPurgeUnlinkGuard - purge unlink OSError keeps the row + propagates (no orphan resurrection)
============================================================
"""

from pathlib import Path

import pytest

from serenity.core import note_store as ns
from serenity.core.note_store import NoteStore


class TestAtomicWrite:
    def test_write_routes_through_atomic_write_text(self, tmp_path, monkeypatch):
        store = NoteStore(tmp_path)
        calls = []
        real = ns.atomic_write_text
        monkeypatch.setattr(
            ns, "atomic_write_text",
            lambda p, text, **kw: (calls.append(Path(p)), real(p, text, **kw))[1],
        )
        note = store.create("Hello", body="world")
        assert Path(note.path) in calls               # create's .md write went through the helper

    def test_create_failure_leaves_no_torn_file(self, tmp_path, monkeypatch):
        store = NoteStore(tmp_path)

        def boom(p, text, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(ns, "atomic_write_text", boom)
        with pytest.raises(OSError):
            store.create("Doomed", body="x")
        # no torn .md and no stray .tmp left behind
        assert list((tmp_path / "notes").glob("*.md")) == []
        assert list((tmp_path / "notes").glob("*.tmp")) == []


class TestGuardedMutate:
    def _store_with_note(self, tmp_path):
        store = NoteStore(tmp_path)
        note = store.create("Keep me", body="body")
        return store, note

    def test_soft_delete_write_failure_keeps_note_active(self, tmp_path, monkeypatch):
        store, note = self._store_with_note(tmp_path)

        monkeypatch.setattr(ns, "atomic_write_text",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            store.soft_delete(note.id)

        # in-memory state must NOT have flipped (else reindex resurrects/vanishes the note)
        assert store.get(note.id).deleted is False
        assert note.deleted is False
        assert store.get(note.id) in store.all_active()
        # disk is the source of truth on restart; it must still say active
        store2 = NoteStore(tmp_path)
        assert store2.get(note.id).deleted is False

    def test_restore_write_failure_keeps_note_trashed(self, tmp_path, monkeypatch):
        store, note = self._store_with_note(tmp_path)
        store.soft_delete(note.id)                     # genuinely trashed first
        assert store.get(note.id).deleted is True

        monkeypatch.setattr(ns, "atomic_write_text",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            store.restore(note.id)

        assert store.get(note.id).deleted is True
        assert note.deleted is True
        store2 = NoteStore(tmp_path)                    # restart reads disk
        assert store2.get(note.id).deleted is True

    def test_set_pinned_write_failure_keeps_prior_pin(self, tmp_path, monkeypatch):
        store, note = self._store_with_note(tmp_path)
        assert note.pinned is False

        monkeypatch.setattr(ns, "atomic_write_text",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            store.set_pinned(note.id, True)

        assert store.get(note.id).pinned is False
        assert note.pinned is False
        store2 = NoteStore(tmp_path)
        assert store2.get(note.id).pinned is False


class TestPurgeUnlinkGuard:
    def test_purge_unlink_failure_keeps_row_and_propagates(self, tmp_path, monkeypatch):
        store = NoteStore(tmp_path)
        note = store.create("Forever?", body="x")

        monkeypatch.setattr(Path, "unlink",
                            lambda self, *a, **k: (_ for _ in ()).throw(OSError("locked")))
        with pytest.raises(OSError):
            store.purge(note.id)

        # the row must NOT have been removed (file still on disk -> would resurrect)
        assert store.get(note.id) is not None
        assert store._db.execute(
            "SELECT 1 FROM notes WHERE id=?", (note.id,)
        ).fetchone() is not None
        # file is still there (we forced unlink to fail) -> consistent with the kept row
        assert Path(note.path).exists()
