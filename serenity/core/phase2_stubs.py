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
- TranscriptionService - audio -> text (faster-whisper, on-device); pluggable Transcriber
  backend via core.stt (StubTranscriber for tests, lazy WhisperTranscriber for real use).
- SemanticIndex - note embeddings -> "Meaning" search (e5 + sqlite-vec), via core.semantic.
============================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .models import Note
from .parser import Capture, parse_capture

if TYPE_CHECKING:
    from .llm import LLMEngine
    from .semantic import Embedder, VectorStore
    from .stt import Transcriber


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

def _iter_json_objs(s: str):
    """Yield each balanced top-level {...} substring in `s`, left to right.

    The default model (Qwen3) is a reasoning model that emits a leading <think>...</think>
    block, and that block routinely contains a stray brace while it reasons about the output
    format (e.g. "output {intent, title} as JSON"). A greedy `\\{.*\\}` would span from that
    first brace to the LAST brace in the reply, splicing the think-block prose into the real
    object so json.loads fails and a perfectly valid result is discarded. Instead we walk the
    string tracking nesting depth (ignoring braces inside JSON string literals, with escape
    handling) and yield each complete top-level object as we close it - so the caller can try
    each candidate and keep the first that parses. The think-block's `{intent, title}` is
    yielded first (and rejected by json.loads), then the real object is yielded next."""
    depth = 0
    start = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(s):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    yield s[start:i + 1]
                    start = -1


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
        # Try each balanced top-level object left to right; keep the first that parses to a
        # dict. This skips a stray `{...}` inside a Qwen3 <think> block (which json.loads
        # rejects) and lands on the real object - where a greedy regex would splice the two
        # together and parse nothing.
        for frag in _iter_json_objs(reply):
            try:
                obj = json.loads(frag)
            except Exception:
                continue
            if isinstance(obj, dict):
                return obj
        return None

    def _merge(self, base: Capture, data: dict) -> Capture:
        """Validate the LLM dict and merge its trusted fields onto the parser baseline.

        Only `intent` (must be a known intent) and `title` (a non-empty string) are taken
        from the model; everything else (date, tags, recurring, reminder_offset) stays as
        the deterministic parser computed it. Unknown / malformed fields are ignored, so a
        partially-valid reply still improves the capture without ever corrupting it. The
        reminder flag is kept consistent with the chosen intent. When the LLM supplies BOTH
        a valid intent and a title, `confidence` is bumped to at least 0.75: the parser's
        score reflected a weak parse of the raw text, but a clean LLM intent+title is a
        strong result, and the documented confirm/slot-filling flow gates on confidence
        (< 0.55) - leaving the stale parser value would misfire that gate. Returns the
        baseline unchanged if nothing valid is on offer (the parser confidence is then the
        right value to keep)."""
        intent = data.get("intent")
        intent_ok = False
        if isinstance(intent, str) and intent in _VALID_INTENTS:
            base.intent = intent
            base.reminder = (intent == "reminder")
            intent_ok = True
        title = data.get("title")
        title_ok = False
        if isinstance(title, str) and title.strip():
            base.title = title.strip()
            title_ok = True
        # A clean LLM intent+title is a confident result - don't report the weak parser
        # score that the confirm flow would gate on. Only ever raise, never lower.
        if intent_ok and title_ok:
            base.confidence = max(base.confidence, 0.75)
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
    """On-device speech-to-text. The mic never streams out; this takes an audio FILE.

    A thin wrapper over a pluggable Transcriber backend (see core.stt): tests inject a
    deterministic StubTranscriber, while the default is the lazy WhisperTranscriber
    (faster-whisper, tiny/base for low-RAM) which reports available=False - and degrades
    transcribe() to "" - when the optional dep / model is absent. The recording UI is
    platform-specific and lives in the app layer, NOT here. transcribe_to_capture() routes
    the recognized text through the SAME CaptureRouter.route the typed-capture path uses, so
    a spoken utterance flows into the confirm + undo flow exactly like a typed one."""

    def __init__(self, transcriber: "Optional[Transcriber]" = None) -> None:
        if transcriber is None:
            from .stt import WhisperTranscriber
            transcriber = WhisperTranscriber()
        self.transcriber = transcriber

    @property
    def available(self) -> bool:
        """Live read-through to the wrapped backend's readiness (not a construction-time
        snapshot), so a backend that probes its dep/model lazily is reported correctly.
        False without faster-whisper / a model - the shipped backends are immutable here."""
        return bool(getattr(self.transcriber, "available", False))

    def transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file to text via the wrapped backend. Degrades to "".

        Never raises into the caller - an unavailable backend / unreadable file (or even an
        injected backend that raises) yields "" so the capture flow stays silent instead of
        crashing (mirrors the TTS engines). The shipped backends already degrade internally;
        the guard here makes the wrapper honour its own contract regardless of backend."""
        try:
            return self.transcriber.transcribe(audio_path)
        except Exception:
            return ""

    def transcribe_to_capture(self, audio_path: str,
                              router: "CaptureRouter") -> Optional[Capture]:
        """Transcribe an audio file then route the text into a Capture via CaptureRouter.

        Convenience over core.stt.transcribe_to_capture using this service's backend, so a
        spoken capture converges on the same structured Capture (and confirm + undo flow) as
        a typed one. Returns None when nothing usable was transcribed."""
        from .stt import transcribe_to_capture
        return transcribe_to_capture(audio_path, router, self.transcriber)


class SemanticIndex:
    """'Meaning' search over note embeddings (fastembed + sqlite-vec), via core.semantic.

    The assembled object the app holds: an Embedder (the real FastEmbedBackend, or a test
    StubEmbedder) plus a VectorStore. `available` is False until a USABLE embedder is
    wired - a bare SemanticIndex() (no embedder) reports available=False and search()
    returns [] so core.search.semantic_search silently falls back to keyword search, with
    no crash and nothing heavy loaded at idle. index() is incremental: only notes whose
    content hash changed are re-embedded (the rest are skipped), and vectors for deleted /
    gone notes are pruned - so the break-time re-index job is cheap on repeat runs. The
    real embedding model only loads on the first index()/search()/related().

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
        """Lazily build the VectorStore (dim + model id taken from the embedder), or None.

        The dim is fixed at store creation; for a custom fastembed id the backend's dim is
        0 until probed, so ensure_dim() (when present) discovers it first - the StubEmbedder
        has no ensure_dim, so the getattr fallback returns its fixed dim. The embedder's
        name (the fastembed model id) is threaded as the store's model so a model change
        wipes + rebuilds the store rather than mixing dims."""
        if not self.available or self.embedder is None:
            return None
        if self._store is None:
            from .semantic import VectorStore
            dim = getattr(self.embedder, "ensure_dim", lambda: self.embedder.dim)()
            # A custom fastembed id resolves to dim 0 until its first embedding sets it; if
            # the probe yielded nothing (model failed to download/load) dim stays 0. Building
            # VectorStore(dim=0) would create a float[0] table and disable the per-upsert dim
            # guard, so treat a still-zero dim as unusable and degrade to keyword search -
            # matching the available=False contract instead of opening a dim-0 store.
            if not dim:
                self.available = False
                return None
            self._store = VectorStore(
                db_path=self.db_path, dim=dim,
                model=getattr(self.embedder, "name", ""))
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

    def _nearest_other(self, note: Note, top_k: int) -> list[tuple[str, float]]:
        """Shared KNN plumbing for related()/neighbours(): the top_k nearest OTHER notes to
        `note` as (note_id, score), self excluded.

        Returns [] on the usual degrade paths (no store / no embedder, empty store, `note`
        has no id, no embeddable text, embed_query failure). The model only loads on the
        first index()/search()/related()/neighbours() - same lazy rule as search(); this does
        NOT call index() (the caller indexes first, exactly as NotesView.refresh already does
        for Meaning search)."""
        store = self._ensure_store()
        if store is None or self.embedder is None:
            return []
        # Empty/unpopulated store: skip the (potentially heavy) query-embed - no embedding
        # model load just to query nothing. hashes() is one cheap SELECT; [] degrades to the
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
        # neighbourhood; the StubEmbedder applies no query:/passage: prefix so ranking
        # stays correct in tests.
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

    def related(self, note: Note, top_k: int = 5) -> list[Note]:
        """Notes nearest to `note` over the embedding index (note-linking). Mirrors search().

        Returns id-only Note placeholders for the top_k most-similar OTHER notes, excluding
        `note` itself. [] when unavailable / empty store / `note` has no id / note has no
        embeddable text. The model only loads on first index()/search()/related() - same lazy
        rule as search(); related() does NOT call index() (the caller indexes first, exactly
        as NotesView.refresh already does for Meaning search)."""
        return [Note(id=nid) for nid, _score in self._nearest_other(note, top_k)]

    def is_populated(self) -> bool:
        """True if the embedding store holds any vectors (cheap; one SELECT, no embed).

        Lets callers distinguish a real 'no results' from an unindexed store without an
        embed_query (used by dedup to decide whether to degrade to the token path). False
        when no usable embedder / store is wired."""
        store = self._ensure_store()
        return bool(store is not None and store.hashes())

    def population(self) -> int:
        """The number of vectors held (0 when no usable store). Callers that rank the FULL
        corpus but then re-project onto a context-filtered candidate subset (Phase C) query
        with top_k=population() so a small fixed top_k can't be crowded out by other-context
        notes before the re-projection (a cheap SELECT, no embed)."""
        store = self._ensure_store()
        return len(store.hashes()) if store is not None else 0

    def neighbours(self, note: Note, top_k: int = 10) -> list[tuple[str, float]]:
        """Nearest OTHER notes to `note` over the embedding index, WITH scores.

        The pair-finding surface for dedup (Job 3): unlike related(), it returns (note_id,
        score) tuples so the near-duplicate scan can threshold on cosine. Mirrors related()'s
        lazy/degrade rules exactly - returns [] when unavailable / empty store / no id / no
        embeddable text / model-load failure (embed_query -> []). Does NOT auto-index (the
        caller indexes first). Self is excluded; results are (note_id, score) descending, up
        to top_k. Reuses VectorStore.query exactly as related() does - no new branching."""
        return self._nearest_other(note, top_k)
