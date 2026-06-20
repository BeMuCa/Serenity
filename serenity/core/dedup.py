"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: On-demand near-duplicate / fragment detection + a safe, recoverable merge.
Role:    Backs the Notes tab "Find duplicates" maintenance action (Job 3). Pure Python,
         no Qt. Scans the active note vault for pairs that are NEAR-DUPLICATES (almost the
         same content) or FRAGMENTS (a shorter note whose tokens are largely contained in a
         longer one), then lets the UI MERGE a pair safely (append body, union tags,
         soft-delete the dropped note - Trash is the undo, NEVER purged).

         Two duplicate-detection paths share one entry point: the Job-14 embedding index
         (cosine via SemanticIndex.neighbours) when a model is wired, degrading to a
         deterministic token-set Jaccard otherwise. FRAGMENT detection is ALWAYS the
         deterministic token-containment method (containment is poorly captured by cosine),
         so it runs in both paths. The degrade (token) path is first-class - it is the path
         that runs in this env / on the user's machine today - never a "Phase 2" dead-end.
         Reuses search._tokens/_haystack/_sort_ts; adds no new tokenizer.

Functions:
- find_duplicates(notes, index=None, limit=MAX_SUGGESTIONS) -> list[DupPair] - the scan
- default_keep(a, b) -> str - which id to keep by default (longer body, then more-recent)
- merge_notes(store, keep_id, drop_id) -> Note - safe + recoverable merge

Classes:
- DupPair - a suggested pair: a_id, b_id, kind ("duplicate"|"fragment"), score
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Note
from .search import _haystack, _sort_ts, _tokens

# --------------------------------------------------------------------------- #
# Threshold constants (named; tuned for the bag-of-tokens StubEmbedder + token path).
# --------------------------------------------------------------------------- #
DUP_COSINE = 0.92          # embedding path: cosine >= this -> 'duplicate'
DUP_JACCARD = 0.80         # token degrade path: token-set Jaccard >= this -> 'duplicate'
FRAGMENT_CONTAINMENT = 0.80  # shorter note's tokens this-fraction-in-longer -> 'fragment'
FRAGMENT_MIN_TOKENS = 5    # ignore tiny notes as fragments (too noisy / spurious overlap)
FRAGMENT_MAX_RATIO = 0.75  # shorter must have < this fraction of longer's distinct tokens
#                            (must be genuinely shorter, else it is a duplicate not a fragment)
MAX_SUGGESTIONS = 30       # cap on returned pairs (narrow dock; sane top-N)
DUP_NEIGHBOURS = 10        # k per note for the embedding-path KNN candidate generation

MERGE_SEPARATOR = "\n\n---\n\n"  # clear visual break between the two bodies in markdown


@dataclass(frozen=True)
class DupPair:
    """A suggested near-duplicate / fragment pair (unordered for 'duplicate').

    For kind == "fragment", a_id is ALWAYS the longer (kept-by-default) note and b_id the
    shorter (the fragment), so the UI can label "B looks like part of A". For kind ==
    "duplicate" the id order is canonicalized (sorted) so the same pair has a single key.
    score is the cosine / Jaccard for a duplicate, or the containment ratio for a fragment."""

    a_id: str
    b_id: str
    kind: str          # "duplicate" | "fragment"
    score: float


