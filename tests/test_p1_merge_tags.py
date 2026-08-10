"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: Regression tests for the two P1 data-safety gaps in AI maintenance (flows 17 + 21):
         a transactional / idempotent-on-retry note merge, and a fail-fast bulk tag rewrite.
Role:    Guards core.dedup.merge_notes and core.tagsync.consolidate_tag against a mid-operation
         write failure. Each test injects an OSError into the real NoteStore at a precise step
         and asserts the vault is left in a clean, recoverable, re-runnable state - NO content
         duplication, NO half-applied partial rewrite that a re-run cannot finish.

Test classes:
- TestMergeTransactional - merge_notes: drop trashed before keep's destructive commit; a failed
  keep-commit leaves keep un-merged + drop trashed, and a retry merges cleanly (no double body).
- TestConsolidateAbortsEarly - consolidate_tag: a per-note write error aborts early, returns how
  many notes succeeded, leaves only those rewritten, and a re-run finishes the rest (idempotent).
============================================================
"""

import pytest

from serenity.core.dedup import MERGE_SEPARATOR, merge_notes
from serenity.core.note_store import NoteStore
from serenity.core.settings import Settings
from serenity.core.tagsync import consolidate_tag


def _settings(tmp_path, tags):
    s = Settings()
    s._path = tmp_path / "settings.json"
    s.tags = list(tags)
    return s


class TestMergeTransactional:
    """The destructive append onto `keep` must only finalize AFTER `drop` is safely trashed."""

    def test_drop_trashed_before_keep_committed(self, tmp_path):
        # If keep's destructive commit is what fails, drop must ALREADY be trashed (the safe
        # order) and keep must NOT carry the merged body on disk -> no silent duplication.
        store = NoteStore(tmp_path)
        keep = store.create("Keep", body="keep body", tags=["work"])
        drop = store.create("Drop", body="drop body", tags=["urgent"])

        real_write = store._write

        def failing_write(note):
            if note.id == keep.id:           # fail ONLY the keep destructive commit
                raise OSError("disk full during keep update")
            return real_write(note)

        store._write = failing_write
        with pytest.raises(OSError):
            merge_notes(store, keep.id, drop.id)

        # drop was trashed first -> safe + recoverable.
        assert store.get(drop.id).deleted is True
        # keep was NOT committed-merged: its body must still be the original, with no drop body.
        keep_after = store.get(keep.id)
        assert keep_after.body == "keep body"
        assert "drop body" not in keep_after.body
        assert MERGE_SEPARATOR not in keep_after.body
        assert keep_after.tags == ["work"]   # tags not destructively unioned either

    def test_retry_after_failed_keep_commit_no_double_append(self, tmp_path):
        # Simulate the crash window: keep-commit failed once (drop already trashed). A retry of
        # the SAME merge must finish cleanly - drop body appended EXACTLY ONCE, no duplication.
        store = NoteStore(tmp_path)
        keep = store.create("Keep", body="keep body", tags=["work"])
        drop = store.create("Drop", body="drop body", tags=["urgent"])

        real_write = store._write
        state = {"fail_keep": True}

        def maybe_failing_write(note):
            if note.id == keep.id and state["fail_keep"]:
                raise OSError("disk full during keep update")
            return real_write(note)

        store._write = maybe_failing_write
        with pytest.raises(OSError):
            merge_notes(store, keep.id, drop.id)

        # Retry: the keep-commit now succeeds (drop already trashed from the first attempt).
        state["fail_keep"] = False
        kept = merge_notes(store, keep.id, drop.id)

        assert kept.body.count("drop body") == 1     # appended exactly once, NOT twice
        assert "keep body" in kept.body
        assert MERGE_SEPARATOR in kept.body
        assert kept.tags == ["work", "urgent"]       # union applied exactly once
        assert store.get(drop.id).deleted is True

    def test_failed_drop_trash_leaves_keep_unmerged(self, tmp_path):
        # If trashing the drop fails (the FIRST destructive step), keep must be wholly untouched
        # so the whole merge can be retried from scratch with no residue.
        store = NoteStore(tmp_path)
        keep = store.create("Keep", body="keep body", tags=["work"])
        drop = store.create("Drop", body="drop body", tags=["urgent"])

        real_write = store._write

        def failing_write(note):
            if note.id == drop.id:           # fail the soft_delete(drop) write
                raise OSError("disk full during drop soft-delete")
            return real_write(note)

        store._write = failing_write
        with pytest.raises(OSError):
            merge_notes(store, keep.id, drop.id)

        keep_after = store.get(keep.id)
        assert keep_after.body == "keep body"        # untouched
        assert keep_after.tags == ["work"]
        assert store.get(drop.id).deleted is False    # still active -> clean retry


class TestConsolidateAbortsEarly:
    """A per-note write error must abort early, returning how many notes were rewritten."""

    def test_partial_failure_returns_succeeded_count(self, tmp_path):
        store = NoteStore(tmp_path)
        store.create("A", tags=["proj"])
        store.create("B", tags=["proj"])
        store.create("C", tags=["proj"])
        settings = _settings(tmp_path, ["proj"])

        # Fail the write of whichever note is processed THIRD, so exactly 2 succeed.
        real_write = store._write
        seen = {"n": 0}

        def failing_write(note):
            seen["n"] += 1
            if seen["n"] == 3:
                raise OSError("disk full mid bulk rewrite")
            return real_write(note)

        store._write = failing_write
        done = consolidate_tag(store, settings, "project", ["proj"])

        # Returned the count actually rewritten (not a crash, not a silent half-apply).
        assert done == 2
        rewritten = [n for n in store.all_active() if n.tags == ["project"]]
        remaining = [n for n in store.all_active() if n.tags == ["proj"]]
        assert len(rewritten) == 2
        assert len(remaining) == 1                    # the one that failed is unchanged

    def test_rerun_finishes_after_partial(self, tmp_path):
        # consolidate_tag is idempotent, so a clean re-run must finish the leftover note(s).
        store = NoteStore(tmp_path)
        store.create("A", tags=["proj"])
        store.create("B", tags=["proj"])
        store.create("C", tags=["proj"])
        settings = _settings(tmp_path, ["proj"])

        real_write = store._write
        state = {"fail_on": 3, "n": 0}

        def failing_write(note):
            state["n"] += 1
            if state["n"] == state["fail_on"]:
                raise OSError("disk full mid bulk rewrite")
            return real_write(note)

        store._write = failing_write
        assert consolidate_tag(store, settings, "project", ["proj"]) == 2

        # Clean re-run: only the one leftover note still needs rewriting.
        store._write = real_write
        assert consolidate_tag(store, settings, "project", ["proj"]) == 1
        assert all(n.tags == ["project"] for n in store.all_active())

    def test_no_failure_returns_full_count(self, tmp_path):
        # Sanity: with no injected failure the count is unchanged from the existing behaviour.
        store = NoteStore(tmp_path)
        store.create("A", tags=["proj"])
        store.create("B", tags=["proj"])
        settings = _settings(tmp_path, ["proj"])
        assert consolidate_tag(store, settings, "project", ["proj"]) == 2
