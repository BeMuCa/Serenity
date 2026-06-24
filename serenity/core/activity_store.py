"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Persist the activity time-tracking log as JSON in the vault.
Role:    The mascot's activity selector starts/stops spans on an ActivityLog (core.activity);
         this store reads/writes that log to <vault>/activity.json so tracked time survives
         restarts and feeds the Weekly Performance Board. It also persists the board's
         last auto-open timestamp (the once-a-day Friday trigger). Pure of Qt - the UI calls
         start/stop and save through here. A running span (end is None) is persisted too, so
         a span open at quit is still open on next launch.

Functions:
- ActivityStore(vault_dir) - opens/creates <vault>/activity.json
- start(category) / stop() / running() - mutate the log (auto-save)
- log() -> ActivityLog - the loaded log (for the Weekly Board)
- last_board_open() / set_last_board_open(dt) - the Friday auto-open marker
============================================================
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .activity import ActivityEntry, ActivityLog
from .paths import atomic_write_text


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


class ActivityStore:
    """Persist the activity log + the weekly-board auto-open marker as JSON.

    The vault file shape is {"version": 1, "entries": [...], "last_board_open": iso}.
    Mutations (start/stop) save immediately so the timer survives a crash."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.path = self.vault_dir / "activity.json"
        self._log = ActivityLog()
        self._last_board_open: Optional[datetime] = None
        self.reload()

    # --- persistence ---
    def reload(self) -> None:
        entries: list[ActivityEntry] = []
        self._last_board_open = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Corrupt/truncated file: preserve the user's tracked-time history by
                # renaming it aside before the next save() overwrites it.
                self._backup_corrupt()
                data = {}
            if isinstance(data, dict):
                for row in data.get("entries", []):
                    if not isinstance(row, dict):
                        continue
                    start = _parse(row.get("start"))
                    if start is None:
                        continue
                    entries.append(ActivityEntry(
                        category=str(row.get("category", "")),
                        start=start,
                        end=_parse(row.get("end")),
                    ))
                self._last_board_open = _parse(data.get("last_board_open"))
        self._log = ActivityLog(entries)

    def save(self) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": [
                {"category": e.category, "start": _iso(e.start), "end": _iso(e.end)}
                for e in self._log.entries()
            ],
            "last_board_open": _iso(self._last_board_open),
        }
        atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _backup_corrupt(self) -> None:
        """Rename an unparseable activity.json to a .corrupt-<ts> sibling (recoverable)."""
        try:
            self.path.rename(self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}"))
        except OSError:
            pass

    # --- log access ---
    def log(self) -> ActivityLog:
        return self._log

    def running(self) -> Optional[ActivityEntry]:
        return self._log.running()

    # --- mutations ---
    def start(self, category: str, when: Optional[datetime] = None) -> ActivityEntry:
        entry = self._log.start(category, when or datetime.now())
        self.save()
        return entry

    def stop(self, when: Optional[datetime] = None) -> Optional[ActivityEntry]:
        entry = self._log.stop(when or datetime.now())
        self.save()
        return entry

    # --- weekly-board auto-open marker ---
    def last_board_open(self) -> Optional[datetime]:
        return self._last_board_open

    def set_last_board_open(self, when: datetime) -> None:
        self._last_board_open = when
        self.save()
