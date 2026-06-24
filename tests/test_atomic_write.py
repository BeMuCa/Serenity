"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: Unit tests for core.paths.atomic_write_text.
Role:    Guards the crash-safe write contract used wherever Serenity persists a
         file: content is written via a sibling .tmp then os.replace'd in, so the
         target is never truncated, no .tmp is orphaned, and an existing file is
         atomically replaced.

Test classes:
- TestAtomicWriteText - writes content; target is complete; no .tmp left behind;
                        overwrite replaces an existing file; tmp cleaned on failure
============================================================
"""

import pytest

from serenity.core.paths import atomic_write_text


class TestAtomicWriteText:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "note.md"
        atomic_write_text(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_target_is_complete(self, tmp_path):
        # the whole payload lands; nothing truncated.
        target = tmp_path / "big.txt"
        payload = "x" * 100_000
        atomic_write_text(target, payload)
        assert target.read_text(encoding="utf-8") == payload

    def test_no_tmp_left_behind(self, tmp_path):
        target = tmp_path / "note.md"
        atomic_write_text(target, "data")
        # only the target exists; the sibling .tmp was renamed away.
        assert not (tmp_path / "note.md.tmp").exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["note.md"]

    def test_overwrite_replaces_existing(self, tmp_path):
        target = tmp_path / "note.md"
        target.write_text("OLD content that is longer", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"
        assert not (tmp_path / "note.md.tmp").exists()

    def test_tmp_cleaned_up_on_failure(self, tmp_path, monkeypatch):
        # if the replace fails, the .tmp must not be orphaned and the error propagates.
        import serenity.core.paths as paths_mod

        target = tmp_path / "note.md"

        def boom(_src, _dst):
            raise OSError("replace failed")

        monkeypatch.setattr(paths_mod.os, "replace", boom)
        with pytest.raises(OSError):
            atomic_write_text(target, "data")
        assert not (tmp_path / "note.md.tmp").exists()
        assert not target.exists()
