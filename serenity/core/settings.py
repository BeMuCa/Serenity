"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Load/save app settings (JSON) + the learning tag arsenal.
Role:    Single config object the shell, mascot and settings UI read/write. Lives
         in the per-user config dir. Holds vault path, render scale, accent, language,
         autostart/hotkey, the state->pose map override, undo window, and AI/voice
         toggles (stubbed for Phase 2).

Functions:
- Settings.load(path=None) / save() - persist to settings.json
- Settings.add_tags(tags) - grow the learning tag arsenal (decisions doc 4c)
- Settings.state_map() - effective state->pose map (override or default)
============================================================
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import paths
from .parser import BASIC_TAGS
from .poses import default_state_map

RENDER_SCALES = {"S": 128, "M": 152, "L": 192}


@dataclass
class Settings:
    vault_path: str = ""
    render_scale: str = "M"               # S | M | L
    accent: str = "#a78bfa"
    language: str = "en"                  # en | de
    autostart: bool = False
    global_hotkey: str = "Ctrl+Alt+Space"
    undo_seconds: int = 20
    confirm_before_save: bool = True
    autosave_after_silence: bool = True
    # Phase-2 toggles (stubbed): wired in UI, no backend yet.
    ai_enabled: bool = False
    voice_enabled: bool = False
    # mascot state -> [pose keys]; empty => use defaults
    state_pose_map: dict = field(default_factory=dict)
    # learning category tags (starts at the 8 basics, grows on use)
    tags: list = field(default_factory=lambda: list(BASIC_TAGS))

    _path: Optional[Path] = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        p = path or (paths.config_dir() / "settings.json")
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}
        data.pop("_path", None)
        valid = {f for f in cls.__dataclass_fields__ if f != "_path"}
        s = cls(**{k: v for k, v in data.items() if k in valid})
        if not s.vault_path:
            s.vault_path = str(paths.default_vault_dir())
        if not s.tags:
            s.tags = list(BASIC_TAGS)
        s._path = p
        return s

    def save(self) -> None:
        p = self._path or (paths.config_dir() / "settings.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d.pop("_path", None)
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        self._path = p

    def add_tags(self, new_tags) -> bool:
        """Add unseen tags to the arsenal (case-insensitive). Returns True if grown."""
        changed = False
        lower = {t.lower() for t in self.tags}
        for t in new_tags:
            t = (t or "").strip()
            if t and t.lower() not in lower:
                self.tags.append(t)
                lower.add(t.lower())
                changed = True
        return changed

    def state_map(self) -> dict:
        return self.state_pose_map if self.state_pose_map else default_state_map()

    @property
    def avatar_px(self) -> int:
        return RENDER_SCALES.get(self.render_scale, 152)
