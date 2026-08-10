"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Plain data models for todos, subtasks and notes (+ JSON serialization).
Role:    The vocabulary every store and UI widget speaks. Framework-free dataclasses
         so they serialize to the JSON todo document and the note front-matter.

Models:
- SubTask - one step of a todo
- Todo - a task: subtasks, timer, recurring, deadline, dependencies, done/deleted state,
  creation-time state_tag/context stamp (Phase C), reminder ladder (Phase H §2: offsets,
  fired, active, nudge_at)
- Note - a markdown note's metadata (body lives in the .md file) + state_tag/context stamp

Functions:
- Todo.from_dict / to_dict, SubTask.* , Note.from_dict / to_dict - (de)serialize
- new_id() - short unique id
- _clean_rungs(v, extra=()) - coerce untrusted reminder offsets to known int list, deduped, desc
- _clean_active(v) - coerce untrusted reminder_active to known int or 0 or None
============================================================
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

NOTE_COLORS = ["violet", "sky", "green", "amber", "rose", "neutral"]

# Phase H reminders: known reminder offset values (minutes). Must match reminders.RUNG_MINUTES.
# Hardcoded here to avoid a core→core cycle (models.py must NOT import reminders.py).
_KNOWN_RUNGS = {10080, 1440, 60, 30, 5}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _clean_context(v) -> Optional[str]:
    """Untrusted stored context: anything but the two exact values loads as None
    (None = visible in both contexts downstream)."""
    return v if v in ("business", "private") else None


def _clean_state_tag(v) -> Optional[str]:
    """Untrusted stored state_tag: any non-empty string (a registry key, possibly
    orphaned) is kept; everything else loads as None."""
    return v if isinstance(v, str) and v else None


def _clean_rungs(v, extra=()) -> list[int]:
    """Untrusted reminder_offsets: extract known ints (from _KNOWN_RUNGS + extra),
    dedupe, sort descending. Non-list inputs return []."""
    if not isinstance(v, list):
        return []
    known = _KNOWN_RUNGS | set(extra)
    result = []
    seen = set()
    for item in v:
        if isinstance(item, int) and item in known and item not in seen:
            result.append(item)
            seen.add(item)
    return sorted(result, reverse=True)


def _clean_active(v) -> Optional[int]:
    """Untrusted reminder_active: must be int in _KNOWN_RUNGS ∪ {0}, else None."""
    if not isinstance(v, int):
        return None
    if v == 0 or v in _KNOWN_RUNGS:
        return v
    return None


@dataclass
class SubTask:
    id: str = field(default_factory=new_id)
    text: str = ""
    done: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "done": self.done}

    @classmethod
    def from_dict(cls, d: dict) -> "SubTask":
        return cls(id=d.get("id") or new_id(), text=d.get("text", ""), done=bool(d.get("done")))


