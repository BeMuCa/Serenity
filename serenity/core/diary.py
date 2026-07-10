"""
============================================================
Author:  Berk
Created: 2026-07-10
Purpose: Persist and mutate manual diary lines as a JSON document in the vault.
Role:    The Diary tab + Weekly Board diary section read/write through this.
         Holds the list of diary lines, handles add/edit/delete, and tolerates
         corrupt JSON and poison timestamps (P1-1: drop any line with ts=None).

Models:
- DiaryLine(id, ts, text, state_tag, context) - one diary entry
- DiaryStore(vault_dir) - opens/creates <vault>/diary.json

Functions:
- add / get / edit / delete
- all()
- reload() / save()
============================================================
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import _iso, _parse_iso
from .paths import atomic_write_text


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
