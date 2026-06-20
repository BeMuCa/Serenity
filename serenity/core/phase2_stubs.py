"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Wired-up Phase-2 entry points - LLM routing, voice transcription, embeddings.
Role:    Clean interfaces the Phase-1 app can call today; they raise / no-op until the
         Phase-2 backends land (see notes/2_System_Arch.md, serenity-spec.md sec 11).
         NOT fake demos - real seams so Phase 2 slots in without reworking callers.

Classes:
- CaptureRouter - transcript -> structured Capture via an injected LLMEngine (core.llm),
  with a deterministic parse_capture fallback. The LLM produces a small JSON object that is
  validated then MERGED onto the parser baseline; any failure degrades to pure parse_capture.
- TranscriptionService - audio -> text (whisper.cpp, on-device). STUB.
- SemanticIndex - note embeddings -> "Meaning" search (e5 + sqlite-vec), via core.semantic.
============================================================
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .models import Note
from .parser import Capture, parse_capture

if TYPE_CHECKING:
    from .llm import LLMEngine
    from .semantic import Embedder, VectorStore


# The capture intents the router will accept from the LLM (must match parser.Capture's
# vocabulary). Anything outside this set is rejected and the parser baseline is kept.
_VALID_INTENTS = frozenset(
    {"todo", "note", "note_idea", "meeting", "reminder", "ask"})

# The system instruction handed to the LLM. Constrains it to emit a small JSON object so
# the result is machine-validatable; on any deviation the router falls back to the parser.
# No emojis; "-" not an em-dash (CLAUDE.md user-string rules).
_ROUTER_SYSTEM = (
    "You are a capture router. Read the user's note and reply with a single JSON object "
    "and nothing else. Keys: intent (one of todo, note, note_idea, meeting, reminder, "
    "ask), title (a short clean summary). Do not add commentary."
)

# Pull the first {...} object out of an LLM reply (it may wrap JSON in prose / fences).
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


class CaptureRouter:
    """Phase 2: route a transcript to a structured Capture via a local LLM.

    Holds an injected LLMEngine (core.llm) - a StubLLM in tests, a LlamaCppLLM in the app,
    or None. The LLM never writes directly: route() asks it for a small JSON object, then
    VALIDATES it and MERGES the trusted fields (intent, title) onto a deterministic
    parse_capture baseline, so dates / tags / recurring / confidence / missing-slot logic
    stay rule-based and the existing route()->Capture contract (and the confirm + undo
    intent) are unchanged. On ANY failure - no engine, engine unavailable, empty / non-JSON
    / invalid output - it degrades to pure parse_capture (the Phase-1 behavior). `available`
    reflects whether a usable engine is wired."""

    def __init__(self, engine: "Optional[LLMEngine]" = None) -> None:
        self.engine = engine
        # Available only when a usable engine is wired (degrade-to-parser otherwise).
        self.available = bool(
            engine is not None and getattr(engine, "available", False))

    def route(self, text: str) -> Capture:
        """Transcript -> structured Capture. LLM-assisted when available, else parse_capture.

        Always returns a Capture (never raises). The deterministic parser is the baseline
        and the always-correct fallback; the LLM only refines intent + title on top of it."""
        # Deterministic baseline - also the fallback for every LLM failure path below.
        base = parse_capture(text)
        if not self.available or self.engine is None:
            return base
        data = self._ask_llm(text)
        if not data:
            return base
        return self._merge(base, data)

    def _ask_llm(self, text: str) -> Optional[dict]:
        """Ask the engine for the capture JSON and parse it, or None on any failure.

        Fail-closed: a missing engine, an inference error, empty output or text that does
        not contain a JSON object all return None so route() keeps the parser baseline."""
        raw = (text or "").strip()
        if not raw:
            return None
        try:
            reply = self.engine.generate(raw, system=_ROUTER_SYSTEM, max_tokens=256)
        except Exception:
            return None
        if not reply:
            return None
        match = _JSON_OBJ_RE.search(reply)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except Exception:
            return None
        return obj if isinstance(obj, dict) else None

    def _merge(self, base: Capture, data: dict) -> Capture:
        """Validate the LLM dict and merge its trusted fields onto the parser baseline.

        Only `intent` (must be a known intent) and `title` (a non-empty string) are taken
        from the model; everything else (date, tags, recurring, confidence, missing) stays
        as the deterministic parser computed it. Unknown / malformed fields are ignored, so
        a partially-valid reply still improves the capture without ever corrupting it. The
        reminder flag is kept consistent with the chosen intent. Returns the baseline
        unchanged if nothing valid is on offer."""
        intent = data.get("intent")
        if isinstance(intent, str) and intent in _VALID_INTENTS:
            base.intent = intent
            base.reminder = (intent == "reminder")
        title = data.get("title")
        if isinstance(title, str) and title.strip():
            base.title = title.strip()
        # Re-derive the required-slot check against the (possibly) new intent/title so the
        # confirm/slot-filling flow stays correct after the merge.
        missing: list[str] = []
        if not base.title:
            missing.append("title")
        if base.kind == "todo" and base.intent in ("meeting", "reminder") \
                and base.date is None:
            missing.append("date")
        base.missing = missing
        return base

    def load_model(self, gguf_path: str) -> None:
        raise NotImplementedError(
            "Phase 2: load a Qwen3-4B GGUF via llama-cpp-python with GBNF/json_schema "
            "constrained decoding. Validate the grammar at init and fail closed. "
            "The pluggable seam is core.llm.LlamaCppLLM - inject it via __init__(engine=)."
        )


