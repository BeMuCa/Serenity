"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for keyword note search + ordering (pinned/recent-first).
Role:    Guards the Notes tab "Text" search and list ordering, and confirms the
         Phase-2 "Meaning" search remains a wired stub.

Test classes:
- TestKeywordSearch / TestOrdering / TestSemanticStub
============================================================
"""

from datetime import datetime

import pytest

from serenity.core.models import Note
from serenity.core.search import keyword_search, order_notes, semantic_search


def mk(title, body="", tags=None, pinned=False, deleted=False, updated=None):
    return Note(
        title=title, body=body, tags=tags or [], pinned=pinned, deleted=deleted,
        updated=updated or datetime(2026, 6, 19, 10, 0),
    )


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


class TestSemanticStub:
    def test_semantic_is_not_implemented(self):
        with pytest.raises(NotImplementedError):
            semantic_search([mk("A")], "anything")
