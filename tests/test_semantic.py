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
- TestModelRegistry - resolve_model presets / preset-id / custom / empty (dim + e5 prefix)
- TestPrefixConditional - FastEmbedBackend prepends e5 prefixes ONLY for e5 models, plus
  dim-detection from the first embedding for a custom id (fastembed monkeypatched - no load)
- TestStoreInvalidation - VectorStore store_meta wipe-on-mismatch (dim/model) vs survive
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
    DEFAULT_MODEL_KEY,
    MODEL_REGISTRY,
    FastEmbedBackend,
    StubEmbedder,
    VectorStore,
    embed_text,
    note_hash,
    resolve_model,
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

    def test_query_scores_are_cosine(self):
        # Contract lock (DEDUP-1): query() must return TRUE cosine similarity - ~1.0 for an
        # identical unit vector and ~0.0 for an orthogonal one - so absolute thresholds like
        # dedup.DUP_COSINE mean the same thing on BOTH backends. Runs on the pure-Python path
        # here, but guards the contract the sqlite-vec path now also honours
        # (distance_metric=cosine + 1-distance conversion).
        s = VectorStore(db_path=None, dim=2)
        s.upsert("same", "h1", [1.0, 0.0])      # identical to the query (cosine 1.0)
        s.upsert("orth", "h2", [0.0, 1.0])      # orthogonal to the query (cosine 0.0)
        scores = {nid: sc for nid, sc in s.query([1.0, 0.0], top_k=2)}
        assert abs(scores["same"] - 1.0) < 1e-6
        assert abs(scores["orth"] - 0.0) < 1e-6
        s.close()


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

    def test_zero_dim_embedder_degrades_to_keyword(self):
        # A custom fastembed id resolves to dim 0; if the model fails to load the probe
        # yields nothing and dim stays 0 while the backend still advertises available=True.
        # SemanticIndex must NOT open a dim-0 store - it must degrade to keyword search.
        class ZeroDimEmbedder:
            name = "some/broken-custom-id"
            dim = 0
            available = True

            def ensure_dim(self):
                return 0                      # model never loaded -> no dim learned

            def embed_documents(self, texts):
                return []

            def embed_query(self, text):
                return []

        idx = SemanticIndex(embedder=ZeroDimEmbedder(), db_path=None)
        idx.index([mk("apple", nid="a")])     # must not build a dim-0 store / not raise
        assert idx._store is None
        assert idx.available is False         # degraded to keyword search
        assert idx.search("apple") == []

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

    def test_related_notes_partial_store_reflects_live_vault(self):
        # JOB4-CORR-1 regression: a store indexed with [a,b] then queried for `a` against a
        # live list that ALSO contains a newer note `c` must NOT silently drop `c`. The caller
        # is expected to index() first (as the UI now does on expand); once it does, c surfaces.
        a = mk("apple banana cherry", nid="a")
        b = mk("apple", nid="b")
        idx = self._idx([a, b])                              # store knows only a, b
        c = mk("apple banana cherry date", nid="c")          # newer, most-related to a
        live = [a, b, c]
        # Without re-indexing, the stale store cannot know about c (documents the hazard).
        stale = related_notes(a, live, index=idx, top_k=4)
        assert all(n.id != "c" for n in stale)
        # Index-first (the contract the UI honors) -> c is surfaced as the top neighbour.
        idx.index(live)
        fresh = related_notes(a, live, index=idx, top_k=4)
        assert "c" in {n.id for n in fresh}
        assert fresh[0].id == "c"

    def test_index_related_top_k_clamped_low(self):
        # TC-2: the index path mirrors search() - top_k<=0 clamps to at least 1 at the index
        # layer (never the whole corpus). related_notes guards above this, but the index
        # method itself keeps the documented sibling-of-search clamp.
        notes = [
            mk("alpha beta gamma", nid="src"),
            mk("alpha beta", nid="other"),
            mk("alpha", nid="low"),
        ]
        idx = self._idx(notes)
        assert len(idx.related(notes[0], top_k=0)) == 1
        assert len(idx.related(notes[0], top_k=-1)) == 1

    def test_related_notes_top_k_zero_unified_empty(self):
        # JOB4-CORR-2: both paths agree at top_k<=0 - related_notes returns [] whether or not
        # an index is present, even though the underlying index.related clamps to >=1.
        a = mk("A", body="alpha beta", tags=["work"], nid="a")
        b = mk("B", body="alpha beta", tags=["work"], nid="b")
        notes = [a, b]
        idx = self._idx(notes)
        assert related_notes(a, notes, index=idx, top_k=0) == []
        assert related_notes(a, notes, index=None, top_k=0) == []
        assert related_notes(a, notes, index=idx, top_k=-3) == []
        assert related_notes(a, notes, index=None, top_k=-3) == []


