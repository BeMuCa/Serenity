"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Persist and mutate todos as a JSON document in the vault.
Role:    The Todos tab + Trash tab read/write through this. Holds the list, assigns
         insertion order, handles complete/restore/delete/timer, and exposes the
         ranked view (delegating order to core.ranking).

Functions:
- TodoStore(vault_dir) - opens/creates <vault>/todos.json
- add / get / update / complete / reopen / soft_delete / restore / purge
  · complete: silences active reminder, pre-marks past rungs on recurrence clone (R-5/R-13)
  · soft_delete: silences active reminder (R-5)
  · reopen: pre-marks past rungs (R-13)
- start_timer / stop_timer
- active() -> ranked non-done/non-deleted todos
- trash() -> done or deleted todos (for the Trash tab)
- save() / reload()
============================================================
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import reminders
from .models import Todo
from .paths import atomic_write_text
from .ranking import rank_todos
from .recurrence import next_due


class TodoStore:
    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.path = self.vault_dir / "todos.json"
        self._todos: list[Todo] = []
        self._next_order = 0
        self.reload()

    # --- persistence ---
    def reload(self) -> None:
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
        # Accept both a bare list and the spec's document shape
        # {"version": 1, "todos": [...]}; degrade to empty for anything else.
        if isinstance(data, dict):
            data = data.get("todos", [])
        if not isinstance(data, list):
            data = []
        self._todos = [Todo.from_dict(d) for d in data if isinstance(d, dict)]
        self._next_order = (max((t.order for t in self._todos), default=-1)) + 1

    def save(self) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        payload = [t.to_dict() for t in self._todos]
        atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _backup_corrupt(self) -> None:
        """Rename an unparseable todos.json to a .corrupt-<ts> sibling (recoverable)."""
        try:
            self.path.rename(self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}"))
        except OSError:
            pass

    # --- queries ---
    def all(self) -> list[Todo]:
        return list(self._todos)

    def get(self, todo_id: str) -> Optional[Todo]:
        return next((t for t in self._todos if t.id == todo_id), None)

    def active(self, now: Optional[datetime] = None) -> list[Todo]:
        return rank_todos(self._todos, now=now)

    def trash(self) -> list[Todo]:
        """Done or deleted todos, most-recently-updated first."""
        items = [t for t in self._todos if t.done or t.deleted]
        items.sort(key=lambda t: (t.updated or t.created or datetime.min), reverse=True)
        return items

    # --- mutations ---
    def add(self, todo: Todo, persist: bool = True) -> Todo:
        now = datetime.now()
        todo.created = todo.created or now
        todo.updated = now
        todo.order = self._next_order
        self._next_order += 1
        self._todos.append(todo)
        if persist:
            self.save()
        return todo

    def update(self, todo: Todo, persist: bool = True) -> None:
        todo.updated = datetime.now()
        if persist:
            self.save()

    def complete(self, todo_id: str) -> Optional[Todo]:
        """Mark done. Done todos leave the active list and land in Trash/Archive.
        If recurring, spawn the next occurrence."""
        t = self.get(todo_id)
        if not t:
            return None
        t.done = True
        t.in_progress = False
        t.timer_running_since = None
        t.updated = datetime.now()
        t.completed_at = t.updated
        reminders.silence(t)
        if t.recurring:
            self._spawn_recurrence(t)
        self.save()
        return t

    def reopen(self, todo_id: str) -> Optional[Todo]:
        t = self.get(todo_id)
        if not t:
            return None
        t.done = False
        t.deleted = False
        t.updated = datetime.now()
        t.completed_at = None
        reminders.pre_mark_past(t, datetime.now())
        self.save()
        return t

    def soft_delete(self, todo_id: str) -> Optional[Todo]:
        t = self.get(todo_id)
        if not t:
            return None
        t.deleted = True
        t.in_progress = False
        t.timer_running_since = None
        t.updated = datetime.now()
        reminders.silence(t)
        self.save()
        return t

    def restore(self, todo_id: str) -> Optional[Todo]:
        return self.reopen(todo_id)

    def purge(self, todo_id: str) -> None:
        self._todos = [t for t in self._todos if t.id != todo_id]
        self.save()

    def start_timer(self, todo_id: str) -> Optional[Todo]:
        t = self.get(todo_id)
        if not t:
            return None
        if not t.timer_running:
            t.timer_running_since = datetime.now()
        t.in_progress = True
        t.updated = datetime.now()
        self.save()
        return t

    def stop_timer(self, todo_id: str) -> Optional[Todo]:
        t = self.get(todo_id)
        if not t:
            return None
        if t.timer_running_since:
            elapsed = (datetime.now() - t.timer_running_since).total_seconds()
            t.timer_seconds += int(elapsed)
            t.timer_running_since = None
        t.in_progress = False
        t.updated = datetime.now()
        self.save()
        return t

    def _spawn_recurrence(self, done_todo: Todo) -> None:
        """Create a fresh, not-done copy for a recurring todo (next occurrence).

        Clones title/recurring/category/tags/state_tag/context, clears timers + done,
        and advances the due date to the next occurrence per the recurrence rule
        (daily / weekdays / weekly / monthly). The base is the completed todo's due,
        or now if it had none. ics_uid + linked_note_ids are deliberately NOT copied
        (a new occurrence is a new event identity). Reminder offsets are copied; past
        rungs are pre-marked to avoid spurious re-firing."""
        base = done_todo.due or datetime.now()
        clone = Todo(
            title=done_todo.title,
            recurring=done_todo.recurring,
            category=done_todo.category,
            tags=list(done_todo.tags),
            due=next_due(done_todo.recurring, base),
            subtasks=[],
            state_tag=done_todo.state_tag,
            context=done_todo.context,
            reminder_offsets=list(done_todo.reminder_offsets),
        )
        reminders.pre_mark_past(clone, datetime.now())
        self.add(clone, persist=False)
