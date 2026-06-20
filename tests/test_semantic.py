"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Headless unit tests for the semantic ('Meaning') search engine + its wiring.
Role:    Exercises core.semantic (StubEmbedder + the pure-Python cosine VectorStore) and
         the rewired SemanticIndex / core.search.semantic_search WITHOUT network or heavy
         deps (fastembed / sqlite-vec are not installed here). Guards: embedder determinism
         + L2-normalization, search ranking, content-hash incrementality (unchanged notes
         are not re-embedded), invalidation on change/delete, the degrade-to-keyword path
         when the index is unavailable/empty, and edge cases (empty query/index, top_k
         clamp, dim mismatch, unicode/German tokens).

Test classes:
- TestStubEmbedder - determinism, L2 norm, fixed dim, distinct vectors
- TestVectorStore - python backend, round-trip, dim mismatch, top_k clamp
- TestEmbedText - canonical text + hashing (whitespace, unicode)
- TestSemanticIndex - ranking, hash-skip, invalidation, edge cases
- TestSemanticSearchWiring - delegate vs degrade-to-keyword
- TestRelated - SemanticIndex.related (note-linking) + related_notes reproject/degrade
============================================================
"""

import math

from serenity.core.models import Note
from serenity.core.search import (
    _related_fallback,
    keyword_search,
    related_notes,
    semantic_search,
)
from serenity.core.phase2_stubs import SemanticIndex
from serenity.core.semantic import (
    StubEmbedder,
    VectorStore,
    embed_text,
    note_hash,
)


def mk(title, body="", tags=None, deleted=False, nid=None):
    n = Note(title=title, body=body, tags=tags or [], deleted=deleted)
    if nid is not None:
        n.id = nid
    return n


class CountingEmbedder:
    """Wraps a StubEmbedder to record how many documents each embed_documents call saw.

    Lets the incrementality tests assert that an unchanged vault re-embeds NOTHING and a
    one-note edit re-embeds exactly one note."""

    name = "stub"
    available = True

    def __init__(self, dim: int = 16) -> None:
        self._inner = StubEmbedder(dim=dim)
        self.dim = self._inner.dim
        self.doc_batches: list[list[str]] = []

    def embed_documents(self, texts):
        self.doc_batches.append(list(texts))
        return self._inner.embed_documents(texts)

    def embed_query(self, text):
        return self._inner.embed_query(text)


# --------------------------------------------------------------------------- #


class TestStubEmbedder:
    def test_deterministic(self):
        e = StubEmbedder()
        a = e.embed_query("the quick brown fox")
        b = e.embed_query("the quick brown fox")
        assert a == b

    def test_l2_normalized(self):
        e = StubEmbedder()
        v = e.embed_query("hello world meaning search")
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)

    def test_fixed_dim(self):
        e = StubEmbedder(dim=24)
        assert e.dim == 24
        assert len(e.embed_query("anything")) == 24
        docs = e.embed_documents(["one", "two"])
        assert all(len(v) == 24 for v in docs)

    def test_different_texts_differ(self):
        e = StubEmbedder()
        assert e.embed_query("alpha beta gamma") != e.embed_query("delta epsilon zeta")

    def test_empty_text_is_zero_vector(self):
        e = StubEmbedder()
        v = e.embed_query("")
        assert v == [0.0] * e.dim


class TestVectorStore:
    def test_python_backend_in_this_env(self):
        # sqlite-vec is not installed here, so the store must pick the pure-Python path.
        s = VectorStore(db_path=None, dim=4)
        assert s.backend == "python"
        s.close()

    def test_upsert_query_roundtrip(self):
        s = VectorStore(db_path=None, dim=3)
        s.upsert("a", "h1", [1.0, 0.0, 0.0])
        s.upsert("b", "h2", [0.0, 1.0, 0.0])
        out = s.query([1.0, 0.0, 0.0], top_k=2)
        assert out[0][0] == "a"
        assert out[0][1] > out[1][1]
        s.close()

    def test_needs_embed_and_hashes(self):
        s = VectorStore(db_path=None, dim=2)
        assert s.needs_embed("a", "h1") is True
        s.upsert("a", "h1", [1.0, 0.0])
        assert s.needs_embed("a", "h1") is False     # same hash -> cache hit
        assert s.needs_embed("a", "h2") is True       # changed hash -> re-embed
        assert s.hashes() == {"a": "h1"}
        s.close()

    def test_upsert_overwrites_on_change(self):
        s = VectorStore(db_path=None, dim=2)
        s.upsert("a", "h1", [1.0, 0.0])
        s.upsert("a", "h2", [0.0, 1.0])
        assert s.hashes() == {"a": "h2"}              # one row, new hash
        s.close()

    def test_prune_drops_gone_notes(self):
        s = VectorStore(db_path=None, dim=2)
        s.upsert("a", "h1", [1.0, 0.0])
        s.upsert("b", "h2", [0.0, 1.0])
        s.prune(keep_ids={"a"})
        assert set(s.hashes()) == {"a"}
        assert all(nid == "a" for nid, _ in s.query([1.0, 0.0], top_k=10))
        s.close()

    def test_dim_mismatch_rejected(self):
        s = VectorStore(db_path=None, dim=3)
        try:
            s.upsert("a", "h1", [1.0, 0.0])           # wrong dim
            assert False, "expected ValueError"
        except ValueError:
            pass
        s.close()

    def test_top_k_clamp_and_overflow(self):
        s = VectorStore(db_path=None, dim=2)
        s.upsert("a", "h1", [1.0, 0.0])
        assert s.query([1.0, 0.0], top_k=0) == []     # <= 0 -> empty
        assert s.query([1.0, 0.0], top_k=-5) == []
        assert len(s.query([1.0, 0.0], top_k=99)) == 1  # > corpus -> all


class TestEmbedText:
    def test_canonical_layout(self):
        n = mk("Title", body="Body text", tags=["x", "y"])
        assert embed_text(n) == "Title x y Body text"

    def test_whitespace_normalized(self):
        a = mk("Same", body="one   two\n\nthree")
        b = mk("Same", body="one two three")
        assert embed_text(a) == embed_text(b)
        assert note_hash(a) == note_hash(b)

    def test_hash_changes_on_edit(self):
        a = mk("T", body="alpha")
        b = mk("T", body="beta")
        assert note_hash(a) != note_hash(b)

    def test_unicode_german_survives(self):
        n = mk("Grüße", body="Über straße fließt Wasser - schön", tags=["übung"])
        txt = embed_text(n)
        assert "Grüße" in txt and "straße" in txt and "übung" in txt
        # Hash is stable + token vector is non-zero for German text.
        assert note_hash(n) == note_hash(n)
        v = StubEmbedder().embed_query(txt)
        assert any(x != 0.0 for x in v)


class TestSemanticIndex:
    def test_no_embedder_unavailable_and_empty(self):
        idx = SemanticIndex()
        assert idx.available is False
        assert idx.search("anything") == []
        idx.index([mk("A")])         # no-op, must not raise

    def test_stub_embedder_flips_available(self):
        idx = SemanticIndex(embedder=StubEmbedder(), db_path=None)
        assert idx.available is True

    def test_ranking_most_overlap_first(self):
        # Bag-of-token-hash vectors make cosine overlap monotonic, so the note sharing the
        # most query tokens ranks first.
        idx = SemanticIndex(embedder=StubEmbedder(dim=64), db_path=None)
        notes = [
            mk("apple banana cherry", nid="best"),       # 3 query tokens
            mk("apple banana", nid="mid"),               # 2 query tokens
            mk("apple", nid="low"),                       # 1 query token
            mk("zebra ostrich walrus", nid="none"),       # 0 query tokens
        ]
        idx.index(notes)
        ranked = idx.search("apple banana cherry", top_k=4)
        ids = [n.id for n in ranked]
        assert ids[0] == "best"
        assert ids.index("best") < ids.index("mid") < ids.index("low")

    def test_hash_skip_no_reembed_unchanged(self):
        emb = CountingEmbedder(dim=32)
        idx = SemanticIndex(embedder=emb, db_path=None)
        notes = [mk("A", body="alpha", nid="a"), mk("B", body="beta", nid="b")]
        idx.index(notes)
        assert sorted(emb.doc_batches[0]) == sorted([embed_text(n) for n in notes])
        # Second index of the SAME notes -> nothing re-embedded.
        idx.index(notes)
        assert len(emb.doc_batches) == 1 or emb.doc_batches[1] == []

    def test_one_edit_reembeds_exactly_one(self):
        emb = CountingEmbedder(dim=32)
        idx = SemanticIndex(embedder=emb, db_path=None)
        notes = [mk("A", body="alpha", nid="a"), mk("B", body="beta", nid="b")]
        idx.index(notes)
        first_calls = len(emb.doc_batches)
        notes[0].body = "alpha changed"
        idx.index(notes)
        last = emb.doc_batches[-1]
        assert last == [embed_text(notes[0])]
        assert len(emb.doc_batches) == first_calls + 1
        # The stored hash for the edited note was updated.
        store = idx._store
        assert store.hashes()["a"] == note_hash(notes[0])

    def test_invalidation_on_delete(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=32), db_path=None)
        notes = [mk("A", body="alpha", nid="a"), mk("B", body="beta", nid="b")]
        idx.index(notes)
        assert set(idx._store.hashes()) == {"a", "b"}
        # Re-index with one note marked deleted -> it is pruned and never returned.
        notes[1].deleted = True
        idx.index(notes)
        assert set(idx._store.hashes()) == {"a"}
        ranked = idx.search("beta", top_k=10)
        assert all(n.id != "b" for n in ranked)

    def test_deleted_notes_excluded_from_index(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=32), db_path=None)
        notes = [mk("A", body="alpha", nid="a"), mk("D", body="alpha", nid="d", deleted=True)]
        idx.index(notes)
        assert set(idx._store.hashes()) == {"a"}

    def test_empty_query_returns_empty(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=16), db_path=None)
        idx.index([mk("A", body="alpha", nid="a")])
        assert idx.search("") == []
        assert idx.search("   ") == []

    def test_empty_index_search_empty(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=16), db_path=None)
        idx.index([])
        assert idx.search("alpha") == []

    def test_top_k_clamped_low(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=32), db_path=None)
        idx.index([mk("A", body="alpha", nid="a"), mk("B", body="beta", nid="b")])
        # top_k <= 0 is clamped to at least 1 (never raises, never returns the whole corpus).
        out = idx.search("alpha", top_k=0)
        assert len(out) == 1

    def test_top_k_larger_than_corpus(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=32), db_path=None)
        notes = [mk("A", body="alpha", nid="a"), mk("B", body="alpha", nid="b")]
        idx.index(notes)
        out = idx.search("alpha", top_k=99)
        assert len(out) == 2

    def test_german_tokens_searchable(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=64), db_path=None)
        notes = [
            mk("Einkauf", body="Käse Brötchen für die Woche", nid="de"),
            mk("Travel", body="flight booking next month", nid="en"),
        ]
        idx.index(notes)
        ranked = idx.search("Brötchen Käse", top_k=2)
        assert ranked[0].id == "de"


class TestSemanticSearchWiring:
    def test_index_none_degrades_to_keyword(self):
        notes = [mk("Q3 planning"), mk("Reading list")]
        assert semantic_search(notes, "planning") == keyword_search(notes, "planning")

    def test_unavailable_index_degrades_to_keyword(self):
        idx = SemanticIndex()             # no embedder -> available False
        notes = [mk("A", body="alpha"), mk("B", body="beta")]
        assert semantic_search(notes, "alpha", index=idx) == keyword_search(notes, "alpha")

    def test_empty_index_degrades_to_keyword(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=16), db_path=None)
        # Index never populated -> search returns [] -> caller falls back to keyword.
        notes = [mk("A", body="alpha"), mk("B", body="beta")]
        assert semantic_search(notes, "alpha", index=idx) == keyword_search(notes, "alpha")

    def test_available_index_returns_ranked_active_notes(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=64), db_path=None)
        notes = [
            mk("apple banana cherry", nid="best"),
            mk("apple", nid="low"),
            mk("zebra", nid="none"),
        ]
        idx.index(notes)
        out = semantic_search(notes, "apple banana cherry", index=idx)
        assert out[0].id == "best"
        # Re-projected onto the live notes list: returns real Note objects from `notes`.
        assert all(n in notes for n in out)

    def test_ranked_ids_reprojected_filter_deleted(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=64), db_path=None)
        live = [mk("apple banana", nid="a"), mk("apple", nid="b")]
        idx.index(live)
        # Mark one deleted in the live list passed to semantic_search; it must be filtered.
        live[0].deleted = True
        out = semantic_search(live, "apple banana", index=idx)
        assert all(n.id != "a" for n in out)


class TestRelated:
    def _idx(self, notes, dim=64):
        idx = SemanticIndex(embedder=StubEmbedder(dim=dim), db_path=None)
        idx.index(notes)
        return idx

    def test_index_related_ranks_similar_first(self):
        notes = [
            mk("apple banana cherry", nid="src"),
            mk("apple banana", nid="mid"),
            mk("apple", nid="low"),
            mk("zebra ostrich walrus", nid="none"),
        ]
        idx = self._idx(notes)
        src = notes[0]
        ranked = idx.related(src, top_k=3)
        ids = [n.id for n in ranked]
        assert "src" not in ids                                  # source excluded
        assert ids.index("mid") < ids.index("low")              # more overlap ranks higher

    def test_index_related_excludes_self_even_when_nearest(self):
        # The source note is its own nearest vector; related() must still drop it.
        notes = [mk("alpha beta gamma", nid="src"), mk("alpha beta", nid="other")]
        idx = self._idx(notes)
        ranked = idx.related(notes[0], top_k=5)
        assert all(n.id != "src" for n in ranked)
        assert any(n.id == "other" for n in ranked)

    def test_index_related_empty_store(self):
        idx = SemanticIndex(embedder=StubEmbedder(dim=32), db_path=None)
        idx.index([])
        assert idx.related(mk("alpha", nid="a"), top_k=5) == []

    def test_index_related_no_embedder(self):
        idx = SemanticIndex()                       # no embedder -> unavailable
        assert idx.related(mk("alpha", nid="a")) == []

    def test_index_related_no_id_returns_empty(self):
        notes = [mk("alpha beta", nid="a"), mk("alpha", nid="b")]
        idx = self._idx(notes)
        no_id = Note(title="floating")
        no_id.id = ""
        assert idx.related(no_id, top_k=5) == []

    def test_related_notes_available_reprojects_onto_live(self):
        live = [
            mk("apple banana cherry", nid="src"),
            mk("apple banana", nid="mid"),
            mk("apple", nid="low"),
        ]
        idx = self._idx(live)
        out = related_notes(live[0], live, index=idx, top_k=3)
        assert out                                              # non-empty
        assert all(n in live for n in out)                     # real Note objects from live
        assert all(n.id != "src" for n in out)                 # source excluded

    def test_related_notes_reproject_filters_deleted(self):
        live = [
            mk("apple banana cherry", nid="src"),
            mk("apple banana", nid="mid"),
            mk("apple", nid="low"),
        ]
        idx = self._idx(live)
        # Mark a would-be neighbour deleted in the live list -> filtered on reproject.
        live[1].deleted = True
        out = related_notes(live[0], live, index=idx, top_k=3)
        assert all(n.id != "mid" for n in out)

    def test_related_notes_unavailable_degrades_to_fallback(self):
        idx = SemanticIndex()                       # unavailable
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        b = mk("B", body="alpha beta", tags=["work"], nid="b")
        notes = [a, b]
        assert related_notes(a, notes, index=idx) == _related_fallback(a, notes, 5)

    def test_related_notes_empty_index_degrades(self):
        # Indexed-but-empty store -> index.related returns [] -> falls back deterministically.
        idx = SemanticIndex(embedder=StubEmbedder(dim=32), db_path=None)
        idx.index([])
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        b = mk("B", body="alpha beta", tags=["work"], nid="b")
        notes = [a, b]
        out = related_notes(a, notes, index=idx)
        assert out == _related_fallback(a, notes, 5)
        assert all(n.id != "a" for n in out)
