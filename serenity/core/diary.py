"""
============================================================
Author:  Berk
Created: 2026-07-10
Purpose: Persist and mutate manual diary lines as a JSON document in the vault.
Role:    The Diary tab + Weekly Board diary section read/write through this.
         Holds the list of diary lines, handles add/edit/delete, and tolerates
         corrupt JSON and poison timestamps (P1-1: drop any line with ts=None).
         Also builds per-day span/item structures for the Weekly Board (T4).

Models:
- DiaryLine(id, ts, text, state_tag, context) - one diary entry
- DiaryItem(kind, text, ts, context) - derived: todo/note/diary item for display
- DiarySpan(category, start, end, items) - activity span clipped to one day + its items
- DiaryDay(date, spans, untracked) - one day's spans and untracked items
- DiaryStore(vault_dir) - opens/creates <vault>/diary.json

Functions:
- add / get / edit / delete
- all()
- reload() / save()
- build_diary_week(log_entries, todos, notes, lines, anchor, now) -> list[DiaryDay]
============================================================
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .activity import ActivityEntry, week_start_dt
from .models import _iso, _parse_iso, Note, Todo
from .paths import atomic_write_text


@dataclass
class DiaryItem:
    """One item (todo/note/diary) for display in a span or untracked bucket.

    kind: "todo", "note", or "diary"
    text: todo title, note title, or diary line text
    ts: datetime of completion/creation/entry
    id: unique id (for lookups/deduplication)
    context: optional context from source (for cross-context markers)
    """

    kind: str
    text: str
    ts: datetime
    id: str
    context: Optional[str] = None


@dataclass
class DiarySpan:
    """Activity span clipped to a single day, with items that occurred inside it.

    category: activity category (from ActivityEntry)
    start: span start (clipped to [day_start, day_end))
    end: span end (clipped to [day_start, day_end))
    items: list of DiaryItem occurring inside [start, end)
    """

    category: str
    start: datetime
    end: datetime
    items: list[DiaryItem] = field(default_factory=list)


@dataclass
class DiaryDay:
    """One day's spans and untracked items.

    date: the calendar date
    spans: list of DiarySpan for the day
    untracked: list of DiaryItem with no covering span
    """

    date: date
    spans: list[DiarySpan] = field(default_factory=list)
    untracked: list[DiaryItem] = field(default_factory=list)


@dataclass
class DiaryLine:
    """One line in the diary journal (manual or captured)."""

    ts: datetime
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state_tag: Optional[str] = None
    context: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict, with ts as ISO string."""
        return {
            "id": self.id,
            "ts": _iso(self.ts),
            "text": self.text,
            "state_tag": self.state_tag,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DiaryLine:
        """Deserialize from dict. Tolerant: missing/bad keys -> None/defaults.
        Caller must DROP lines where ts is None (the P1-1 fix)."""
        ts = _parse_iso(d.get("ts"))  # May be None if missing or garbage
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            ts=ts,  # type: ignore  # ts may be None (caller filters)
            text=str(d.get("text", "")),
            state_tag=d.get("state_tag"),
            context=d.get("context"),
        )


