"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: A small on-disk cache of rendered TTS audio so identical lines play instantly.
Role:    Synthesis (Kokoro / Piper / Chatterbox) is slow; many of Serenity's lines are
         spoken verbatim again and again (greetings, confirmations). This cache keys a
         WAV file on (engine, voice_id, exact final spoken text) - so the FIRST time a
         line is synthesized it is written here, and every identical request afterwards
         just replays the cached file. A pre-warm step (see core.tts) renders the fully
         fixed voice lines (no {slots}) up-front so they are instant later; slotted lines
         get cached on first real use. Pure of Qt / heavy deps - unit-tested headless.

Functions:
- cache_key(engine, voice_id, text) -> str - the stable sha256 hex key for a render
- TtsCache.path_for(engine, voice_id, text) -> Path - where that render lives
- TtsCache.get(...) / put(...) / has(...) - lookup / store / probe a cached render
- TtsCache.prune() / clear() - enforce the size cap (LRU by mtime) / wipe the cache
============================================================
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

CACHE_SUBDIR = "cache"
# Default cap on total cached audio. Fixed voice lines are tiny WAVs; 64 MB is plenty
# of headroom and keeps the on-disk footprint bounded even with many voices pre-warmed.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


def cache_key(engine: str, voice_id: str, text: str) -> str:
    """The stable cache key for a render: sha256 over engine + voice id + exact text.

    The EXACT final spoken string is hashed (after the caller has cleaned/filled it), so
    two requests collide only when they would synthesize byte-for-byte the same audio.
    Pure - no disk access - so the keying is unit-tested without a cache directory."""
    h = hashlib.sha256()
    h.update((engine or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((voice_id or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()


class TtsCache:
    """A bounded directory of rendered WAVs keyed on (engine, voice_id, final text).

    Files are named <key>.wav under <voices_dir>/cache/. The cap is enforced by prune(),
    evicting the least-recently-used files (by mtime) until under budget. Safe to use
    even when the directory does not exist yet (get() simply misses)."""

    def __init__(self, voices_dir: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.dir = Path(voices_dir) / CACHE_SUBDIR
        self.max_bytes = int(max_bytes)

    def path_for(self, engine: str, voice_id: str, text: str) -> Path:
        """The on-disk path a render for (engine, voice_id, text) would live at."""
        return self.dir / f"{cache_key(engine, voice_id, text)}.wav"

    def has(self, engine: str, voice_id: str, text: str) -> bool:
        """True when a non-empty cached render already exists for this request."""
        p = self.path_for(engine, voice_id, text)
        try:
            return p.exists() and p.stat().st_size > 0
        except OSError:
            return False

    def get(self, engine: str, voice_id: str, text: str) -> Optional[Path]:
        """The cached render path if present (and bumps its mtime so it stays warm), else None."""
        p = self.path_for(engine, voice_id, text)
        try:
            if p.exists() and p.stat().st_size > 0:
                # Touch so LRU pruning treats freshly-played lines as recently used.
                p.touch()
                return p
        except OSError:
            return None
        return None

    def put(self, engine: str, voice_id: str, text: str, wav_path: Path) -> Optional[Path]:
        """Adopt an already-rendered WAV into the cache under its key. Returns the cached path.

        Copies `wav_path` to the keyed location (so the caller's temp file can vanish),
        then prunes to the size cap. Returns None if the source is missing/empty."""
        src = Path(wav_path)
        try:
            if not (src.exists() and src.stat().st_size > 0):
                return None
        except OSError:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        dest = self.path_for(engine, voice_id, text)
        try:
            if src.resolve() != dest.resolve():
                import shutil
                shutil.copyfile(src, dest)
        except OSError:
            return None
        self.prune()
        return dest

    def total_bytes(self) -> int:
        """Total size of all cached WAVs in bytes (0 if the dir does not exist)."""
        if not self.dir.exists():
            return 0
        total = 0
        for f in self.dir.glob("*.wav"):
            try:
                total += f.stat().st_size
            except OSError:
                continue
        return total

    def prune(self) -> int:
        """Evict least-recently-used renders until under the byte cap. Returns bytes freed."""
        if self.max_bytes <= 0 or not self.dir.exists():
            return 0
        files = []
        for f in self.dir.glob("*.wav"):
            try:
                st = f.stat()
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, f))
        total = sum(size for _m, size, _f in files)
        if total <= self.max_bytes:
            return 0
        freed = 0
        # Oldest first (LRU): evict until we are back under budget.
        for _mtime, size, f in sorted(files, key=lambda t: t[0]):
            if total - freed <= self.max_bytes:
                break
            try:
                f.unlink()
                freed += size
            except OSError:
                continue
        return freed

    def clear(self) -> None:
        """Remove every cached render (e.g. on a voice / engine reset)."""
        if not self.dir.exists():
            return
        for f in self.dir.glob("*.wav"):
            try:
                f.unlink()
            except OSError:
                continue
