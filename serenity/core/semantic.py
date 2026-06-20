"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The on-device 'Meaning' (semantic) search engine - e5 embeddings + a vector store.
Role:    Backs phase2_stubs.SemanticIndex and core.search.semantic_search. Holds the
         Embedder seam (a Protocol so tests inject a deterministic StubEmbedder while the
         real e5 backend, E5Embedder, is a lazy fastembed/ONNX class that degrades to
         available=False when its optional deps/model are absent), the per-note content
         hash (so an unchanged note is never re-embedded, mirroring the TTS render cache),
         and a VectorStore with a sqlite-vec native KNN fast path AND a pure-Python cosine
         fallback chosen at open time - so the suite runs on the stock sqlite3 here with no
         heavy deps. Nothing heavy is resident at idle: the e5 model loads on first use and
         is shared per process like KokoroEngine._shared. e5's 'query:' / 'passage:'
         instruction prefixes are applied INSIDE each backend, never by the caller.

Functions:
- embed_text(note) -> str - the canonical embedding input: title + tags + body, normalized
- note_hash(note) -> str - sha256 hex over embed_text(note) (no model tag folded in)

Classes:
- Embedder - typing.Protocol seam: name / dim / available + embed_documents / embed_query
- StubEmbedder - deterministic, dependency-free, L2-normalized hashing embedder (tests + default)
- E5Embedder - real backend: lazy fastembed/ONNX multilingual-e5, query:/passage: prefixes,
  shared session per process, available=False when fastembed is absent
- VectorStore - vectors keyed on (note_id, content_hash); sqlite-vec fast path OR pure-Python
  cosine fallback (upsert / needs_embed / query / prune / hashes / close)
============================================================
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from .models import Note

# The two interchangeable e5 backends (same family, same MIT license, same prefix scheme).
# Default is e5-BASE (user choice: better retrieval quality, matches the AI-stack note).
# e5-small stays reachable for the low-RAM idle principle on lighter machines - swapping is
# a one-line MODEL_ID + dim change against a fresh db (vectors are keyed per dim).
E5_SMALL_MODEL_ID = "intfloat/multilingual-e5-small"     # 384d, ~120-130 MB ONNX, MIT
E5_BASE_MODEL_ID = "intfloat/multilingual-e5-base"       # 768d, ~450 MB ONNX, MIT (16GB+)
E5_SMALL_DIM = 384
E5_BASE_DIM = 768

SEMANTIC_DB_FILE = "semantic.sqlite"

_WS = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[\wäöüÄÖÜß]+", re.UNICODE)


# --------------------------------------------------------------------------- #
# Content-hash incrementality (mirrors tts_cache.cache_key's sha256 idea).
# --------------------------------------------------------------------------- #

def embed_text(note: Note) -> str:
    """The canonical text fed to the embedder for a note: title + tags + body, normalized.

    This is the ONLY thing hashed and the ONLY thing embedded, so a note's hash and its
    vector always correspond. Whitespace is collapsed so cosmetic edits (extra spaces /
    newlines) do not invalidate the cache. Pure - no disk, no model - so the hash is
    deterministic and unit-tested without a backend. The e5 'passage:' prefix is NOT added
    here; each backend applies its own instruction prefix."""
    title = note.title or ""
    tags = " ".join(note.tags or [])
    body = note.body or ""
    raw = f"{title} \n {tags} \n {body}"
    return _WS.sub(" ", raw).strip()


