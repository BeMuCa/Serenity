"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Notes-as-files: one markdown file per note (YAML front-matter is truth).
Role:    Backs the Notes tab + Trash tab. The filesystem is authoritative; a small
         SQLite index gives fast listing/search. On open it (re)builds the index by
         scanning the notes folder, so notes edited outside the app are picked up.

Functions:
- NoteStore(vault_dir) - opens <vault>/notes/ + <config>/index.sqlite (or in-vault)
- create(title, body, tags, color, pinned) -> Note  (writes the .md file)
- update(note) / set_pinned / set_color / soft_delete / restore / purge
- all_active() / trash() / search(query) - delegate ordering to core.search
- read_raw(note) -> str - the raw .md text for the file-view modal
- parse_markdown(text) / serialize(note) - front-matter (de)serialization
============================================================
"""

from __future__ import annotations

import random
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .models import NOTE_COLORS, Note, new_id
from .paths import atomic_write_text
from .search import keyword_search, order_notes

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def parse_markdown(text: str) -> tuple[dict, str]:
    """Split YAML front-matter from the markdown body."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, m.group(2)


def serialize(note: Note) -> str:
    fm = note.to_frontmatter()
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n{note.body.strip()}\n"


def _slug(title: str) -> str:
    s = _SLUG_RE.sub("-", (title or "note").lower()).strip("-")
    return s[:48] or "note"


class NoteStore:
    def __init__(self, vault_dir: Path, index_path: Optional[Path] = None):
        self.vault_dir = Path(vault_dir)
        self.notes_dir = self.vault_dir / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = Path(index_path) if index_path else (self.vault_dir / ".index.sqlite")
        self._db = sqlite3.connect(str(self.index_path))
        self._db.row_factory = sqlite3.Row
        self._init_db()
        self._notes: dict[str, Note] = {}
        self.reindex()

    def _init_db(self) -> None:
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS notes(
                id TEXT PRIMARY KEY, path TEXT, title TEXT, tags TEXT,
                color TEXT, pinned INTEGER, deleted INTEGER,
                created TEXT, updated TEXT, body TEXT)"""
        )
        self._db.commit()

    # --- index ---
    def reindex(self) -> None:
        """Filesystem is source of truth: scan the notes folder, rebuild the index."""
        self._notes.clear()
        self._db.execute("DELETE FROM notes")
        for md in sorted(self.notes_dir.glob("*.md")):
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, body = parse_markdown(text)
            note = Note.from_frontmatter(fm, body, str(md))
            if note.created is None:
                note.created = datetime.fromtimestamp(md.stat().st_ctime)
            if note.updated is None:
                note.updated = datetime.fromtimestamp(md.stat().st_mtime)
            self._notes[note.id] = note
            self._index_note(note)
        self._db.commit()

    def _index_note(self, note: Note) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                note.id, note.path, note.title, ",".join(note.tags), note.color,
                int(note.pinned), int(note.deleted),
                note.created.isoformat() if note.created else None,
                note.updated.isoformat() if note.updated else None,
                note.body,
            ),
        )

    # --- queries ---
    def get(self, note_id: str) -> Optional[Note]:
        return self._notes.get(note_id)

    def all_active(self) -> list[Note]:
        return order_notes(list(self._notes.values()))

    def trash(self) -> list[Note]:
        items = [n for n in self._notes.values() if n.deleted]
        items.sort(key=lambda n: (n.updated or n.created or datetime.min), reverse=True)
        return items

    def search(self, query: str) -> list[Note]:
        active = [n for n in self._notes.values() if not n.deleted]
        return keyword_search(active, query)

    def read_raw(self, note: Note) -> str:
        try:
            return Path(note.path).read_text(encoding="utf-8")
        except OSError:
            return serialize(note)

    # --- mutations (write the .md file, then re-index that note) ---
    def create(
        self,
        title: str,
        body: str = "",
        tags: Optional[list] = None,
        color: Optional[str] = None,
        pinned: bool = False,
    ) -> Note:
        now = datetime.now()
        note = Note(
            id=new_id(),
            title=title.strip() or "Untitled",
            tags=tags or [],
            color=color or random.choice(NOTE_COLORS),
            pinned=pinned,
            created=now,
            updated=now,
            body=body,
        )
        fname = f"{now.strftime('%Y-%m-%d')}-{_slug(note.title)}-{note.id[:6]}.md"
        note.path = str(self.notes_dir / fname)
        self._write(note)
        return note

    def update(self, note: Note) -> None:
        note.updated = datetime.now()
        self._write(note)

    def set_pinned(self, note_id: str, pinned: bool) -> Optional[Note]:
        n = self.get(note_id)
        if n:
            self._guarded_set(n, "pinned", pinned)
        return n

    def set_color(self, note_id: str, color: str) -> Optional[Note]:
        n = self.get(note_id)
        if n and color in NOTE_COLORS:
            self._guarded_set(n, "color", color)
        return n

    def soft_delete(self, note_id: str) -> Optional[Note]:
        n = self.get(note_id)
        if n:
            self._guarded_set(n, "deleted", True)
        return n

    def restore(self, note_id: str) -> Optional[Note]:
        n = self.get(note_id)
        if n:
            self._guarded_set(n, "deleted", False)
        return n

    def _guarded_set(self, note: Note, field: str, value) -> None:
        # mutate-after-success: flip the in-memory flag, persist; if the write raises
        # restore the prior value so memory never diverges from disk (no resurrect/vanish).
        prior = getattr(note, field)
        setattr(note, field, value)
        try:
            self.update(note)
        except OSError:
            setattr(note, field, prior)
            raise

    def reload_note(self, note_id: str) -> None:
        """Re-read the note's .md from disk -> refresh _notes[id] + its index row.

        Restores "the .md is the source of truth" after an outside-Serenity edit so a
        later in-app write can't serialize a stale note over the newer file. If the
        file is gone, drop both the in-memory entry and the index row.
        """
        n = self.get(note_id)
        if not n:
            return
        try:
            text = Path(n.path).read_text(encoding="utf-8")
        except OSError:
            self._notes.pop(note_id, None)
            self._db.execute("DELETE FROM notes WHERE id=?", (note_id,))
            self._db.commit()
            return
        fm, body = parse_markdown(text)
        note = Note.from_frontmatter(fm, body, n.path)
        if note.created is None:
            note.created = datetime.fromtimestamp(Path(n.path).stat().st_ctime)
        if note.updated is None:
            note.updated = datetime.fromtimestamp(Path(n.path).stat().st_mtime)
        self._notes[note.id] = note
        self._index_note(note)
        self._db.commit()

    def purge(self, note_id: str) -> None:
        n = self.get(note_id)
        if not n:
            return
        # unlink the .md FIRST; only drop the row/index if the file is actually gone.
        # If unlink fails (locked/permission) the file would otherwise be orphaned and
        # resurrected on the next reindex, so propagate instead of swallowing.
        Path(n.path).unlink(missing_ok=True)
        # also remove the sibling .draft so a stale draft can't resurrect the note (P1-3)
        Path(n.path + ".draft").unlink(missing_ok=True)
        self._notes.pop(note_id, None)
        self._db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        self._db.commit()

    def _write(self, note: Note) -> None:
        # atomic .md write FIRST (temp+os.replace) so a crash never leaves a torn file;
        # only on a successful write do we touch the in-memory map + index.
        atomic_write_text(Path(note.path), serialize(note))
        self._notes[note.id] = note
        self._index_note(note)
        self._db.commit()

    def close(self) -> None:
        self._db.close()
