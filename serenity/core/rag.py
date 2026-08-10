"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Ask-Your-Vault RAG - answer a question grounded ONLY in the user's own notes,
         with citations, plus a warm-cache so repeat questions answer instantly.
Role:    Backs the Notes tab "Ask" affordance (serenity.ui.ask_dialog). Retrieval-augmented
         generation over the local vault: pick the top_k most relevant notes (the e5/sqlite-vec
         SemanticIndex when available, else core.search.keyword_search), build a numbered
         context block from them, and ask the injected LLMEngine (core.llm) to answer USING
         ONLY that context and cite the notes it used - returning the answer plus the source
         note ids. NOTHING heavy is resident at idle: retrieval only embeds when the index is
         live, and the LLM only runs on a real ask. Degrades on every axis: no / unavailable
         LLM -> answer is None and sources are the retrieved ids (the UI just shows the
         related notes - no synthesized answer, no dead-end); no / unavailable index ->
         keyword retrieval. The WarmCache mirrors core.tts_cache's precompute+invalidate idea:
         precompute() runs the full RAG for candidate questions up front and stores results;
         ask() serves a cached answer when the question matches a stored key AND the source
         notes are unchanged (a hash over their content via core.semantic.note_hash), else it
         computes live and re-caches; stale entries (source hash drifted) self-invalidate. The
         cache is a standalone class with a thin precompute() hook - wiring it into the
         break-time scheduler is the framework's later job, NOT done here. Pure of Qt / heavy
         deps - unit-tested headless with StubLLM + a StubEmbedder-backed SemanticIndex. All
         strings are emoji-free with a single "-" (never an em-dash).

Functions:
- answer_question(question, notes, index, llm, top_k=5) -> RagResult - retrieve -> ground ->
  answer + cite; degrades to sources-only (answer None) when no usable LLM
- normalize_question(question) -> str - the cache key: lowercased, whitespace-collapsed
- sources_hash(notes) -> str - a stable hash over a set of notes' content (reuses note_hash)

Classes:
- RagResult - the answer (str or None) + the source note ids used as citations
- WarmCache - precompute()/ask() over a dict of {question_key: entry}; serves a cached
  answer only when the question matches AND its source hash is unchanged, else recomputes;
  invalidate() prunes entries whose sources drifted
============================================================
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .models import Note
from .search import _STOP, _haystack, _sort_ts, _tokens, keyword_search
from .semantic import note_hash

if TYPE_CHECKING:
    from .llm import LLMEngine
    from .phase2_stubs import SemanticIndex

# How many notes to retrieve as grounding context by default. Small on purpose: a personal
# vault answer rarely needs more than a handful of notes, the context block stays inside the
# small local model's window, and citations stay readable.
DEFAULT_TOP_K = 5

# The system instruction handed to the LLM. It pins the model to the supplied context and asks
# it to ground its answer there - so the vault is the only source of truth and the model does
# not free-associate from its pre-training. No emojis; "-" not an em-dash (CLAUDE.md rules).
_RAG_SYSTEM = (
    "You are a helpful assistant answering questions about the user's own notes. "
    "Use ONLY the numbered notes in the context to answer. If the notes do not contain the "
    "answer, say you could not find it in the notes. Do not invent facts. Keep the answer "
    "short and refer to the relevant note numbers."
)

_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Result + small pure helpers (the cache key + the source-content hash).
# --------------------------------------------------------------------------- #

@dataclass
class RagResult:
    """The outcome of answer_question: a synthesized answer (or None) + its citations.

    `answer` is the LLM's grounded reply, or None when no usable LLM is wired (the degrade
    path - the UI then shows the retrieved notes as related, with no synthesized answer and
    no dead-end). `sources` is the list of source note ids used as citations - the notes
    actually fed to the model on the answer path, and the retrieved-but-unanswered notes on
    the degrade path - so the UI can always render clickable citation chips either way."""

    answer: Optional[str] = None
    sources: list[str] = field(default_factory=list)


def normalize_question(question: str) -> str:
    """The cache key for a question: lowercased, whitespace-collapsed, trimmed.

    Pure - no disk, no model - so two cosmetically-different spellings of the same question
    ('Where is my passport?' vs '  where is my   passport? ') collide on one cache entry.
    Punctuation is intentionally kept (it can carry meaning) - only case + spacing fold."""
    return _WS.sub(" ", (question or "").strip().lower())