class TestRelatedFallback:
    """The no-model keyword/tag related ranking (the path THIS env always takes)."""

    def test_stopword_only_overlap_is_not_related(self):
        # ux-1: notes sharing only function words ("the", "to", "i", "need"...) must NOT be
        # judged related - a shared content word, not a shared "the", earns a chip.
        groceries = mk("Buy groceries", body="i need to get milk and bread", nid="g")
        car = mk("Fix the car", body="i need to get the car to the shop", nid="c")
        out = _related_fallback(groceries, [car], top_k=4)
        assert out == []

    def test_content_word_overlap_is_related(self):
        # A genuine shared content word ("ocean") still surfaces as related.
        a = mk("Beach trip", body="ocean waves sand", nid="a")
        b = mk("Diving", body="ocean reef coral", nid="b")
        out = _related_fallback(a, [b], top_k=4)
        assert [n.id for n in out] == ["b"]

    def test_shared_tag_still_relates_without_content_overlap(self):
        # The +3.0 shared-tag signal stands on its own (tags are deliberate user grouping),
        # even when bodies share only stop-words.
        a = mk("One", body="i need it", tags=["project-x"], nid="a")
        b = mk("Two", body="to do the thing", tags=["project-x"], nid="b")
        out = _related_fallback(a, [b], top_k=4)
        assert [n.id for n in out] == ["b"]


