"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for near-duplicate / fragment detection + the safe, recoverable merge.
Role:    Guards core.dedup (Job 3): find_duplicates over both the deterministic token degrade
         path (the one that runs in this env / on the user's machine today) and the
         StubEmbedder-backed embedding path, fragment containment, unordered-pair dedup,
         self/deleted exclusion, threshold boundaries, empty/one-note vaults, cap + sort, and
         merge_notes (append body + union tags + keep color/pin + soft_delete-not-purge).
         Also covers the new SemanticIndex.neighbours pair-finding surface.

Test classes:
- TestFindDuplicatesTokens - the deterministic degrade path (index=None)
- TestFindDuplicatesSemantic - the StubEmbedder embedding path
- TestNeighbours - SemanticIndex.neighbours lazy/degrade + scores
- TestMergeNotes - safe + recoverable merge on a real NoteStore
- TestDefaultKeep - which note is kept by default
============================================================
"""

from datetime import datetime

import pytest

from serenity.core.dedup import (
    DUP_COSINE,
    MAX_SUGGESTIONS,
    MERGE_SEPARATOR,
    DupPair,
    default_keep,
    find_duplicates,
    merge_notes,
)
from serenity.core.models import Note
from serenity.core.note_store import NoteStore
from serenity.core.phase2_stubs import SemanticIndex
from serenity.core.semantic import StubEmbedder


def mk(title, body="", tags=None, deleted=False, updated=None, nid=None):
    n = Note(
        title=title, body=body, tags=tags or [], deleted=deleted,
        updated=updated or datetime(2026, 6, 19, 10, 0),
    )
    if nid is not None:
        n.id = nid
    return n


# A long, distinctive body and a near-identical twin (Jaccard >= 0.80).
_LONG = ("project roadmap quarter goals ship the beta release by friday and review the "
         "budget with finance before the board meeting next monday afternoon")
_LONG_TWIN = ("project roadmap quarter goals ship the beta release by friday and review the "
              "budget with finance before the board meeting next monday morning")
_OTHER = ("grocery shopping list apples bananas oranges milk bread eggs cheese yoghurt and "
          "a bag of frozen peas from the corner store")


class TestFindDuplicatesTokens:
    def test_near_duplicate_detected(self):
        a = mk("Roadmap", body=_LONG, nid="a")
        b = mk("Roadmap copy", body=_LONG_TWIN, nid="b")
        c = mk("Groceries", body=_OTHER, nid="c")
        pairs = find_duplicates([a, b, c], index=None)
        dups = [p for p in pairs if p.kind == "duplicate"]
        assert len(dups) == 1
        assert {dups[0].a_id, dups[0].b_id} == {"a", "b"}
        # The unrelated note is not paired with either.
        assert all("c" not in (p.a_id, p.b_id) for p in pairs)

    def test_fragment_detected(self):
        long = mk("Full plan", body=_LONG, nid="long")
        # A short note whose tokens are a contained subset of the long one (>=5 tokens,
        # well under FRAGMENT_MAX_RATIO of the long note's distinct token count).
        frag = mk("Snippet", body="ship the beta release friday budget", nid="frag")
        pairs = find_duplicates([long, frag], index=None)
        frags = [p for p in pairs if p.kind == "fragment"]
        assert len(frags) == 1
        # a_id is ALWAYS the longer note, b_id the shorter fragment.
        assert frags[0].a_id == "long"
        assert frags[0].b_id == "frag"

    def test_unordered_pairs_deduped(self):
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG_TWIN, nid="b")
        pairs = find_duplicates([a, b], index=None)
        keys = [frozenset((p.a_id, p.b_id)) for p in pairs]
        assert len(keys) == len(set(keys))   # never both (a,b) and (b,a)

    def test_no_self_pairs(self):
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG_TWIN, nid="b")
        pairs = find_duplicates([a, b], index=None)
        assert all(p.a_id != p.b_id for p in pairs)

    def test_deleted_excluded(self):
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG_TWIN, nid="b", deleted=True)
        pairs = find_duplicates([a, b], index=None)
        assert pairs == []

    def test_empty_and_single_note_no_crash(self):
        assert find_duplicates([], index=None) == []
        assert find_duplicates([mk("only", body=_LONG, nid="x")], index=None) == []

    def test_fragment_min_tokens(self):
        long = mk("Full plan", body=_LONG, nid="long")
        tiny = mk("Tiny", body="ship beta", nid="tiny")   # only ~3 distinct tokens
        pairs = find_duplicates([long, tiny], index=None)
        assert all(p.kind != "fragment" for p in pairs)

    def test_fragment_not_when_similar_length(self):
        # Two same-length near-identical notes -> 'duplicate', not 'fragment'
        # (FRAGMENT_MAX_RATIO guard: the shorter is not genuinely shorter).
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG_TWIN, nid="b")
        pairs = find_duplicates([a, b], index=None)
        assert len(pairs) == 1
        assert pairs[0].kind == "duplicate"

    def test_duplicate_wins_over_fragment(self):
        # A pair that could qualify as both keeps only the 'duplicate' entry. Identical
        # bodies of differing token counts is hard to force, so assert the canonical rule:
        # a near-dup pair yields exactly one entry and it is 'duplicate'.
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG_TWIN, nid="b")
        pairs = find_duplicates([a, b], index=None)
        keys = [frozenset((p.a_id, p.b_id)) for p in pairs]
        assert keys.count(frozenset({"a", "b"})) == 1
        assert pairs[0].kind == "duplicate"

    def test_sorted_desc_and_cap(self):
        # Many identical notes -> many qualifying pairs, all score ~1.0, sorted desc and
        # capped at MAX_SUGGESTIONS.
        notes = [mk(f"N{i}", body=_LONG, nid=f"n{i}") for i in range(12)]
        pairs = find_duplicates(notes, index=None)
        scores = [p.score for p in pairs]
        assert scores == sorted(scores, reverse=True)
        assert len(pairs) <= MAX_SUGGESTIONS
        # The explicit limit param is honoured too.
        assert len(find_duplicates(notes, index=None, limit=3)) <= 3

    def test_deterministic(self):
        notes = [mk("X", body=_LONG, nid="a"),
                 mk("Y", body=_LONG_TWIN, nid="b"),
                 mk("Z", body=_OTHER, nid="c")]
        out1 = find_duplicates(notes, index=None)
        out2 = find_duplicates(notes, index=None)
        assert out1 == out2


class TestFindDuplicatesSemantic:
    def _index(self, notes):
        idx = SemanticIndex(StubEmbedder(dim=64))
        idx.index(notes)
        return idx

    def test_semantic_path_detects_duplicate(self):
        # Essentially-identical bodies -> StubEmbedder cosine ~1.0 (>= DUP_COSINE 0.92).
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG, nid="b")
        c = mk("Z", body=_OTHER, nid="c")
        idx = self._index([a, b, c])
        pairs = find_duplicates([a, b, c], index=idx)
        dups = [p for p in pairs if p.kind == "duplicate"]
        assert len(dups) == 1
        assert {dups[0].a_id, dups[0].b_id} == {"a", "b"}
        assert dups[0].score >= DUP_COSINE

    def test_semantic_empty_store_degrades_to_tokens(self):
        # index.available True but the store was never indexed -> neighbours() returns [];
        # find_duplicates falls through to the deterministic token path and still finds dups.
        a = mk("X", body=_LONG, nid="a")
        b = mk("Y", body=_LONG_TWIN, nid="b")
        idx = SemanticIndex(StubEmbedder(dim=64))   # NOT indexed
        assert idx.available is True
        pairs = find_duplicates([a, b], index=idx)
        dups = [p for p in pairs if p.kind == "duplicate"]
        assert len(dups) == 1

    def test_fragment_runs_in_semantic_path(self):
        # The fragment path is index-independent: it still reports with a live index.
        long = mk("Full plan", body=_LONG, nid="long")
        frag = mk("Snippet", body="ship the beta release friday budget", nid="frag")
        idx = self._index([long, frag])
        pairs = find_duplicates([long, frag], index=idx)
        frags = [p for p in pairs if p.kind == "fragment"]
        assert len(frags) == 1
        assert frags[0].a_id == "long" and frags[0].b_id == "frag"


class TestNeighbours:
    def test_neighbours_unavailable_returns_empty(self):
        assert SemanticIndex().neighbours(mk("x", nid="x")) == []

    def test_neighbours_excludes_self_and_scores(self):
        notes = [mk("X", body=_LONG, nid="a"),
                 mk("Y", body=_LONG_TWIN, nid="b"),
                 mk("Z", body=_OTHER, nid="c")]
        idx = SemanticIndex(StubEmbedder(dim=64))
        idx.index(notes)
        out = idx.neighbours(notes[0], top_k=5)
        assert out, "expected neighbours from a populated store"
        assert all(nid != "a" for nid, _ in out)        # self excluded
        scores = [s for _, s in out]
        assert scores == sorted(scores, reverse=True)    # descending
        assert all(isinstance(s, float) for s in scores)

    def test_neighbours_empty_store(self):
        idx = SemanticIndex(StubEmbedder(dim=64))         # available but not indexed
        assert idx.neighbours(mk("x", body=_LONG, nid="x")) == []


class TestMergeNotes:
    def _store_with(self, tmp_path, a_body, b_body, a_tags=None, b_tags=None):
        store = NoteStore(tmp_path)
        a = store.create("Keep", body=a_body, tags=a_tags or [], color="violet", pinned=True)
        b = store.create("Drop", body=b_body, tags=b_tags or [])
        return store, a, b

    def test_merge_appends_body_with_separator(self, tmp_path):
        store, a, b = self._store_with(tmp_path, "first body", "second body")
        kept = merge_notes(store, a.id, b.id)
        assert "first body" in kept.body
        assert "second body" in kept.body
        assert MERGE_SEPARATOR in kept.body

    def test_merge_unions_tags_case_insensitive(self, tmp_path):
        store, a, b = self._store_with(tmp_path, "x", "y", a_tags=["work"], b_tags=["Work", "urgent"])
        kept = merge_notes(store, a.id, b.id)
        assert kept.tags == ["work", "urgent"]

    def test_merge_keeps_color_and_pin(self, tmp_path):
        store, a, b = self._store_with(tmp_path, "x", "y")
        assert a.color == "violet" and a.pinned is True
        kept = merge_notes(store, a.id, b.id)
        assert kept.color == "violet"
        assert kept.pinned is True

    def test_merge_soft_deletes_drop_not_purge(self, tmp_path):
        store, a, b = self._store_with(tmp_path, "x", "y")
        from pathlib import Path
        drop_path = b.path
        merge_notes(store, a.id, b.id)
        dropped = store.get(b.id)
        assert dropped is not None and dropped.deleted is True
        assert any(n.id == b.id for n in store.trash())   # in Trash
        assert Path(drop_path).exists()                   # file still on disk
        # Recoverable.
        restored = store.restore(b.id)
        assert restored is not None and restored.deleted is False

    def test_merge_returns_kept_note(self, tmp_path):
        store, a, b = self._store_with(tmp_path, "first", "second")
        kept = merge_notes(store, a.id, b.id)
        assert kept.id == a.id
        assert "first" in kept.body and "second" in kept.body

    def test_merge_self_raises(self, tmp_path):
        store, a, _ = self._store_with(tmp_path, "x", "y")
        with pytest.raises(ValueError):
            merge_notes(store, a.id, a.id)

    def test_merge_missing_raises(self, tmp_path):
        store, a, _ = self._store_with(tmp_path, "x", "y")
        with pytest.raises(ValueError):
            merge_notes(store, a.id, "nope")

    def test_merge_empty_drop_body(self, tmp_path):
        store, a, b = self._store_with(tmp_path, "kept body", "")
        kept = merge_notes(store, a.id, b.id)
        assert kept.body == "kept body"
        assert MERGE_SEPARATOR not in kept.body


class TestDefaultKeep:
    def test_default_keep_longer_body(self):
        a = mk("A", body="short", nid="a")
        b = mk("B", body="this is a much longer body of text", nid="b")
        assert default_keep(a, b) == "b"

    def test_default_keep_recency_tiebreak(self):
        # Equal-length bodies -> the more-recently-updated note is kept.
        a = mk("A", body="same", nid="a", updated=datetime(2026, 6, 1, 10, 0))
        b = mk("B", body="same", nid="b", updated=datetime(2026, 6, 19, 10, 0))
        assert default_keep(a, b) == "b"
