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
- assets_dir() -> Path - bundled pose images shipped with the package (frozen-aware: sys._MEIPASS)
- poses_dir() -> Path - the WebP pose directory
- data_dir() -> Path - bundled data files (frozen-aware: sys._MEIPASS)
- voice_lines_path() -> Path - the shipped voice_lines.json
- voices_dir() -> Path - per-user TTS voice models (Piper .onnx)
- atomic_write_text(path, text, encoding) -> None - crash-safe write via tmp + os.replace

Frozen note: in a PyInstaller bundle the read-only assets/ and data/ are unpacked
under sys._MEIPASS, NOT next to this file. assets_dir()/data_dir() resolve there
when sys.frozen is set (see _bundle_root); config_dir()/voices_dir() stay per-user.
============================================================
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent  # keep for non-frozen / dev


def _bundle_root() -> Path:
    """Root for bundled read-only assets/data.

    Frozen (PyInstaller): sys._MEIPASS is the temp dir the bundle unpacks to, and
    the .spec lays assets/ and data/ down at that root. Otherwise fall back to the
    source-tree package root next to this file (dev / pip install).

    Computed per-call (not at import time) so tests can monkeypatch sys.frozen /
    sys._MEIPASS without reimporting this module.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return _PKG_ROOT


def assets_dir() -> Path:
    """Directory of bundled, read-only assets (pose webp). Frozen-aware (sys._MEIPASS)."""
    return _bundle_root() / "assets"


def poses_dir() -> Path:
    """Directory holding the animated WebP pose files."""
    return assets_dir() / "poses"


def data_dir() -> Path:
    """Directory holding bundled data files (voice lines etc.). Frozen-aware (sys._MEIPASS)."""
    return _bundle_root() / "data"


def voice_lines_path() -> Path:
    return data_dir() / "voice_lines.json"


def voices_dir() -> Path:
    """Per-user writable directory for downloaded TTS voice models (Piper .onnx)."""
    return config_dir() / "voices"


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


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write text to path atomically: write a sibling .tmp, then os.replace it in.

    os.replace is atomic on the same filesystem, so a crash/power-loss can never
    leave a half-written target; the old file stays intact until the swap. The tmp
    is a sibling (same dir/filesystem) so the replace is a rename, not a copy.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)  # don't leave a stray tmp behind on failure
        raise
