"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for keyword note search + ordering (pinned/recent-first).
Role:    Guards the Notes tab "Text" search and list ordering, and confirms the
         Phase-2 "Meaning" search remains a wired stub.

Test classes:
- TestKeywordSearch / TestOrdering / TestSemanticDegrade
- TestRelatedNotes - the no-model keyword/tag degrade of related_notes (note-linking)
============================================================
"""

from datetime import datetime

import pytest

from serenity.core.models import Note
from serenity.core.search import (
    keyword_search,
    order_notes,
    related_notes,
    semantic_search,
)


def mk(title, body="", tags=None, pinned=False, deleted=False, updated=None, nid=None):
    n = Note(
        title=title, body=body, tags=tags or [], pinned=pinned, deleted=deleted,
        updated=updated or datetime(2026, 6, 19, 10, 0),
    )
    if nid is not None:
        n.id = nid
    return n


class TestKeywordSearch:
    def test_title_match(self):
        notes = [mk("Q3 planning"), mk("Reading list")]
        out = keyword_search(notes, "planning")
        assert [n.title for n in out] == ["Q3 planning"]

    def test_body_match(self):
        notes = [mk("A", body="ship beta by friday"), mk("B", body="nothing")]
        out = keyword_search(notes, "beta")
        assert [n.title for n in out] == ["A"]

    def test_all_tokens_required(self):
        notes = [mk("A", body="alpha beta"), mk("B", body="alpha only")]
        out = keyword_search(notes, "alpha beta")
        assert [n.title for n in out] == ["A"]

    def test_title_outranks_body(self):
        title_hit = mk("budget review", updated=datetime(2026, 6, 1))
        body_hit = mk("Other", body="we discussed budget", updated=datetime(2026, 6, 18))
        out = keyword_search([body_hit, title_hit], "budget")
        assert out[0].title == "budget review"

    def test_deleted_excluded(self):
        notes = [mk("keep", body="x"), mk("trash", body="x", deleted=True)]
        out = keyword_search(notes, "x")
        assert [n.title for n in out] == ["keep"]

    def test_empty_query_returns_ordered_all(self):
        notes = [mk("A"), mk("B")]
        out = keyword_search(notes, "")
        assert len(out) == 2


class TestOrdering:
    def test_pinned_first(self):
        a = mk("A", updated=datetime(2026, 6, 19))
        b = mk("B-pinned", pinned=True, updated=datetime(2026, 6, 1))
        out = order_notes([a, b])
        assert out[0].title == "B-pinned"

    def test_recent_first_within_group(self):
        old = mk("old", updated=datetime(2026, 6, 1))
        new = mk("new", updated=datetime(2026, 6, 18))
        out = order_notes([old, new])
        assert [n.title for n in out] == ["new", "old"]


class TestSemanticDegrade:
    def test_semantic_no_index_falls_back_to_keyword(self):
        # With no index, Meaning mode degrades to keyword search byte-for-byte.
        notes = [mk("Q3 planning"), mk("Reading list")]
        out = semantic_search(notes, "planning")
        assert out == keyword_search(notes, "planning")

    def test_semantic_unavailable_index_falls_back_to_keyword(self):
        class _Unavailable:
            available = False

            def search(self, query, top_k=10):
                raise AssertionError("must not be called when unavailable")

        notes = [mk("A", body="alpha"), mk("B", body="beta")]
        out = semantic_search(notes, "alpha", index=_Unavailable())
        assert out == keyword_search(notes, "alpha")


class TestRelatedNotes:
    """The no-model keyword/tag degrade path of related_notes (index=None)."""

    def test_shared_tags_outrank_shared_tokens(self):
        # A shares a tag with B, and only body tokens with C -> B ranks before C.
        a = mk("A", body="alpha beta gamma", tags=["work"], nid="a")
        b = mk("B", body="nothing here at all", tags=["work"], nid="b")
        c = mk("C", body="alpha beta gamma", tags=["home"], nid="c")
        out = related_notes(a, [a, b, c])
        ids = [n.id for n in out]
        assert ids.index("b") < ids.index("c")

    def test_excludes_self(self):
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        b = mk("B", body="alpha beta", tags=["work"], nid="b")
        out = related_notes(a, [a, b])
        assert all(n.id != "a" for n in out)

    def test_excludes_deleted(self):
        a = mk("A", body="alpha beta gamma", tags=["work"], nid="a")
        gone = mk("B", body="alpha beta gamma", tags=["work"], deleted=True, nid="b")
        out = related_notes(a, [a, gone])
        assert all(n.id != "b" for n in out)

    def test_zero_overlap_dropped(self):
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        unrelated = mk("Z", body="zebra ostrich", tags=["zoo"], nid="z")
        out = related_notes(a, [a, unrelated])
        assert out == []

    def test_top_k_cap(self):
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        cands = [mk(f"C{i}", body="alpha beta", tags=["work"], nid=f"c{i}") for i in range(6)]
        out = related_notes(a, [a, *cands], top_k=4)
        assert len(out) == 4

    def test_deterministic_order(self):
        # Equal-score candidates ordered recent-first (_sort_ts); stable across runs.
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        older = mk("Old", body="alpha beta", tags=["work"],
                   updated=datetime(2026, 6, 1), nid="old")
        newer = mk("New", body="alpha beta", tags=["work"],
                   updated=datetime(2026, 6, 18), nid="new")
        first = [n.id for n in related_notes(a, [a, older, newer])]
        second = [n.id for n in related_notes(a, [a, older, newer])]
        assert first == second
        assert first.index("new") < first.index("old")

    def test_empty_notes_returns_empty(self):
        a = mk("A", body="alpha", tags=["work"], nid="a")
        assert related_notes(a, []) == []

    def test_index_none_uses_fallback(self):
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        b = mk("B", body="alpha beta", tags=["work"], nid="b")
        notes = [a, b]
        assert related_notes(a, notes, index=None) == related_notes(a, notes)


class TestRelatedOverFetch:
    """Phase C QA (criticizer #1/#7): the full-corpus index must be over-fetched so a
    context-filtered candidate that ranks past top_k in the FULL ranking is still returned."""

    class _FakeIndex:
        available = True

        def __init__(self, ranking, pop):
            self._ranking, self._pop, self.queried = ranking, pop, []

        def population(self):
            return self._pop

        def related(self, note, top_k=5):
            self.queried.append(top_k)
            return [Note(id=i) for i in self._ranking[:top_k]]

    def test_related_overfetches_to_population(self):
        # Full corpus ranking puts 3 other-context notes ahead of the one in-context match.
        idx = self._FakeIndex(["o1", "o2", "o3", "inctx"], pop=4)
        inctx = Note(id="inctx", title="keep me")
        note = Note(id="src", title="src")
        # candidates = only the in-context note (the other-context ones are filtered out upstream)
        out = related_notes(note, [inctx], index=idx, top_k=2)
        assert [n.id for n in out] == ["inctx"]     # not crowded out
        assert idx.queried == [4]                    # queried the FULL corpus, not top_k=2

    def test_related_truncates_to_top_k(self):
        # When MORE than top_k candidates survive re-projection, the index path must still
        # cut to top_k (guards the `if len(out) >= top_k: break` truncation).
        idx = self._FakeIndex(["c0", "c1", "c2", "c3"], pop=4)
        cands = [Note(id=f"c{i}", title=f"c{i}") for i in range(4)]
        out = related_notes(Note(id="src"), cands, index=idx, top_k=2)
        assert [n.id for n in out] == ["c0", "c1"]   # not all 4
