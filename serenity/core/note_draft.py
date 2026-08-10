"""
============================================================
Author:  Berk
Created: 2026-06-27
Purpose: Qt-free draft / commit / recover / validate / external-change logic for
         the Notes-expand pop-out editor (the heart of the feature).
Role:    The fail-safe core behind serenity/ui/note_editor_panel.py. All decisions
         are CONTENT-keyed (never mtime) and the durable .md write is the sole commit
         point; the UI only renders the outcomes these functions return/raise. Pairs
         with note_store.serialize/parse_markdown and core.paths.atomic_write_text.

Functions:
- draft_path(md_path) -> str                     - the sibling "<md>.draft" path
- build_draft_text(fm_text, body_text) -> str    - single-sourced draft serialization (P1-6)
- content_hash(text) -> str                       - blake2b digest of whole .md text (P2-8)
- _norm(md_text) -> str                           - normalize .md for content compare
- validate(fm_text, loaded_note) -> dict          - strict commit gate (P1-1/5, P2-6/7)
- write_draft(md_path, fm_text, body_text) -> bool - atomic draft write, never raises (P2-5)
- discard(md_path) -> None                        - unlink draft; real OSError propagates (P2-4)
- recover(md_path) -> RecoverResult               - total, content-keyed open-time decision (P1-2/3, P2-1/11)
- detect_external_change(md_path, baseline_hash) -> str - unchanged|changed|source_missing (P2-8/9)
- promote(store, note_id, fm_text, body_text, fm_edited) -> Note - commit orchestration (spec 3.1)

Classes:
- RecoverResult        - dataclass: status / draft_text / disk_diverged
- NoteDraftInvalid     - raised by validate() on a bad/invalid front-matter
- NoteSourceMissing    - raised by promote() when the .md was purged under the panel
- NoteWriteFailed      - raised by promote() when the durable .md write itself fails
============================================================
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .models import _parse_iso
from .note_store import parse_markdown, serialize
from .paths import atomic_write_text


class NoteDraftInvalid(Exception):
    """Front-matter failed the strict commit gate (bad YAML / shape / immutable id)."""


class NoteSourceMissing(Exception):
    """The note's .md was purged/deleted under the panel; cannot promote in place."""


class NoteWriteFailed(Exception):
    """The durable .md write itself failed (lock/permission); the draft is kept."""


# --------------------------------------------------------------------------- #
# Task 1 — serialization primitives
# --------------------------------------------------------------------------- #
def draft_path(md_path: str) -> str:
    return md_path + ".draft"


def build_draft_text(front_matter_text: str, body_text: str) -> str:
    """Combine the live FM text and the live body text into the canonical .md shape.

    The fm half is sourced ONLY from front_matter_text and the body half ONLY from
    body_text, so a draft can never cross one pane from the loaded Note and the other
    from a widget (P1-6). The raw fm text is kept verbatim — validate(), not this
    serializer, is the gate.
    """
    return f"---\n{front_matter_text.strip()}\n---\n\n{body_text.strip()}\n"


def content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8")).hexdigest()


def _norm(md_text: str) -> str:
    """Normalize an .md text for content comparison.

    Parse then re-serialize so YAML key-order/whitespace can't produce a false diff;
    fall back to a plain strip if it has no parseable front-matter.
    """
    fm, body = parse_markdown(md_text)
    if not fm:
        return md_text.strip()
    front = yaml.safe_dump(fm, sort_keys=True, allow_unicode=True).strip()
    return f"{front}\n\n{body.strip()}"