class TestModelRegistry:
    """resolve_model() is the single source of truth turning a settings value (preset key,
    a preset's fastembed id, a raw custom id, or empty/None) into the backend's
    (fastembed_id, dim, needs_e5_prefix). The curated presets carry a known dim + prefix
    flag; a custom id gets dim 0 (detect-later) and e5-prefix only if 'e5' is in the id."""

    def test_default_key_constant(self):
        assert DEFAULT_MODEL_KEY == "mpnet"
        assert MODEL_REGISTRY["mpnet"]["dim"] == 768

    def test_preset_keys(self):
        # The fastembed ids carry the "sentence-transformers/" namespace - fastembed
        # rejects the bare names (verified against TextEmbedding.list_supported_models).
        assert resolve_model("mpnet") == (
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", 768, False)
        assert resolve_model("e5-large") == (
            "intfloat/multilingual-e5-large", 1024, True)
        assert resolve_model("minilm") == (
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384, False)

    def test_empty_and_none_default_to_mpnet(self):
        mpnet = ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", 768, False)
        assert resolve_model("") == mpnet
        assert resolve_model(None) == mpnet
        assert resolve_model("   ") == mpnet     # whitespace-only -> default

    def test_preset_id_not_key(self):
        # Passing a preset's fastembed id (not its key) still resolves to its dim/prefix.
        assert resolve_model("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") == (
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384, False)

    def test_custom_id_unknown_dim_no_prefix(self):
        # An unknown custom id: dim 0 (detect from first embedding), no e5 prefix.
        assert resolve_model("some/custom-model") == ("some/custom-model", 0, False)

    def test_custom_e5_id_gets_prefix(self):
        # 'e5' in the id (case-insensitive) -> needs_e5_prefix True even for a custom id.
        assert resolve_model("acme/my-e5-thing") == ("acme/my-e5-thing", 0, True)
        assert resolve_model("acme/My-E5-Thing") == ("acme/My-E5-Thing", 0, True)


class _Recorder:
    """A fake fastembed model: records the exact texts it is asked to embed and returns a
    deterministic fixed-dim vector, so tests can assert on the prefixing without a load."""

    def __init__(self, dim: int = 5) -> None:
        self.seen: list[str] = []
        self._dim = dim

    def embed(self, texts):
        for t in texts:
            self.seen.append(t)
            yield [1.0] + [0.0] * (self._dim - 1)


class TestPrefixConditional:
    """FastEmbedBackend applies e5's 'passage:'/'query:' prefixes ONLY for e5-family models;
    mpnet/MiniLM/custom-non-e5 get RAW text. fastembed is monkeypatched (via _model) so no
    real model loads or downloads. Also covers dim-detection for a custom id (dim 0 ->
    len of the first embedding)."""

    def test_e5_model_prefixes(self, monkeypatch):
        rec = _Recorder()
        be = FastEmbedBackend(model="e5-large")
        monkeypatch.setattr(be, "_model", lambda: rec)
        be.embed_documents(["hello"])
        be.embed_query("q")
        assert "passage: hello" in rec.seen
        assert "query: q" in rec.seen

    def test_mpnet_model_no_prefix(self, monkeypatch):
        rec = _Recorder()
        be = FastEmbedBackend(model="mpnet")
        monkeypatch.setattr(be, "_model", lambda: rec)
        be.embed_documents(["hello"])
        be.embed_query("q")
        assert rec.seen == ["hello", "q"]            # RAW text, no prefixes
        assert "passage: hello" not in rec.seen

    def test_custom_id_detects_dim(self, monkeypatch):
        # A custom id declares dim 0; after the first embed the backend learns its dim.
        rec = _Recorder(dim=7)
        be = FastEmbedBackend(model="some/custom-model")
        assert be.dim == 0
        monkeypatch.setattr(be, "_model", lambda: rec)
        vec = be.embed_query("anything")
        assert len(vec) == 7
        assert be.dim == 7
        assert rec.seen == ["anything"]              # custom non-e5 -> RAW text

    def test_ensure_dim_probes_only_when_unknown(self, monkeypatch):
        # Preset dim is known -> ensure_dim is a no-op (no probe fires).
        be = FastEmbedBackend(model="mpnet")
        called = []
        monkeypatch.setattr(be, "embed_query", lambda t: called.append(t) or [])
        assert be.ensure_dim() == 768
        assert called == []
        # Custom id dim 0 -> ensure_dim fires one probe.
        rec = _Recorder(dim=9)
        be2 = FastEmbedBackend(model="some/custom-model")
        monkeypatch.setattr(be2, "_model", lambda: rec)
        assert be2.ensure_dim() == 9
        assert rec.seen == ["dim probe"]


class TestStoreInvalidation:
    """A model change shifts the vector dim; mixing persisted vectors with a new model would
    corrupt results. The VectorStore store_meta identity row catches a model/dim mismatch on
    open and wipes + rebuilds the store empty (the next index() re-embeds from the notes).
    Same identity -> rows survive. Uses a real on-disk db so the meta persists across opens."""

    def test_dim_change_wipes(self, tmp_path):
        p = tmp_path / "s.sqlite"
        s1 = VectorStore(db_path=p, dim=3, model="A")
        s1.upsert("a", "h", [1.0, 0.0, 0.0])
        assert s1.hashes() == {"a": "h"}
        s1.close()
        # Reopen with a different dim + model -> wiped (rebuilt empty), NOT corrupt.
        s2 = VectorStore(db_path=p, dim=4, model="B")
        assert s2.hashes() == {}
        s2.upsert("a", "h", [1.0, 0.0, 0.0, 0.0])    # new dim accepted
        assert s2.hashes() == {"a": "h"}
        s2.close()

    def test_same_identity_survives(self, tmp_path):
        p = tmp_path / "s.sqlite"
        s1 = VectorStore(db_path=p, dim=3, model="A")
        s1.upsert("a", "h", [1.0, 0.0, 0.0])
        s1.close()
        s2 = VectorStore(db_path=p, dim=3, model="A")
        assert s2.hashes() == {"a": "h"}             # same model + dim -> no wipe
        s2.close()

    def test_model_only_change_same_dim_wipes(self, tmp_path):
        # Same dim but a different model id (e.g. broken e5-base 768d -> mpnet 768d) MUST
        # still wipe - this is exactly why we store the model id, not just the dim.
        p = tmp_path / "s.sqlite"
        s1 = VectorStore(db_path=p, dim=768, model="intfloat/multilingual-e5-base")
        s1.upsert("a", "h", [0.0] * 768)
        s1.close()
        s2 = VectorStore(
            db_path=p, dim=768, model="paraphrase-multilingual-mpnet-base-v2")
        assert s2.hashes() == {}
        s2.close()

    def test_fresh_db_is_noop(self, tmp_path):
        # First open records identity and keeps any (here: none) rows - no spurious wipe.
        p = tmp_path / "s.sqlite"
        s = VectorStore(db_path=p, dim=3, model="A")
        s.upsert("a", "h", [1.0, 0.0, 0.0])
        assert s.hashes() == {"a": "h"}
        s.close()