@dataclass
class Todo:
    id: str = field(default_factory=new_id)
    title: str = ""
    done: bool = False
    deleted: bool = False
    in_progress: bool = False
    order: int = 0                       # manual insertion order (lower = added earlier)
    due: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    recurring: Optional[str] = None      # e.g. "every weekday"
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)   # ids this todo waits on (P2 graph)
    linked_note_ids: list[str] = field(default_factory=list)   # vault notes attached (prep/protocol)
    subtasks: list[SubTask] = field(default_factory=list)
    # timer (seconds). running_since set => timer is live.
    timer_seconds: int = 0
    timer_running_since: Optional[datetime] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    ics_uid: Optional[str] = None        # source UID for ICS round-trip dedup (cross-device)
    # creation-time stamp (Phase C): activity registry key / global context; never re-stamped on edit
    state_tag: Optional[str] = None
    context: Optional[str] = None        # "business" | "private" | None
    # Phase H reminders (Phase H §2)
    reminder_offsets: list[int] = field(default_factory=list)  # sorted desc; known values only
    reminder_fired: list[int] = field(default_factory=list)    # includes fired reminders + 0 sentinel
    reminder_active: Optional[int] = None                       # current active rung or 0 or None
    reminder_nudge_at: Optional[datetime] = None                # when to nudge next (or None)

    @property
    def timer_running(self) -> bool:
        return self.timer_running_since is not None

    def live_timer_seconds(self, now: Optional[datetime] = None) -> int:
        """Accumulated seconds including the current run (for a live ticking chip)."""
        total = self.timer_seconds
        if self.timer_running_since is not None:
            now = now or datetime.now()
            total += max(0, int((now - self.timer_running_since).total_seconds()))
        return total

    @property
    def progress(self) -> float:
        if not self.subtasks:
            return 1.0 if self.done else 0.0
        done = sum(1 for s in self.subtasks if s.done)
        return done / len(self.subtasks)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "done": self.done,
            "deleted": self.deleted,
            "in_progress": self.in_progress,
            "order": self.order,
            "due": _iso(self.due),
            "completed_at": _iso(self.completed_at),
            "recurring": self.recurring,
            "category": self.category,
            "tags": list(self.tags),
            "depends_on": list(self.depends_on),
            "linked_note_ids": list(self.linked_note_ids),
            "subtasks": [s.to_dict() for s in self.subtasks],
            "timer_seconds": self.timer_seconds,
            "timer_running_since": _iso(self.timer_running_since),
            "created": _iso(self.created),
            "updated": _iso(self.updated),
            "ics_uid": self.ics_uid,
            "state_tag": self.state_tag,
            "context": self.context,
            "reminder_offsets": list(self.reminder_offsets),
            "reminder_fired": list(self.reminder_fired),
            "reminder_active": self.reminder_active,
            "reminder_nudge_at": _iso(self.reminder_nudge_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Todo":
        return cls(
            id=d.get("id") or new_id(),
            title=d.get("title", ""),
            done=bool(d.get("done")),
            deleted=bool(d.get("deleted")),
            in_progress=bool(d.get("in_progress")),
            order=int(d.get("order", 0)),
            due=_parse_iso(d.get("due")),
            completed_at=_parse_iso(d.get("completed_at")),
            recurring=d.get("recurring"),
            category=d.get("category"),
            tags=list(d.get("tags", [])),
            depends_on=list(d.get("depends_on", []) or []),
            linked_note_ids=list(d.get("linked_note_ids", []) or []),
            subtasks=[SubTask.from_dict(s) for s in d.get("subtasks", [])],
            timer_seconds=int(d.get("timer_seconds", 0)),
            timer_running_since=_parse_iso(d.get("timer_running_since")),
            created=_parse_iso(d.get("created")),
            updated=_parse_iso(d.get("updated")),
            ics_uid=d.get("ics_uid"),
            state_tag=_clean_state_tag(d.get("state_tag")),
            context=_clean_context(d.get("context")),
            reminder_offsets=_clean_rungs(d.get("reminder_offsets", [])),
            reminder_fired=_clean_rungs(d.get("reminder_fired", []), extra=(0,)),
            reminder_active=_clean_active(d.get("reminder_active")),
            reminder_nudge_at=_parse_iso(d.get("reminder_nudge_at")),
        )


@dataclass
class Note:
    """Metadata for a markdown note. The body is the markdown file content."""

    id: str = field(default_factory=new_id)
    title: str = ""
    path: str = ""                       # absolute path to the .md file
    tags: list[str] = field(default_factory=list)
    color: str = "neutral"
    pinned: bool = False
    deleted: bool = False
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    body: str = ""                       # markdown body (not front-matter)
    # creation-time stamp (Phase C): activity registry key / global context; never re-stamped on edit
    state_tag: Optional[str] = None
    context: Optional[str] = None        # "business" | "private" | None

    def to_frontmatter(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tags": list(self.tags),
            "color": self.color,
            "pinned": self.pinned,
            "deleted": self.deleted,
            "created": _iso(self.created),
            "updated": _iso(self.updated),
            "state_tag": self.state_tag,
            "context": self.context,
        }

    @classmethod
    def from_frontmatter(cls, fm: dict, body: str, path: str) -> "Note":
        return cls(
            id=fm.get("id") or new_id(),
            title=fm.get("title", ""),
            path=path,
            tags=list(fm.get("tags", []) or []),
            color=fm.get("color") or "neutral",
            pinned=bool(fm.get("pinned")),
            deleted=bool(fm.get("deleted")),
            created=_parse_iso(fm.get("created")),
            updated=_parse_iso(fm.get("updated")),
            body=body,
            state_tag=_clean_state_tag(fm.get("state_tag")),
            context=_clean_context(fm.get("context")),
        )