# --------------------------------------------------------------------------- #
# Task 2 — the strict commit gate
# --------------------------------------------------------------------------- #
def validate(front_matter_text: str, loaded_note) -> dict:
    """Strict commit-time validator — stricter than parse_markdown's silent coercion.

    Returns the parsed fm dict on success; raises NoteDraftInvalid otherwise. Does NOT
    route through parse_markdown (which silently coerces and would defeat the gate).
    """
    try:
        fm = yaml.safe_load(front_matter_text)
    except yaml.YAMLError as e:
        raise NoteDraftInvalid(f"Invalid YAML front-matter: {e}") from e
    if not isinstance(fm, dict):
        raise NoteDraftInvalid("Front-matter must be a YAML mapping.")

    # id is immutable (P1-5, P2-17)
    if "id" not in fm or fm.get("id") is None:
        raise NoteDraftInvalid("Front-matter must keep the 'id' field.")
    if fm["id"] != loaded_note.id:
        raise NoteDraftInvalid("The 'id' field is immutable and cannot be changed.")

    # tags: list of str (P2-7)
    if "tags" in fm and fm["tags"] is not None:
        tags = fm["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise NoteDraftInvalid("'tags' must be a list of strings.")

    # pinned/deleted: bool (P2-7). yaml.safe_load already types real booleans as bool.
    for key in ("pinned", "deleted"):
        if key in fm and fm[key] is not None and not isinstance(fm[key], bool):
            raise NoteDraftInvalid(f"'{key}' must be true or false.")

    # Phase C stamps (R8): context is a closed vocabulary; state_tag any string or null.
    if "context" in fm and fm["context"] is not None and fm["context"] not in ("business", "private"):
        raise NoteDraftInvalid("'context' must be business, private or null.")
    if "state_tag" in fm and fm["state_tag"] is not None and not isinstance(fm["state_tag"], str):
        raise NoteDraftInvalid("'state_tag' must be a string or null.")

    # created/updated: present, non-empty -> must be ISO; dropped created -> restore (P2-6)
    for key in ("created", "updated"):
        if key in fm and fm[key]:
            if _parse_iso(str(fm[key])) is None:
                raise NoteDraftInvalid(f"'{key}' must be an ISO datetime.")
    if not fm.get("created") and loaded_note.created is not None:
        fm["created"] = loaded_note.created.isoformat()

    return fm


# --------------------------------------------------------------------------- #
# Task 3 — write_draft / discard / recover
# --------------------------------------------------------------------------- #
def write_draft(md_path: str, front_matter_text: str, body_text: str) -> bool:
    """Atomic-write the draft sidecar. Returns True/False; never raises (P2-5)."""
    try:
        atomic_write_text(Path(draft_path(md_path)), build_draft_text(front_matter_text, body_text))
        return True
    except OSError:
        return False


def discard(md_path: str) -> None:
    """Unlink the draft. A missing draft is a no-op success; a real OSError propagates (P2-4)."""
    Path(draft_path(md_path)).unlink(missing_ok=True)


@dataclass
class RecoverResult:
    status: str                      # "none" | "recoverable"
    draft_text: Optional[str] = None


def recover(md_path: str) -> RecoverResult:
    """Total, content-keyed open-time decision (never mtime) — P1-2/3, P2-1/11.

    no draft -> none; draft but .md absent -> discard orphan, none (never resurrect);
    draft content == .md content (normalized) -> silent discard, none (crash-after-commit);
    else -> recoverable (carry the draft text). A locked/unreadable draft or .md returns
    none rather than raising, so opening the panel never throws (P2-11).
    """
    dpath = Path(draft_path(md_path))
    try:
        draft_text = dpath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return RecoverResult(status="none")
    except OSError:
        # draft locked/unreadable -> nothing we can safely offer
        return RecoverResult(status="none")

    try:
        md_text = Path(md_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        # .md gone (purged/deleted) -> discard the orphan, never recreate the note
        discard(md_path)
        return RecoverResult(status="none")
    except OSError:
        # .md present but locked/unreadable -> don't decide, don't destroy the draft
        return RecoverResult(status="none")

    if _norm(draft_text) == _norm(md_text):
        discard(md_path)
        return RecoverResult(status="none")

    return RecoverResult(status="recoverable", draft_text=draft_text)


# --------------------------------------------------------------------------- #
# Task 4 — detect_external_change
# --------------------------------------------------------------------------- #
def detect_external_change(md_path: str, baseline_hash: str) -> str:
    """Re-read .md, compare content_hash to the load-time baseline. Never raises (P2-8/9).

    Returns "unchanged" | "changed" | "source_missing".
    """
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except OSError:
        return "source_missing"
    return "unchanged" if content_hash(text) == baseline_hash else "changed"


# --------------------------------------------------------------------------- #
# Task 5 — promote orchestration (spec 3.1 steps 1-6)
# --------------------------------------------------------------------------- #
def promote(store, note_id: str, front_matter_text: str, body_text: str, fm_edited: bool):
    """Commit the draft to the durable .md (the sole commit point). Spec 3.1 steps 1-6.

    Raises NoteDraftInvalid (bad fm), NoteSourceMissing (.md purged under us), or
    NoteWriteFailed (durable write failed — draft kept). On success returns the
    committed Note and deletes the draft LAST.
    """
    # 1. strict gate
    live = store.get(note_id)
    fm = validate(front_matter_text, live) if live is not None else None

    # 2. store-state guard
    if live is None:
        raise NoteSourceMissing(f"Note {note_id} no longer exists in the store.")

    # 3. field-merge (panel owns body; store owns metadata unless the user edited fm)
    live.body = body_text
    if fm_edited:
        if "title" in fm:
            live.title = fm["title"]
        if "tags" in fm:
            live.tags = list(fm["tags"] or [])
        if "color" in fm and fm["color"]:
            live.color = fm["color"]
        if "pinned" in fm:
            live.pinned = bool(fm["pinned"])
        if "deleted" in fm:
            live.deleted = bool(fm["deleted"])
        # created is user-meaningful; validate() restored a dropped one, so it's present here.
        if fm.get("created"):
            parsed = _parse_iso(str(fm["created"]))
            if parsed is not None:
                live.created = parsed
        # Phase C stamps (R8): an fm edit persists like an external-editor edit would;
        # a missing key keeps the live value, an explicit null clears the stamp.
        if "state_tag" in fm:
            live.state_tag = fm["state_tag"] or None
        if "context" in fm:
            live.context = fm["context"] or None
    # else: pinned/color/tags untouched on `live` (already the store's values).
    # deleted is preserved from `live` in both paths (never silently un-trashed).

    # 4. corrupt-original backup: if the on-disk .md has a FM fence but no usable id
    #    and we're about to write a different id, preserve the original bytes first.
    try:
        on_disk = Path(live.path).read_text(encoding="utf-8")
    except OSError:
        on_disk = None
    if on_disk is not None and on_disk.lstrip().startswith("---"):
        disk_fm, _ = parse_markdown(on_disk)
        if not disk_fm.get("id") and live.id:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                os.rename(live.path, f"{live.path}.corrupt-{ts}")
            except OSError as e:
                # the backup must succeed before we overwrite; a locked .md keeps the draft.
                raise NoteWriteFailed(str(e)) from e

    # 5. durable write is the sole commit point. Only an atomic_write_text OSError is
    #    fatal -> NoteWriteFailed (keep the draft). The index/db.commit step is a
    #    disposable cache that self-heals on the next reindex, so a non-OSError raised
    #    after the .md is written (e.g. an index failure) is logged-and-continued (P3-1).
    try:
        store.update(live)
    except OSError as e:
        raise NoteWriteFailed(str(e)) from e
    except Exception:
        pass  # index step failed; the durable .md write already succeeded

    # 6. delete the draft LAST (after a successful durable write)
    discard(live.path)
    return live