class DiaryStore:
    """Stores DiaryLine entries in <vault>/diary.json."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.path = self.vault_dir / "diary.json"
        self._lines: list[DiaryLine] = []
        self.reload()

    # --- persistence ---
    def reload(self) -> None:
        """Load diary.json; backup if corrupt; DROP any line with ts=None (P1-1)."""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Corrupt/truncated file: keep the user's data recoverable by
                # renaming it aside before the next save() can overwrite it.
                self._backup_corrupt()
                data = []
        else:
            data = []

        # Accept a bare list; degrade to empty for anything else.
        if not isinstance(data, list):
            data = []

        # Build lines from dicts, skip non-dicts.
        # P1-1: DROP any line whose ts is None (the poison-ts fix).
        self._lines = [
            line
            for d in data
            if isinstance(d, dict)
            for line in [DiaryLine.from_dict(d)]
            if line.ts is not None
        ]

    def save(self) -> None:
        """Write diary.json atomically."""
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        payload = [line.to_dict() for line in self._lines]
        atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _backup_corrupt(self) -> None:
        """Rename an unparseable diary.json to a .corrupt-<ts> sibling (recoverable)."""
        try:
            self.path.rename(
                self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            )
        except OSError:
            pass

    # --- queries ---
    def all(self) -> list[DiaryLine]:
        """All diary lines."""
        return list(self._lines)

    def get(self, line_id: str) -> Optional[DiaryLine]:
        """Retrieve a line by id, or None if not found."""
        return next((line for line in self._lines if line.id == line_id), None)

    # --- mutations ---
    def add(self, line: DiaryLine) -> DiaryLine:
        """Add a line and persist."""
        self._lines.append(line)
        self.save()
        return line

    def edit(self, line_id: str, text: str) -> Optional[DiaryLine]:
        """Update text of a line (NEVER touch ts/state_tag/context) and persist.
        Returns the updated line, or None if not found."""
        line = self.get(line_id)
        if not line:
            return None
        line.text = text
        self.save()
        return line

    def delete(self, line_id: str) -> None:
        """Remove a line by id and persist."""
        self._lines = [line for line in self._lines if line.id != line_id]
        self.save()


def build_diary_week(
    log_entries: list[ActivityEntry],
    todos: list[Todo],
    notes: list[Note],
    lines: list[DiaryLine],
    anchor: datetime,
    now: datetime,
) -> list[DiaryDay]:
    """Build 7-day week structure from activity + todos + notes + diary lines.

    Weaves activity spans (clipped per day to handle cross-midnight P2-2), completed
    todos, created notes, and diary lines into per-day structures. Items are placed
    into covering spans or untracked buckets. Pure: no I/O, no datetime.now() inside.

    Args:
        log_entries: list of ActivityEntry (spans with category/start/end)
        todos: list of Todo (with completed_at field; exclude deleted)
        notes: list of Note (with created field; exclude deleted)
        lines: list of DiaryLine (with ts field)
        anchor: a datetime in the week to build (week is Monday-Sunday via week_start_dt)
        now: current datetime for clipping open spans (end=None)

    Returns:
        list[DiaryDay] of exactly 7 days, Monday-Sunday of anchor's ISO week.
    """
    # Compute the week bounds: Monday 00:00 to next Monday 00:00
    week_start = week_start_dt(anchor)
    week_end = week_start + timedelta(days=7)

    # Build the 7 days
    days: list[DiaryDay] = []
    for offset in range(7):
        day_start = week_start + timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        day_date = day_start.date()

        # Clipped spans for this day
        spans_list: list[DiarySpan] = []
        for entry in log_entries:
            # Clip the span to [day_start, day_end)
            # For open spans (end=None), use `now` as the span end
            span_end = entry.end if entry.end is not None else now
            seg_start = max(entry.start, day_start)
            seg_end = min(span_end, day_end)

            if seg_start < seg_end:
                spans_list.append(
                    DiarySpan(
                        category=entry.category,
                        start=seg_start,
                        end=seg_end,
                        items=[],
                    )
                )

        # Items for this day (todo/note/diary)
        items_list: list[DiaryItem] = []

        # Add completed todos
        for todo in todos:
            if todo.deleted or todo.completed_at is None:
                continue
            if day_start <= todo.completed_at < day_end:
                items_list.append(
                    DiaryItem(
                        kind="todo",
                        text=todo.title,
                        ts=todo.completed_at,
                        id=todo.id,
                        context=todo.context,
                    )
                )

        # Add created notes
        for note in notes:
            if note.deleted or note.created is None:
                continue
            if day_start <= note.created < day_end:
                items_list.append(
                    DiaryItem(
                        kind="note",
                        text=note.title,
                        ts=note.created,
                        id=note.id,
                        context=note.context,
                    )
                )

        # Add diary lines
        for line in lines:
            if line.ts is None:
                continue
            if day_start <= line.ts < day_end:
                items_list.append(
                    DiaryItem(
                        kind="diary",
                        text=line.text,
                        ts=line.ts,
                        id=line.id,
                        context=line.context,
                    )
                )

        # Sort items by timestamp
        items_list.sort(key=lambda x: x.ts)

        # Place items into spans or untracked
        untracked_list: list[DiaryItem] = []
        for item in items_list:
            placed = False
            for span in spans_list:
                if span.start <= item.ts < span.end:
                    span.items.append(item)
                    placed = True
                    break
            if not placed:
                untracked_list.append(item)

        days.append(
            DiaryDay(
                date=day_date,
                spans=spans_list,
                untracked=untracked_list,
            )
        )

    return days