def find_duplicates(notes: list[Note], index=None, limit: int = MAX_SUGGESTIONS) -> list[DupPair]:
    """Scan active notes for near-duplicate / fragment pairs.

    `index` is a phase2_stubs.SemanticIndex or None.
    - active = non-deleted notes; if fewer than 2, return [] (no crash on empty/one-note).
    - DUPLICATE: the embedding path (cosine via index.neighbours) when index.available AND
      its store is populated; otherwise the deterministic token-set Jaccard path. The token
      path is the one that runs in this env / on the user's machine today.
    - FRAGMENT: ALWAYS the deterministic token-containment path (runs in both paths).
    - Pairs are deduped by their canonical undirected key; if a pair qualifies as BOTH, the
      'duplicate' entry wins (stronger relationship) and the fragment entry is dropped.
    - Sorted by score desc, then a stable (a_id, b_id) tiebreak, and capped at `limit`."""
    active = [n for n in notes if not n.deleted]
    if len(active) < 2:
        return []

    # Precompute per-note token SETS once (one pass; reused by both checks). Whole-document
    # tokens (title + tags + body via _haystack), consistent with related_notes.
    toks: dict[str, set] = {n.id: set(_tokens(_haystack(n))) for n in active}

    # DUPLICATE detection. Both paths are O(n^2) over the vault at worst - fine for a
    # personal vault of hundreds; the semantic path uses KNN to AVOID the full pairwise
    # embedding compare but still falls within that bound.
    if index is not None and getattr(index, "available", False):
        dup_pairs = _duplicate_pairs_semantic(active, index)
        # DEGRADE WITHIN THE SEMANTIC PATH: an available index over an empty / unindexed
        # store (or a model that failed to load) yields no neighbours, so we would silently
        # lose duplicates. Detect that case (no neighbours for the whole vault) and fall
        # through to the deterministic token path. NotesView indexes before opening the
        # dialog, so normally the store IS populated and this fall-through is not hit.
        if not dup_pairs and not _index_populated(index):
            dup_pairs = _duplicate_pairs_tokens(active, toks)
    else:
        dup_pairs = _duplicate_pairs_tokens(active, toks)

    frag_pairs = _fragment_pairs(active, toks)

    # Merge + dedup by canonical undirected key; 'duplicate' wins over 'fragment'.
    by_key: dict[frozenset, DupPair] = {}
    for p in dup_pairs:
        by_key[frozenset((p.a_id, p.b_id))] = p
    for p in frag_pairs:
        key = frozenset((p.a_id, p.b_id))
        if key not in by_key:          # a duplicate entry already won this pair
            by_key[key] = p

    out = list(by_key.values())
    # Sort purely by score desc, then a stable (a_id, b_id) tiebreak (deterministic).
    out.sort(key=lambda p: (-p.score, p.a_id, p.b_id))
    return out[: max(0, int(limit))]


def _index_populated(index) -> bool:
    """True if the embedding store holds any vectors (store is populated).

    Cheap check via SemanticIndex.is_populated() (one SELECT, NO embed). Used only to decide
    whether an empty semantic result is a real 'no duplicates' answer or an unindexed store
    that should degrade to the token path. Avoids the wasted embed_query a neighbours() probe
    would cost on the common no-duplicates outcome."""
    try:
        return bool(index.is_populated())
    except Exception:
        return False


def _duplicate_pairs_tokens(active: list[Note], toks: dict[str, set]) -> list[DupPair]:
    """Deterministic near-duplicate detection via token-set Jaccard (degrade path).

    This is also the path that runs in THIS env / the user's machine today (no model)."""
    out: list[DupPair] = []
    # O(n^2): visit every unordered pair once (i < j). Fine for a personal vault of hundreds.
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            ta, tb = toks[a.id], toks[b.id]
            if not ta or not tb:
                continue
            union = len(ta | tb)
            if union == 0:
                continue
            jac = len(ta & tb) / union
            if jac >= DUP_JACCARD:
                ka, kb = sorted((a.id, b.id))   # canonical id order for 'duplicate'
                out.append(DupPair(ka, kb, "duplicate", jac))
    return out


