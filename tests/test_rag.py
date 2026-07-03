"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for Ask-Your-Vault RAG + the warm-cache (core.rag, Job 13).
Role:    Guards the RAG contract headless with a StubLLM + a StubEmbedder-backed
         SemanticIndex (no heavy deps, no model downloads):
         - answer_question returns a grounded answer + the source note ids it cited;
         - it degrades to sources-only (answer None) when the LLM is None / unavailable /
           errors / returns empty, so the UI always has notes to show;
         - it uses semantic retrieval when an index is available, and keyword retrieval when
           the index is None / unavailable;
         - WarmCache: a hit (same Q + unchanged sources serves WITHOUT calling the LLM again),
           a miss (a new Q computes live), and invalidation (a cited note is edited -> the
           source hash changes -> the next ask recomputes), plus precompute().

Test classes:
- TestAnswerQuestion - retrieval + grounded answer + the degrade axes
- TestSourcesHash - the cache invalidation key is stable + content-sensitive
- TestWarmCache - precompute / hit / miss / invalidate
============================================================
"""

from datetime import datetime

from serenity.core.models import Note
from serenity.core.phase2_stubs import SemanticIndex
from serenity.core.rag import (
    RagResult,
    WarmCache,
    answer_question,
    normalize_question,
    sources_hash,
)
from serenity.core.semantic import StubEmbedder


# --------------------------------------------------------------------------- #
# Test doubles + fixtures.
# --------------------------------------------------------------------------- #
class _CountingLLM:
    """A StubLLM-like engine that ECHOES its prompt and counts generate() calls.

    Lets a test both assert the answer is grounded (it contains the echoed context) and that a
    warm-cache HIT does NOT call the model again (calls stays put)."""

    name = "counting"

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.calls = 0
        self.last_prompt = None
        self.last_system = None

    def generate(self, prompt, system=None, max_tokens=256):
        self.calls += 1
        self.last_prompt = prompt
        self.last_system = system
        return f"answer: {prompt}"


class _BoomLLM:
    """An available engine whose generate() raises - RAG must degrade, not crash."""

    name = "boom"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        raise RuntimeError("inference exploded")


class _EmptyLLM:
    """An available engine that returns an empty string - treated as no answer."""

    name = "empty"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        return "   "


def _notes():
    """Three notes with distinct vocabularies so retrieval ranking is predictable."""
    now = datetime(2026, 6, 20, 10, 0, 0)
    return [
        Note(id="n1", title="Airport parking", body="I parked in level 3 row D at the airport",
             created=now, updated=now),
        Note(id="n2", title="Tax report", body="invoice deadline accountant numbers",
             created=now, updated=now),
        Note(id="n3", title="Vacation plan", body="beach flight hotel sunset ocean",
             created=now, updated=now),
    ]


def _index():
    """A live SemanticIndex over a StubEmbedder (no model download, deterministic ranking)."""
    return SemanticIndex(embedder=StubEmbedder(dim=64))


# --------------------------------------------------------------------------- #
# answer_question
# --------------------------------------------------------------------------- #
class TestAnswerQuestion:
    def test_answer_and_citations_with_stub_llm(self):
        notes = _notes()
        llm = _CountingLLM()
        res = answer_question("Where did I park at the airport?", notes,
                              index=None, llm=llm, top_k=2)
        assert isinstance(res, RagResult)
        assert res.answer is not None
        assert res.sources                              # at least one citation
        # The most relevant note (airport parking) is among the cited sources.
        assert "n1" in res.sources
        # Grounded: the prompt the model saw carried the cited note's content, and a system
        # instruction constrained it to the context.
        assert "level 3 row D" in llm.last_prompt
        assert llm.last_system is not None
        assert llm.calls == 1

    def test_semantic_retrieval_when_index_available(self):
        notes = _notes()
        index = _index()
        index.index(notes)
        llm = _CountingLLM()
        res = answer_question("beach ocean flight hotel", notes,
                              index=index, llm=llm, top_k=1)
        # The vacation note has the most token overlap -> ranked first by the stub embedder.
        assert res.sources == ["n3"]

    def test_keyword_retrieval_when_index_unavailable(self):
        notes = _notes()
        # A bare SemanticIndex reports available=False -> keyword retrieval must still work.
        index = SemanticIndex()
        assert index.available is False
        llm = _CountingLLM()
        res = answer_question("accountant invoice", notes,
                              index=index, llm=llm, top_k=3)
        assert "n2" in res.sources                      # keyword match on the tax note

    def test_keyword_retrieval_when_index_none(self):
        notes = _notes()
        res = answer_question("accountant", notes, index=None,
                              llm=_CountingLLM(), top_k=3)
        assert "n2" in res.sources

    def test_degrades_to_sources_only_when_llm_none(self):
        notes = _notes()
        res = answer_question("Where did I park?", notes, index=None, llm=None, top_k=2)
        assert res.answer is None                       # no synthesized answer
        assert res.sources                              # but the retrieved notes are returned
        assert "n1" in res.sources

    def test_degrades_when_llm_unavailable(self):
        notes = _notes()
        llm = _CountingLLM(available=False)
        res = answer_question("airport", notes, index=None, llm=llm, top_k=2)
        assert res.answer is None
        assert res.sources
        assert llm.calls == 0                           # an unavailable engine is never called

    def test_degrades_when_llm_raises(self):
        notes = _notes()
        res = answer_question("airport", notes, index=None, llm=_BoomLLM(), top_k=2)
        assert res.answer is None
        assert res.sources                              # the retrieved notes still show

    def test_degrades_when_llm_returns_empty(self):
        notes = _notes()
        res = answer_question("airport", notes, index=None, llm=_EmptyLLM(), top_k=2)
        assert res.answer is None
        assert res.sources

    def test_empty_question_returns_empty_result(self):
        res = answer_question("   ", _notes(), index=None, llm=_CountingLLM())
        assert res.answer is None
        assert res.sources == []

    def test_no_match_returns_empty_sources(self):
        # A keyword query that matches nothing -> nothing retrieved -> no sources, no answer.
        notes = _notes()
        res = answer_question("zzzqqq nonexistent token", notes,
                              index=None, llm=_CountingLLM(), top_k=3)
        assert res.sources == []
        assert res.answer is None

    def test_top_k_caps_sources(self):
        notes = _notes()
        # A broad query matching several notes, capped to 1 source.
        res = answer_question("airport", notes, index=None, llm=_CountingLLM(), top_k=1)
        assert len(res.sources) <= 1

    def test_deleted_notes_excluded_from_retrieval(self):
        notes = _notes()
        notes[0].deleted = True                         # the airport note is gone
        res = answer_question("airport parking level", notes,
                              index=None, llm=_CountingLLM(), top_k=3)
        assert "n1" not in res.sources


# --------------------------------------------------------------------------- #
# sources_hash + normalize_question
# --------------------------------------------------------------------------- #
class TestSourcesHash:
    def test_stable_and_order_independent(self):
        notes = _notes()
        h1 = sources_hash([notes[0], notes[1]])
        h2 = sources_hash([notes[1], notes[0]])         # reversed order
        assert h1 == h2                                 # order independent

    def test_changes_when_a_note_body_changes(self):
        notes = _notes()
        before = sources_hash([notes[0], notes[1]])
        notes[0].body = "I parked in level 5 row A instead"
        after = sources_hash([notes[0], notes[1]])
        assert before != after

    def test_changes_when_a_note_is_dropped(self):
        notes = _notes()
        assert sources_hash([notes[0], notes[1]]) != sources_hash([notes[0]])

    def test_normalize_question_folds_case_and_spacing(self):
        assert normalize_question("  Where  is My  Passport? ") == \
            normalize_question("where is my passport?")


# --------------------------------------------------------------------------- #
# WarmCache
# --------------------------------------------------------------------------- #
class TestWarmCache:
    def test_precompute_then_hit_does_not_call_llm_again(self):
        notes = _notes()
        llm = _CountingLLM()
        cache = WarmCache(top_k=2)
        n = cache.precompute(["Where did I park at the airport?"], notes,
                             index=None, llm=llm)
        assert n == 1
        calls_after_precompute = llm.calls
        assert calls_after_precompute == 1              # precompute ran the LLM once

        # HIT: same question, unchanged sources -> served from cache, NO new LLM call.
        res = cache.ask("Where did I park at the airport?", notes, index=None, llm=llm)
        assert res.answer is not None
        assert llm.calls == calls_after_precompute       # the model was not consulted again

    def test_normalized_hit(self):
        notes = _notes()
        llm = _CountingLLM()
        cache = WarmCache(top_k=2)
        cache.precompute(["Where did I park at the airport?"], notes, index=None, llm=llm)
        before = llm.calls
        # Different case + spacing, same normalized key -> still a hit.
        res = cache.ask("  WHERE did I   park at the airport? ", notes, index=None, llm=llm)
        assert res.answer is not None
        assert llm.calls == before

    def test_miss_for_new_question_computes_live(self):
        notes = _notes()
        llm = _CountingLLM()
        cache = WarmCache(top_k=2)
        cache.precompute(["Where did I park at the airport?"], notes, index=None, llm=llm)
        before = llm.calls
        # A brand-new question is not cached -> computed live (one new LLM call) + cached.
        res = cache.ask("What is on the vacation plan?", notes, index=None, llm=llm)
        assert res.answer is not None
        assert llm.calls == before + 1
        assert cache.has("What is on the vacation plan?")

    def test_invalidation_on_source_edit_recomputes(self):
        notes = _notes()
        llm = _CountingLLM()
        cache = WarmCache(top_k=2)
        cache.precompute(["Where did I park at the airport?"], notes, index=None, llm=llm)
        calls_before = llm.calls

        # Edit a cited note -> its content hash changes -> the cached entry is now stale.
        for n in notes:
            if n.id == "n1":
                n.body = "I parked in level 5 row A instead, not level 3"
                n.updated = datetime(2026, 6, 20, 12, 0, 0)

        res = cache.ask("Where did I park at the airport?", notes, index=None, llm=llm)
        assert res.answer is not None
        assert llm.calls == calls_before + 1            # recomputed live, not served stale
        # The fresh answer reflects the edited note (the stub echoes the new body).
        assert "level 5 row A" in res.answer

    def test_invalidate_drops_stale_entries(self):
        notes = _notes()
        llm = _CountingLLM()
        cache = WarmCache(top_k=2)
        cache.precompute(["Where did I park at the airport?"], notes, index=None, llm=llm)
        assert len(cache) == 1
        # Nothing changed -> invalidate keeps the entry.
        assert cache.invalidate(notes) == 0
        assert len(cache) == 1
        # Edit a cited note -> invalidate evicts the entry.
        for n in notes:
            if n.id == "n1":
                n.body = "totally different content now"
        assert cache.invalidate(notes) == 1
        assert len(cache) == 0

    def test_precompute_skips_blank_and_duplicates(self):
        notes = _notes()
        cache = WarmCache(top_k=2)
        n = cache.precompute(
            ["airport", "  ", "AIRPORT", "airport"], notes, index=None, llm=_CountingLLM())
        assert n == 1                                   # only one distinct, non-blank key
        assert cache.keys() == ["airport"]

    def test_precompute_does_not_cache_zero_source_questions(self):
        notes = _notes()
        cache = WarmCache(top_k=2)
        n = cache.precompute(["zzzqqq nonexistent"], notes, index=None, llm=_CountingLLM())
        assert n == 0
        assert len(cache) == 0

    def test_cache_degrades_when_llm_unavailable(self):
        notes = _notes()
        llm = _CountingLLM(available=False)
        cache = WarmCache(top_k=2)
        # precompute stores a sources-only entry (answer None) even with no usable LLM.
        assert cache.precompute(["airport"], notes, index=None, llm=llm) == 1
        res = cache.ask("airport", notes, index=None, llm=llm)
        assert res.answer is None
        assert res.sources                              # the retrieved notes are still cached
        assert llm.calls == 0

    def test_sources_only_entry_recomputes_once_llm_becomes_available(self):
        # Regression (RAG-1): a sources-only entry cached WITHOUT a usable LLM must NOT be
        # served verbatim once a model appears - the next ask() re-answers with the live model.
        notes = _notes()
        cache = WarmCache(top_k=2)
        # precompute / ask while the model is absent -> caches answer=None.
        assert cache.precompute(["airport"], notes, index=None, llm=None) == 1
        degraded = cache.ask("airport", notes, index=None, llm=None)
        assert degraded.answer is None                  # degrade path: sources only

        # Drop a working model into place; the same question must now synthesize an answer.
        llm = _CountingLLM(available=True)
        res = cache.ask("airport", notes, index=None, llm=llm)
        assert res.answer is not None                   # not the stale answer=None
        assert llm.calls == 1                           # the now-available model was consulted

        # And it is re-cached as an answered entry: a second ask is a hit (no new call).
        res2 = cache.ask("airport", notes, index=None, llm=llm)
        assert res2.answer is not None
        assert llm.calls == 1

    def test_answered_entry_not_reused_when_llm_disappears(self):
        # The flip the other way: an answered entry is NOT served once the model goes away
        # (its usability changed) - ask() degrades to a fresh sources-only result.
        notes = _notes()
        llm = _CountingLLM(available=True)
        cache = WarmCache(top_k=2)
        cache.precompute(["airport"], notes, index=None, llm=llm)
        assert cache.ask("airport", notes, index=None, llm=llm).answer is not None

        # Model now unavailable -> the answered entry is a miss; degrade to sources-only.
        gone = _CountingLLM(available=False)
        res = cache.ask("airport", notes, index=None, llm=gone)
        assert res.answer is None
        assert res.sources
        assert gone.calls == 0

    def test_precompute_self_indexes_the_semantic_index(self):
        # RAG-2: precompute is a standalone break-time hook; it must index the live store
        # itself (index-first) so semantic retrieval queries a fresh store, NOT rely on the
        # caller having pre-indexed. The test never calls index.index() - precompute must.
        notes = _notes()
        index = _index()                                # live, but NOT indexed by the test
        assert index.available is True
        # An un-indexed live store returns nothing for a semantic search.
        assert index.search("beach ocean flight hotel", top_k=1) == []

        cache = WarmCache(top_k=1)
        n = cache.precompute(["beach ocean flight hotel"], notes,
                             index=index, llm=_CountingLLM())
        assert n == 1
        # precompute populated the store: the same semantic search now ranks the vacation note.
        ranked = index.search("beach ocean flight hotel", top_k=1)
        assert [r.id for r in ranked] == ["n3"]


class TestRetrieveOverFetch:
    """Phase C QA (criticizer #1/#7): _retrieve/answer_question must over-fetch the full
    corpus so a context-filtered candidate past top_k in the full ranking still retrieves."""

    class _FakeIndex:
        available = True

        def __init__(self, ranking, pop):
            self._ranking, self._pop, self.queried = ranking, pop, []

        def population(self):
            return self._pop

        def search(self, query, top_k=10):
            self.queried.append(top_k)
            return [Note(id=i) for i in self._ranking[:top_k]]

    def test_answer_overfetches_to_population(self):
        idx = self._FakeIndex(["o1", "o2", "o3", "inctx"], pop=4)
        inctx = Note(id="inctx", title="airport", body="I parked in lot C")
        res = answer_question("where did I park", [inctx], index=idx, llm=None, top_k=2)
        assert "inctx" in res.sources                 # retrieved despite ranking past k=2
        assert idx.queried == [4]                      # full-corpus over-fetch