def sources_hash(notes: list[Note]) -> str:
    """A stable hash over a SET of notes' content - the cache's invalidation key.

    Reuses core.semantic.note_hash per note (the same per-note content key the embedding
    index keys on), then folds the (id, hash) pairs in a deterministic id-sorted order so the
    result is independent of retrieval order and changes the moment ANY cited note's content
    changes (or a note is added to / dropped from the set). Pure - unit-tested without a
    backend. An empty set hashes to a fixed, stable value."""
    h = hashlib.sha256()
    for n in sorted(notes, key=lambda x: x.id):
        h.update((n.id or "").encode("utf-8"))
        h.update(b"\x00")
        h.update(note_hash(n).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Retrieval + the RAG answer.
# --------------------------------------------------------------------------- #

def _keyword_retrieve(question: str, active: list[Note], k: int) -> list[Note]:
    """The keyword degrade retriever: strict conjunctive match first, OR-overlap fallback.

    core.search.keyword_search is conjunctive (a note matches only if it contains EVERY query
    token) - exactly right for a search BOX, but too strict for a natural-language QUESTION
    ('Where did I park at the airport?'), where no single note holds all the tokens and the
    strict match returns nothing. So: try the strict match first (it is the most precise), and
    when it yields nothing, fall back to ranking by how many DISTINCT content tokens of the
    question appear in each note (stop-words filtered via core.search._STOP, the same set the
    related-notes fallback uses) - an OR-overlap score so a question still retrieves its notes
    even with no embedding model. A query token counts as present when it is a SUBSTRING of any
    note token (the same forgiving containment keyword_search itself uses, so 'park' matches a
    note's 'parking' / 'parked') - natural-language questions rarely share an exact surface
    form with a note. Deterministic: ties break on the standard recent-first order."""
    strict = keyword_search(active, question)
    if strict:
        return strict[:k]
    qtokens = {t for t in _tokens(question) if t not in _STOP}
    if not qtokens:
        return []
    scored: list[tuple[float, Note]] = []
    for n in active:
        hay = _haystack(n)
        overlap = sum(1 for t in qtokens if t in hay)
        if overlap <= 0:
            continue
        scored.append((float(overlap), n))
    scored.sort(key=lambda x: (-x[0], _sort_ts(x[1])))
    return [n for _, n in scored[:k]]


def _retrieve(question: str, notes: list[Note],
              index: "Optional[SemanticIndex]", top_k: int) -> list[Note]:
    """The top_k notes most relevant to `question`, semantic when available else keyword.

    Mirrors core.search.semantic_search's decision point: a live index ranks by meaning (its
    ids re-projected onto `notes`, deleted dropped, order preserved); otherwise - no index,
    unavailable index, or an empty/unindexed result - _keyword_retrieve ranks the same notes
    (strict match, then an OR token-overlap fallback for natural-language questions).
    Always returns at most top_k notes, never raises."""
    k = max(0, int(top_k))
    if k <= 0:
        return []
    active = [n for n in notes if not n.deleted]
    if index is not None and getattr(index, "available", False):
        # Over-fetch the FULL corpus ranking (Phase C): `notes` may be a context-filtered
        # subset of what the index holds, so a small top_k could be filled by other-context
        # notes and re-project to nothing. Rank all, re-project, then break at k.
        ranked = index.search(question, top_k=max(k, index.population()))
        if ranked:
            by_id = {n.id: n for n in active}
            out: list[Note] = []
            for r in ranked:
                n = by_id.get(r.id)
                if n is not None:
                    out.append(n)
                if len(out) >= k:
                    break
            if out:
                return out
    # Degrade: keyword retrieval (also the empty-index / no-model path).
    return _keyword_retrieve(question, active, k)


def _build_context(notes: list[Note]) -> str:
    """A numbered context block the model cites by index: '[1] Title\\n body' per note.

    The body is included so the model has the facts to answer from; titles + numbers give it
    a stable handle to cite. Plain text - the cleaning the embedder does is not needed here."""
    blocks: list[str] = []
    for i, n in enumerate(notes, 1):
        title = (n.title or "Untitled").strip()
        body = (n.body or "").strip()
        block = f"[{i}] {title}"
        if body:
            block += f"\n{body}"
        blocks.append(block)
    return "\n\n".join(blocks)


def answer_question(question: str, notes: list[Note],
                    index: "Optional[SemanticIndex]" = None,
                    llm: "Optional[LLMEngine]" = None,
                    top_k: int = DEFAULT_TOP_K) -> RagResult:
    """Answer `question` grounded ONLY in the user's notes, with citations.

    Flow: retrieve the top_k most relevant notes (semantic via `index` when available, else
    keyword), build a numbered context block from them, and ask `llm` to answer USING ONLY
    that context. Returns a RagResult with the synthesized answer and the source note ids.

    Precondition (semantic path): like SemanticIndex.search, this NEVER auto-indexes - when a
    live `index` is passed the caller must have already indexed it for `notes` (AskDialog._ask
    does this index-first; WarmCache.precompute does it once up front). An un-indexed live
    index simply yields nothing and retrieval falls back to keyword - correct but stale.

    DEGRADE (never a dead-end, never raises):
    - empty question OR nothing retrieved -> RagResult(answer=None, sources=[]);
    - `llm` is None / unavailable / errors / returns empty -> RagResult(answer=None,
      sources=<retrieved ids>): the UI shows the retrieved notes as related, no synthesized
      answer. The retrieved ids are ALWAYS the citations, so chips render on both paths."""
    q = (question or "").strip()
    if not q:
        return RagResult(answer=None, sources=[])

    retrieved = _retrieve(q, notes, index, top_k)
    source_ids = [n.id for n in retrieved]
    if not retrieved:
        return RagResult(answer=None, sources=[])

    # Degrade to sources-only when no usable LLM is wired - the UI shows the retrieved notes.
    if llm is None or not getattr(llm, "available", False):
        return RagResult(answer=None, sources=source_ids)

    context = _build_context(retrieved)
    prompt = (
        f"Context notes:\n{context}\n\n"
        f"Question: {q}\n\n"
        "Answer using only the notes above and cite the note numbers you used."
    )
    try:
        reply = llm.generate(prompt, system=_RAG_SYSTEM, max_tokens=384, blocking=False)
    except Exception:
        # Inference error -> degrade to sources-only (the retrieved notes still show).
        return RagResult(answer=None, sources=source_ids)
    answer = (reply or "").strip()
    if not answer:
        return RagResult(answer=None, sources=source_ids)
    return RagResult(answer=answer, sources=source_ids)


# --------------------------------------------------------------------------- #
# Warm-cache: precompute candidate answers, serve on a hit, self-invalidate.
# (Mirrors core.tts_cache's precompute + invalidate idea, for RAG answers.)
# --------------------------------------------------------------------------- #

def _usable_llm(llm: "Optional[LLMEngine]") -> bool:
    """True when `llm` is wired AND reports itself available - the same usability test
    answer_question applies before it will run the model. The cache records this at write
    time so an answer synthesized (or NOT synthesized) under one LLM state is never served
    as a hit under a different one."""
    return llm is not None and bool(getattr(llm, "available", False))

@dataclass
class _CacheEntry:
    """One cached RAG answer keyed by a normalized question.

    `answer` / `source_ids` are the stored RagResult fields; `source_hash` is sources_hash
    over the notes that produced them, so a hit is only valid while those notes are unchanged.
    `had_llm` records whether a usable LLM was wired when the entry was written - so a
    sources-only entry produced on the degrade path (no model) never satisfies a hit once a
    model appears (otherwise ask() would serve answer=None forever, until a cited note drifts,
    despite a now-working model). `question` keeps the original text for diagnostics /
    re-precompute."""

    question: str
    answer: Optional[str]
    source_ids: list[str]
    source_hash: str
    had_llm: bool = False


class WarmCache:
    """A warm-cache of RAG answers: precompute candidate questions, serve unchanged ones fast.

    Mirrors core.tts_cache's precompute + invalidate pattern, for answers instead of audio:
    a break-time / idle step calls precompute(questions, notes, index, llm) to run the full
    answer_question for each candidate and store the result; later, ask(question, notes, ...)
    serves the cached answer when the question matches a stored key (exact OR normalized), the
    cited notes are unchanged (sources_hash matches), AND the LLM usability is unchanged since
    the entry was written - otherwise it recomputes live and re-caches, and prunes the now-stale
    entry. invalidate(notes) drops every entry whose cited notes' content has drifted, so a
    single edited note evicts exactly the answers that cited it. This is a STANDALONE class with
    a thin precompute() hook; wiring it into the actual break-time scheduler is the framework's
    later job and is deliberately NOT done here.

    Degrades like answer_question: precompute over an unavailable LLM stores sources-only
    entries (answer None), and ask() with no usable LLM serves / computes the sources-only
    result the same way - so the cache never blocks the degrade path. A sources-only entry
    (cached with no usable LLM) is treated as a MISS once a usable LLM is wired, so dropping a
    model into place makes the next ask() synthesize a real answer instead of replaying the
    cached answer=None until a cited note happens to change."""

    def __init__(self, top_k: int = DEFAULT_TOP_K) -> None:
        self.top_k = max(1, int(top_k))
        self._entries: dict[str, _CacheEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> list[str]:
        """The normalized question keys currently cached (diagnostics / tests)."""
        return list(self._entries.keys())

    def has(self, question: str) -> bool:
        """True when a (normalized) entry for `question` exists - regardless of staleness."""
        return normalize_question(question) in self._entries

    def precompute(self, questions: list[str], notes: list[Note],
                   index: "Optional[SemanticIndex]" = None,
                   llm: "Optional[LLMEngine]" = None) -> int:
        """Run the full RAG for each candidate question and store the results. Returns the
        number of entries written.

        The warm-up hook (intended for a break-time / idle pass): each question is answered
        once now so the next ask() is instant. Blank / duplicate (post-normalize) questions
        are skipped; an answer that retrieved nothing (no sources) is NOT cached (there is
        nothing to key invalidation on, and a future note could make it answerable). Stores
        the sources_hash over the cited notes so the entry self-validates at ask-time, and
        records whether a usable LLM was wired so a sources-only entry never serves as a hit
        once a model appears.

        Index: this hook indexes the SemanticIndex over `notes` ONCE up front when a usable
        index is wired (cheap + incremental, mirroring AskDialog._ask's index-first step), so
        the semantic retrieval queries a fresh store rather than a stale / empty one. The
        caller therefore does NOT need to pre-index before calling precompute."""
        if index is not None and getattr(index, "available", False):
            index.index(notes)
        had_llm = _usable_llm(llm)
        written = 0
        for q in questions:
            key = normalize_question(q)
            if not key or key in self._entries:
                continue
            res = answer_question(q, notes, index, llm, top_k=self.top_k)
            if not res.sources:
                continue
            cited = self._cited_notes(res.sources, notes)
            self._entries[key] = _CacheEntry(
                question=(q or "").strip(),
                answer=res.answer,
                source_ids=list(res.sources),
                source_hash=sources_hash(cited),
                had_llm=had_llm,
            )
            written += 1
        return written

    def ask(self, question: str, notes: list[Note],
            index: "Optional[SemanticIndex]" = None,
            llm: "Optional[LLMEngine]" = None) -> RagResult:
        """Serve `question` from the cache when fresh, else compute live and (re)cache it.

        HIT: a stored entry whose key matches (normalized), whose source_hash still equals
        sources_hash over its cited notes in the CURRENT vault, AND that was written under the
        SAME LLM usability as now - returned verbatim, no LLM call. MISS: no entry, the cited
        notes changed, or the LLM usability flipped (e.g. a sources-only entry was cached with
        no model and a model is now available, so it must be re-answered) - the entry is pruned
        first, then answer_question runs live, the fresh result is cached (when it has sources),
        and returned. Always returns a RagResult; degrades exactly like answer_question."""
        key = normalize_question(question)
        had_llm = _usable_llm(llm)
        entry = self._entries.get(key)
        if entry is not None:
            cited = self._cited_notes(entry.source_ids, notes)
            # A hit requires the cited notes to still exist, their content to be unchanged, AND
            # the LLM usability to match the entry's - so a sources-only entry computed without
            # a model is re-answered (not served verbatim) once a model becomes available.
            if len(cited) == len(entry.source_ids) and \
                    sources_hash(cited) == entry.source_hash and \
                    entry.had_llm == had_llm:
                return RagResult(answer=entry.answer, sources=list(entry.source_ids))
            # Miss: the sources drifted (edited / deleted) or the LLM state changed. Evict and
            # recompute.
            self._entries.pop(key, None)

        res = answer_question(question, notes, index, llm, top_k=self.top_k)
        if key and res.sources:
            cited = self._cited_notes(res.sources, notes)
            self._entries[key] = _CacheEntry(
                question=(question or "").strip(),
                answer=res.answer,
                source_ids=list(res.sources),
                source_hash=sources_hash(cited),
                had_llm=had_llm,
            )
        return res

    def invalidate(self, notes: list[Note]) -> int:
        """Drop every cached entry whose cited notes drifted (content changed / gone). Returns
        the number of entries evicted.

        Mirrors the cache invalidation in core.tts_cache / SemanticIndex.index: an edit to one
        note evicts exactly the answers that cited it (their recomputed source_hash no longer
        matches), leaving still-valid answers warm. Cheap - a hash compare per entry."""
        dropped = 0
        for key in list(self._entries.keys()):
            entry = self._entries[key]
            cited = self._cited_notes(entry.source_ids, notes)
            if len(cited) != len(entry.source_ids) or \
                    sources_hash(cited) != entry.source_hash:
                self._entries.pop(key, None)
                dropped += 1
        return dropped

    def clear(self) -> None:
        """Wipe every cached entry (e.g. on a vault switch / model change)."""
        self._entries.clear()

    @staticmethod
    def _cited_notes(source_ids: list[str], notes: list[Note]) -> list[Note]:
        """Resolve cited ids to live, NON-deleted Note objects, preserving id order.

        A deleted / gone note simply drops out, so the resolved list is shorter than the cited
        ids - which ask()/invalidate() read as 'the sources changed' (a citation vanished)."""
        by_id = {n.id: n for n in notes if not n.deleted}
        out: list[Note] = []
        for sid in source_ids:
            n = by_id.get(sid)
            if n is not None:
                out.append(n)
        return out
