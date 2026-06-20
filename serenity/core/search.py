"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Keyword ("Text") search over notes; ordering (pinned + recent-first).
Role:    Powers the Notes tab list + search box. Phase-1 = literal token match.
         "Meaning" (semantic) search delegates to a SemanticIndex and degrades to
         keyword search when no embedder/index is available (see semantic_search).

Functions:
- keyword_search(notes, query) -> list[Note] - literal token match, scored
- order_notes(notes) -> list[Note] - pinned first, then most-recently-updated
- semantic_search(notes, query, index=None) -> list[Note] - delegate to a SemanticIndex,
  degrade to keyword_search when the index is None / unavailable / empty
============================================================
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import Note

_TOKEN_RE = re.compile(r"[\wäöüÄÖÜß]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _haystack(note: Note) -> str:
    return " ".join([note.title, " ".join(note.tags), note.body]).lower()


def keyword_search(notes: list[Note], query: str) -> list[Note]:
    """Literal token match across title, tags and body.

    A note matches when every query token appears as a substring of the note's
    text. Results are scored (title hits weigh more) then ordered by score, then
    by the standard pinned/recent ordering."""
    q = (query or "").strip()
    if not q:
        return order_notes(notes)
    qtokens = _tokens(q)
    if not qtokens:
        return order_notes(notes)

    scored: list[tuple[float, Note]] = []
    for n in notes:
        if n.deleted:
            continue
        title = n.title.lower()
        body_tags = (n.body + " " + " ".join(n.tags)).lower()
        if not all((tok in title) or (tok in body_tags) for tok in qtokens):
            continue
        score = 0.0
        for tok in qtokens:
            score += title.count(tok) * 3.0
            score += body_tags.count(tok) * 1.0
        if n.pinned:
            score += 0.5
        scored.append((score, n))

    scored.sort(key=lambda x: (-x[0], _sort_ts(x[1])))
    return [n for _, n in scored]


def _sort_ts(note: Note) -> float:
    """Negative epoch so most-recent sorts first in an ascending sort."""
    dt = note.updated or note.created or datetime.min
    return -dt.timestamp() if dt != datetime.min else 0.0


def order_notes(notes: list[Note]) -> list[Note]:
    """Pinned section first, then most-recently-updated. Excludes deleted notes."""
    active = [n for n in notes if not n.deleted]
    active.sort(key=lambda n: (0 if n.pinned else 1, _sort_ts(n)))
    return active


def semantic_search(notes: list[Note], query: str, index=None) -> list[Note]:
    """Semantic 'Meaning' search via e5 embeddings + sqlite-vec, delegating to a SemanticIndex.

    The single decision point for Meaning mode, and the documented degrade path the UI's
    'Meaning ... showing Text matches' notice already promises:

    - `index` is None OR not index.available -> return keyword_search(notes, query)
      (Phase 1 / no embedding model bundled);
    - else ask the index for its ranking and RE-PROJECT it onto the passed-in `notes`:
      filter deleted notes, keep only ids present in `notes`, preserve the index's order;
    - if the index returns nothing (empty corpus / not yet indexed) -> keyword_search too.

    `index` is a parameter so this stays injectable: tests pass a StubEmbedder-backed
    SemanticIndex and the app passes the e5-backed one."""
    if index is None or not getattr(index, "available", False):
        return keyword_search(notes, query)

    ranked = index.search(query, top_k=len(notes) or 10)
    if not ranked:
        return keyword_search(notes, query)

    by_id = {n.id: n for n in notes if not n.deleted}
    out: list[Note] = []
    for r in ranked:
        n = by_id.get(r.id)
        if n is not None:
            out.append(n)
    return out if out else keyword_search(notes, query)