class TranscriptionService:
    """Phase 2: on-device speech-to-text. The mic never streams out."""

    available = False

    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError(
            "Phase 2: local transcription via whisper.cpp / faster-whisper. "
            "Phase 1 captures text only - no audio is recorded."
        )


class SemanticIndex:
    """'Meaning' search over note embeddings (e5 + sqlite-vec), via core.semantic.

    The assembled object the app holds: an Embedder (the real E5Embedder, or a test
    StubEmbedder) plus a VectorStore. `available` is False until a USABLE embedder is
    wired - a bare SemanticIndex() (no embedder) reports available=False and search()
    returns [] so core.search.semantic_search silently falls back to keyword search, with
    no crash and nothing heavy loaded at idle. index() is incremental: only notes whose
    content hash changed are re-embedded (the rest are skipped), and vectors for deleted /
    gone notes are pruned - so the break-time re-index job is cheap on repeat runs. The
    real e5 model only loads on the first index()/search()/related().

    related(note) is the note-linking surface (Job 4): nearest neighbours of a note's own
    text over the same index, id-only and self-excluded, mirroring search()'s lazy/degrade
    rules (it never auto-indexes; the caller indexes first, exactly as search() expects).

    neighbours(note) is the near-duplicate surface (Job 3): the same KNN as related() but
    returning (note_id, score) tuples so dedup can threshold on cosine; same lazy/degrade."""

    def __init__(self, embedder: "Optional[Embedder]" = None,
                 db_path: Optional[Path] = None,
                 store: "Optional[VectorStore]" = None) -> None:
        self.embedder = embedder
        self.db_path = db_path
        self._store = store
        # Available only when a usable embedder is present (degrade-to-keyword otherwise).
        self.available = bool(embedder is not None and getattr(embedder, "available", False))

    def _ensure_store(self) -> "Optional[VectorStore]":
        """Lazily build the VectorStore (dim taken from the embedder), or None when unusable."""
        if not self.available or self.embedder is None:
            return None
        if self._store is None:
            from .semantic import VectorStore
            self._store = VectorStore(db_path=self.db_path, dim=self.embedder.dim)
        return self._store

    def index(self, notes: list[Note]) -> None:
        """Incrementally (re)embed the active notes: skip unchanged, re-embed changed,
        prune deleted. No-op when no usable embedder is wired (available is False)."""
        store = self._ensure_store()
        if store is None or self.embedder is None:
            return
        from .semantic import note_hash, embed_text

        active = [n for n in notes if not n.deleted]
        to_embed: list[Note] = []
        hashes: dict[str, str] = {}
        for n in active:
            h = note_hash(n)
            hashes[n.id] = h
            if store.needs_embed(n.id, h):
                to_embed.append(n)
        if to_embed:
            vectors = self.embedder.embed_documents([embed_text(n) for n in to_embed])
            for n, vec in zip(to_embed, vectors):
                store.upsert(n.id, hashes[n.id], vec)
        # Invalidate-on-delete: drop vectors for notes no longer active.
        store.prune(keep_ids={n.id for n in active})

    def search(self, query: str, top_k: int = 10) -> list[Note]:
        """Ranked notes nearest to `query`. Returns [] when unavailable / empty query.

        Returns Note placeholders carrying only the matched ids (id-only); the caller
        (core.search.semantic_search) re-projects these ranked ids onto its live notes
        list. Phase-1 / no-embedder -> []."""
        store = self._ensure_store()
        if store is None or self.embedder is None:
            return []
        q = (query or "").strip()
        if not q:
            return []
        vec = self.embedder.embed_query(q)
        if not vec:
            return []
        k = max(1, int(top_k))
        ranked = store.query(vec, k)
        return [Note(id=note_id) for note_id, _score in ranked]

    def related(self, note: Note, top_k: int = 5) -> list[Note]:
        """Notes nearest to `note` over the embedding index (note-linking). Mirrors search().

        Returns id-only Note placeholders for the top_k most-similar OTHER notes, excluding
        `note` itself. [] when unavailable / empty store / `note` has no id / note has no
        embeddable text. The model only loads on first index()/search()/related() - same lazy
        rule as search(); related() does NOT call index() (the caller indexes first, exactly
        as NotesView.refresh already does for Meaning search)."""
        store = self._ensure_store()
        if store is None or self.embedder is None:
            return []
        # Empty/unpopulated store: skip the (potentially heavy) query-embed - no e5 model
        # load just to query nothing. hashes() is one cheap SELECT; [] degrades to the
        # keyword/tag fallback in related_notes() exactly as an empty result already does.
        if not store.hashes():
            return []
        nid = getattr(note, "id", None)
        if not nid:
            return []
        from .semantic import embed_text

        text = embed_text(note)
        if not text:
            return []
        # Query-side embed of the source note's own canonical text. embed_text yields the
        # same title+tags+body string used at index time, so the note maps to its own
        # neighbourhood; the StubEmbedder ignores e5's query:/passage: prefix so ranking
        # stays correct in tests.
        vec = self.embedder.embed_query(text)
        if not vec:
            return []
        k = max(1, int(top_k))
        # Pull k+1 so we can drop the note itself (it is almost always its own nearest match).
        ranked = store.query(vec, k + 1)
        out: list[Note] = []
        for note_id, _score in ranked:
            if note_id == nid:
                continue
            out.append(Note(id=note_id))
            if len(out) >= k:
                break
        return out

    def is_populated(self) -> bool:
        """True if the embedding store holds any vectors (cheap; one SELECT, no embed).

        Lets callers distinguish a real 'no results' from an unindexed store without an
        embed_query (used by dedup to decide whether to degrade to the token path). False
        when no usable embedder / store is wired."""
        store = self._ensure_store()
        return bool(store is not None and store.hashes())

    def neighbours(self, note: Note, top_k: int = 10) -> list[tuple[str, float]]:
        """Nearest OTHER notes to `note` over the embedding index, WITH scores.

        The pair-finding surface for dedup (Job 3): unlike related(), it returns (note_id,
        score) tuples so the near-duplicate scan can threshold on cosine. Mirrors related()'s
        lazy/degrade rules exactly - returns [] when unavailable / empty store / no id / no
        embeddable text / model-load failure (embed_query -> []). Does NOT auto-index (the
        caller indexes first). Self is excluded; results are (note_id, score) descending, up
        to top_k. Reuses VectorStore.query exactly as related() does - no new branching."""
        store = self._ensure_store()
        if store is None or self.embedder is None:
            return []
        if not store.hashes():
            return []
        nid = getattr(note, "id", None)
        if not nid:
            return []
        from .semantic import embed_text

        text = embed_text(note)
        if not text:
            return []
        vec = self.embedder.embed_query(text)
        if not vec:
            return []
        k = max(1, int(top_k))
        # Pull k+1 so we can drop the note itself (it is almost always its own nearest match).
        ranked = store.query(vec, k + 1)
        out: list[tuple[str, float]] = []
        for note_id, score in ranked:
            if note_id == nid:
                continue
            out.append((note_id, float(score)))
            if len(out) >= k:
                break
        return out