def note_hash(note: Note) -> str:
    """sha256 hex over embed_text(note) - the per-note content key for incrementality.

    Like tts_cache.cache_key's sha256, minus the engine/voice components: the embedder's
    model tag is intentionally NOT folded in here (the store is keyed per dim, and a model
    change is handled by pointing at a fresh db - see open_questions). Same content -> same
    hash -> the note is skipped on the next index(); changed content -> new hash ->
    re-embedded; a gone note -> pruned."""
    return hashlib.sha256(embed_text(note).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Embedder seam (a Protocol; tests inject a stub, e5 is one real impl).
# --------------------------------------------------------------------------- #

@runtime_checkable
class Embedder(Protocol):
    """A text -> vector backend. Implementations apply their own instruction prefixes.

    `available` is False when the dep / model is absent so SemanticIndex degrades to
    keyword search; `name` tags the store's model column; `dim` fixes the store's vector
    width. embed_documents() embeds note passages (e5 prepends 'passage: '); embed_query()
    embeds a search query (e5 prepends 'query: ')."""

    name: str
    dim: int
    available: bool

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    """Return `vec` scaled to unit length (so cosine similarity == dot product).

    A zero vector is returned unchanged (no division by zero)."""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


class StubEmbedder:
    """Deterministic, dependency-free embedder for tests + the always-safe default.

    Hashes each token into a fixed-dim bag-of-tokens vector and L2-normalizes it, so:
    same text -> identical vector across calls (and processes), more shared tokens ->
    higher cosine similarity (monotonic, so ranking is predictable in tests), and no
    network / heavy deps are touched. It ignores e5's query:/passage: prefixes entirely so
    tests stay backend-agnostic."""

    name = "stub"
    available = True

    def __init__(self, dim: int = 16) -> None:
        self.dim = int(dim) if dim and dim > 0 else 16

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN_RE.findall((text or "").lower()):
            # Hash each token to a deterministic bucket; counts make overlap monotonic.
            h = hashlib.sha256(tok.encode("utf-8")).hexdigest()
            bucket = int(h[:8], 16) % self.dim
            vec[bucket] += 1.0
        return _l2_normalize(vec)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class E5Embedder:
    """Real backend: multilingual-e5 as ONNX via fastembed (no PyTorch). Lazy + graceful.

    fastembed gives the e5 model as ONNX (pulls onnxruntime, not torch); the model
    (~130 MB e5-small / ~450 MB e5-base) downloads once into a per-user cache on first
    embed. EVERYTHING heavy is lazy: the fastembed import and the model load happen only on
    the first embed_documents()/embed_query(), the model is shared per process (mirrors
    KokoroEngine._shared), and a missing fastembed / model degrades the engine to
    available=False so SemanticIndex falls back to keyword search. e5 REQUIRES instruction
    prefixes - 'passage: ' for documents, 'query: ' for queries - applied HERE, never by
    the caller. Defaults to e5-base (better quality); e5-small is reachable via the
    constants above for low-RAM machines (swap MODEL_ID + dim against a fresh db)."""

    name = "e5-base"
    dim = E5_BASE_DIM
    MODEL_ID = E5_BASE_MODEL_ID

    # One fastembed model per process - it is large and slow to load (mirrors KokoroEngine).
    _shared = None            # the loaded fastembed TextEmbedding, or False if it failed
    _shared_key = None        # the MODEL_ID the shared session was built for

    def __init__(self, model_dir: Optional[Path] = None) -> None:
        self.model_dir = Path(model_dir) if model_dir else None
        self.available = self._probe()

    def _probe(self) -> bool:
        """True only if fastembed is importable (the model itself downloads lazily).

        Cheap - it does not load or download the model - so the engine is advertised
        whenever the dep is installed; the first embed call does the heavy work."""
        try:
            import fastembed  # noqa: F401
        except Exception:
            return False
        return True

    def _model(self):
        """Load (and cache, per process) the fastembed e5 model, or None on any failure."""
        key = self.MODEL_ID
        if E5Embedder._shared is not None and E5Embedder._shared_key == key:
            return E5Embedder._shared or None
        try:
            from fastembed import TextEmbedding

            kwargs = {"model_name": self.MODEL_ID}
            if self.model_dir is not None:
                kwargs["cache_dir"] = str(self.model_dir)
            model = TextEmbedding(**kwargs)
        except Exception:
            E5Embedder._shared = False        # remember the failure; don't retry
            E5Embedder._shared_key = key
            return None
        E5Embedder._shared = model
        E5Embedder._shared_key = key
        return model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Run the model over already-prefixed texts, returning L2-normalized vectors.

        Returns [] on any failure so callers degrade rather than crash."""
        model = self._model()
        if model is None:
            return []
        try:
            out = []
            for vec in model.embed(texts):
                # fastembed yields numpy arrays; coerce to plain floats and normalize.
                out.append(_l2_normalize([float(x) for x in vec]))
            return out
        except Exception:
            return []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # e5 documents/passages MUST be prefixed with 'passage: '.
        return self._embed([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        # e5 queries MUST be prefixed with 'query: '.
        vecs = self._embed([f"query: {text}"])
        return vecs[0] if vecs else []


# --------------------------------------------------------------------------- #
# Storage: one VectorStore surface, two interchangeable backends chosen at open.
# --------------------------------------------------------------------------- #

class VectorStore:
    """Per-note vectors keyed on (note_id, content_hash). One surface, two backends.

    FAST PATH (sqlite-vec): on open, attempt to load the native extension; on success
    backend == 'sqlite-vec' and query() runs the vec0 KNN. FALLBACK (pure Python): when
    the extension is unavailable (the stock CPython sqlite3 often disables it) or the
    import/load fails, backend == 'python' and query() loads all vectors and computes
    cosine similarity in Python. Vectors are L2-normalized at upsert, so cosine == dot
    product. The python path is O(n) over notes - fine for a personal vault of
    hundreds-to-thousands of notes; do not prematurely optimize. content_hash is stored
    beside each vector so needs_embed() is a single PK lookup + string compare. `dim` is
    fixed at creation (taken from the embedder); mixing dims is rejected. SemanticIndex
    never branches on backend - both paths share upsert/needs_embed/query/prune/hashes."""

    def __init__(self, db_path: Optional[Path] = None, dim: int = 0) -> None:
        import sqlite3

        self.dim = int(dim)
        # None / ":memory:" -> an in-RAM db (used by the tests); else a file on disk.
        if db_path is None or str(db_path) == ":memory:":
            self._path = ":memory:"
        else:
            self._path = str(db_path)
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self.backend = self._init_backend()

    def _init_backend(self) -> str:
        """Try the sqlite-vec fast path; fall back to the pure-Python schema. Returns backend id."""
        if self._try_sqlite_vec():
            # distance_metric=cosine so the vec0 KNN returns COSINE distance (1 - cosine),
            # not the default L2/Euclidean. _query_vec then converts that to a cosine
            # similarity in [-1,1] - matching the pure-Python dot-product path exactly, so
            # both backends honour query()'s "cosine-similarity-like, higher == closer"
            # contract and absolute thresholds (e.g. dedup.DUP_COSINE) mean the same thing
            # on either backend. Without this, sqlite-vec would default to L2 and an absolute
            # cosine threshold would reject every pair.
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0("
                f"embedding float[{self.dim}] distance_metric=cosine)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS note_meta("
                "note_id TEXT PRIMARY KEY, content_hash TEXT, rowid INTEGER)"
            )
            self._conn.commit()
            return "sqlite-vec"
        # Pure-Python cosine fallback: a plain table of packed float vectors.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors("
            "note_id TEXT PRIMARY KEY, content_hash TEXT, vec BLOB)"
        )
        self._conn.commit()
        return "python"

    def _try_sqlite_vec(self) -> bool:
        """Load the native sqlite-vec extension into this connection, or False if absent.

        Heavy import is lazy and every failure path (extension loading disabled, package
        not installed, load error) degrades to the pure-Python fallback."""
        try:
            self._conn.enable_load_extension(True)
        except Exception:
            return False
        try:
            import sqlite_vec
            sqlite_vec.load(self._conn)
        except Exception:
            try:
                self._conn.enable_load_extension(False)
            except Exception:
                pass
            return False
        return True

    # -- pack/unpack for the python fallback --------------------------------- #

    @staticmethod
    def _pack(vector: list[float]) -> bytes:
        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def _unpack(blob: bytes) -> list[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"<{n}f", blob))

    def _check_dim(self, vector: list[float]) -> None:
        if self.dim and len(vector) != self.dim:
            raise ValueError(
                f"vector dim {len(vector)} != store dim {self.dim} (mixing dims is rejected)"
            )

    # -- the shared surface -------------------------------------------------- #

    def upsert(self, note_id: str, content_hash: str, vector: list[float]) -> None:
        """Insert / overwrite the vector + hash for a note (invalidate-on-change: the PK
        upsert replaces a stale vector). Vectors are stored L2-normalized by the embedder."""
        self._check_dim(vector)
        if self.backend == "sqlite-vec":
            self._upsert_vec(note_id, content_hash, vector)
        else:
            self._conn.execute(
                "INSERT INTO vectors(note_id, content_hash, vec) VALUES(?,?,?) "
                "ON CONFLICT(note_id) DO UPDATE SET content_hash=excluded.content_hash, "
                "vec=excluded.vec",
                (note_id, content_hash, self._pack(vector)),
            )
            self._conn.commit()

    def _upsert_vec(self, note_id: str, content_hash: str, vector: list[float]) -> None:
        import json
        cur = self._conn.execute(
            "SELECT rowid FROM note_meta WHERE note_id=?", (note_id,))
        row = cur.fetchone()
        emb = json.dumps(vector)
        if row is not None:
            rowid = row[0]
            self._conn.execute(
                "UPDATE vec_notes SET embedding=? WHERE rowid=?", (emb, rowid))
            self._conn.execute(
                "UPDATE note_meta SET content_hash=? WHERE note_id=?",
                (content_hash, note_id))
        else:
            cur = self._conn.execute(
                "INSERT INTO vec_notes(embedding) VALUES(?)", (emb,))
            rowid = cur.lastrowid
            self._conn.execute(
                "INSERT INTO note_meta(note_id, content_hash, rowid) VALUES(?,?,?)",
                (note_id, content_hash, rowid))
        self._conn.commit()

    def needs_embed(self, note_id: str, content_hash: str) -> bool:
        """True when this note is new or its content changed - i.e. it must be re-embedded.

        False (the cache hit) when a row with the SAME hash already exists, so the caller
        skips embedding it. A single PK lookup + string compare."""
        if self.backend == "sqlite-vec":
            cur = self._conn.execute(
                "SELECT content_hash FROM note_meta WHERE note_id=?", (note_id,))
        else:
            cur = self._conn.execute(
                "SELECT content_hash FROM vectors WHERE note_id=?", (note_id,))
        row = cur.fetchone()
        return row is None or row[0] != content_hash

    def hashes(self) -> dict[str, str]:
        """note_id -> stored content_hash for every vector currently in the store."""
        table = "note_meta" if self.backend == "sqlite-vec" else "vectors"
        cur = self._conn.execute(f"SELECT note_id, content_hash FROM {table}")
        return {nid: h for nid, h in cur.fetchall()}

    def prune(self, keep_ids: set[str]) -> None:
        """Drop vectors for notes not in `keep_ids` (invalidate-on-delete / gone notes)."""
        if self.backend == "sqlite-vec":
            cur = self._conn.execute("SELECT note_id, rowid FROM note_meta")
            for nid, rowid in cur.fetchall():
                if nid not in keep_ids:
                    self._conn.execute("DELETE FROM vec_notes WHERE rowid=?", (rowid,))
                    self._conn.execute("DELETE FROM note_meta WHERE note_id=?", (nid,))
        else:
            cur = self._conn.execute("SELECT note_id FROM vectors")
            for (nid,) in cur.fetchall():
                if nid not in keep_ids:
                    self._conn.execute("DELETE FROM vectors WHERE note_id=?", (nid,))
        self._conn.commit()

    def query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        """The top_k nearest notes to `vector` as (note_id, score) descending by score.

        Scores are cosine-similarity-like in [-1, 1]-ish, higher == closer. top_k <= 0
        returns []; top_k larger than the corpus returns the whole corpus."""
        if top_k <= 0:
            return []
        self._check_dim(vector)
        if self.backend == "sqlite-vec":
            return self._query_vec(vector, top_k)
        return self._query_python(vector, top_k)

    def _query_vec(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        import json
        cur = self._conn.execute(
            "SELECT vec_notes.rowid, distance FROM vec_notes "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (json.dumps(vector), top_k),
        )
        rows = cur.fetchall()
        # Map rowids back to note ids; convert cosine DISTANCE to cosine SIMILARITY. With the
        # table declared distance_metric=cosine, vec0 returns cosine distance (1 - cosine), so
        # similarity == 1 - distance, in [-1,1], higher == closer - identical to the
        # pure-Python dot-product path. Ordering is preserved (distance ASC == similarity DESC).
        meta = {rowid: nid for nid, rowid in
                self._conn.execute("SELECT note_id, rowid FROM note_meta").fetchall()}
        out: list[tuple[str, float]] = []
        for rowid, distance in rows:
            nid = meta.get(rowid)
            if nid is None:
                continue
            out.append((nid, 1.0 - float(distance)))
        return out

    def _query_python(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        # O(n) over the vault: load every vector, dot it (vectors are L2-normalized, so
        # the dot product equals cosine similarity), sort desc, return top_k. Fine for a
        # personal vault of hundreds-to-thousands of notes - do not prematurely optimize.
        scored: list[tuple[str, float]] = []
        for note_id, blob in self._conn.execute(
                "SELECT note_id, vec FROM vectors").fetchall():
            v = self._unpack(blob)
            score = sum(a * b for a, b in zip(vector, v))
            scored.append((note_id, score))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    def close(self) -> None:
        """Close the underlying connection (a no-op if already closed)."""
        try:
            self._conn.close()
        except Exception:
            pass
