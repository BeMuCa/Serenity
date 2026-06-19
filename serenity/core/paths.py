"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Resolve filesystem locations for the vault, app config and bundled assets.
Role:    Single source of truth for where Serenity reads/writes. Keeps platform
         differences (Windows %APPDATA% vs ~/.config) in one place so the rest of
         the app is path-agnostic.

Functions:
- default_vault_dir() -> Path - the user's vault (~/SerenityVault by default)
- config_dir() -> Path - per-user app config/state directory
- assets_dir() -> Path - bundled pose images + json shipped with the package
- poses_dir() -> Path - the WebP pose directory
- voice_lines_path() -> Path - the shipped voice-lines.json
============================================================
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    """Directory of bundled, read-only assets (pose webp + data json)."""
    return _PKG_ROOT / "assets"


def poses_dir() -> Path:
    """Directory holding the animated WebP pose files."""
    return assets_dir() / "poses"


def data_dir() -> Path:
    """Directory holding bundled data files (voice lines etc.)."""
    return _PKG_ROOT / "data"


def voice_lines_path() -> Path:
    return data_dir() / "voice_lines.json"


def config_dir() -> Path:
    """Per-user writable directory for settings, index db, tag arsenal.

    Windows -> %APPDATA%/Serenity ; otherwise ~/.config/serenity .
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Serenity"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "serenity"


def default_vault_dir() -> Path:
    """The default vault folder; user-overridable in Settings."""
    return Path.home() / "SerenityVault"