def _duplicate_pairs_semantic(active: list[Note], index) -> list[DupPair]:
    """Near-duplicate detection via the Job-14 embedding KNN (used only when available).

    For each note ask index.neighbours() for the DUP_NEIGHBOURS nearest OTHER notes WITH
    scores; keep pairs whose cosine score >= DUP_COSINE. The same pair surfaces from both
    ends, so dedup by canonical key. Per-note KNN keeps this within the O(n^2) bound while
    avoiding a full pairwise embedding compare."""
    seen: set = set()
    out: list[DupPair] = []
    active_ids = {n.id for n in active}
    for n in active:
        for other_id, score in index.neighbours(n, top_k=DUP_NEIGHBOURS):
            if other_id == n.id or other_id not in active_ids:
                continue
            if score < DUP_COSINE:
                continue
            ka, kb = sorted((n.id, other_id))
            key = (ka, kb)
            if key in seen:
                continue
            seen.add(key)
            out.append(DupPair(ka, kb, "duplicate", float(score)))
    return out


def _fragment_pairs(active: list[Note], toks: dict[str, set]) -> list[DupPair]:
    """Deterministic fragment detection via token containment (runs in BOTH paths).

    A 'fragment' is a genuinely-shorter note whose distinct tokens are highly contained in a
    longer note. Containment is poorly captured by cosine, so this is always token-based."""
    out: list[DupPair] = []
    # O(n^2): every unordered pair once (i < j). Fine for a personal vault of hundreds.
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            ta, tb = toks[a.id], toks[b.id]
            # Order by distinct-token count: longer = more tokens, shorter = fewer.
            if len(ta) >= len(tb):
                longer, shorter, lt, st = a, b, ta, tb
            else:
                longer, shorter, lt, st = b, a, tb, ta
            if len(st) < FRAGMENT_MIN_TOKENS:       # too small to judge
                continue
            if not lt:
                continue
            if len(st) >= FRAGMENT_MAX_RATIO * len(lt):  # not genuinely shorter -> dup territory
                continue
            contained = len(st & lt) / len(st)      # fraction of shorter inside longer
            if contained >= FRAGMENT_CONTAINMENT:
                # a_id ALWAYS the longer (kept-by-default), b_id the shorter (the fragment).
                out.append(DupPair(longer.id, shorter.id, "fragment", contained))
    return out


def default_keep(a: Note, b: Note) -> str:
    """Which id to keep by default: the LONGER body, tie-broken by more-recently-updated.

    Returns the kept note's id. The UI may override this choice."""
    la, lb = len(a.body or ""), len(b.body or "")
    if la != lb:
        return a.id if la > lb else b.id
    # _sort_ts is negative-epoch, so the SMALLER value is the more-recently-updated note.
    return a.id if _sort_ts(a) <= _sort_ts(b) else b.id


def merge_notes(store, keep_id: str, drop_id: str) -> Note:
    """Merge two notes safely + recoverably, returning the updated kept Note.

    Appends the dropped note's body into the kept note under a clear separator, unions their
    tags (case-insensitive, keeping the kept note's order), keeps the kept note's color/pin/
    title, calls store.update(keep), then store.soft_delete(drop_id) - Trash IS the undo, the
    dropped note is NEVER purged (recoverable via NoteStore.restore). Raises ValueError if
    keep_id == drop_id or either note is missing (defensive; the UI never sends bad ids)."""
    if keep_id == drop_id:
        raise ValueError("cannot merge a note into itself")
    keep = store.get(keep_id)
    drop = store.get(drop_id)
    if keep is None or drop is None:
        raise ValueError("note not found")

    # Body: append the dropped body under a clear separator (no trailing separator when the
    # dropped body is empty).
    dropped_body = (drop.body or "").strip()
    if dropped_body:
        base = (keep.body or "").rstrip()
        keep.body = (base + MERGE_SEPARATOR + dropped_body) if base else dropped_body

    # Tags: union, preserving the kept note's order then appending new ones from drop
    # (case-insensitive de-dup).
    seen = {t.lower() for t in keep.tags}
    for t in drop.tags:
        if t.lower() not in seen:
            keep.tags.append(t)
            seen.add(t.lower())

    # color / pinned / title stay the kept note's (untouched).
    store.update(keep)            # writes the .md + reindexes (and bumps keep.updated)
    store.soft_delete(drop_id)    # -> Trash, RECOVERABLE via NoteStore.restore (never purge)
    return keep
