"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The cloned-voice registry - "drop a clip, pick the language, get that voice".
Role:    Stores the user's voice clones (a short reference audio clip + metadata) so a
         Chatterbox engine can reproduce that voice. A clone is just a reference WAV the
         user supplied; Chatterbox does zero-shot cloning at synthesis time, so we only
         persist the clip path + name + language, never a trained model. The registry
         lives in app-data (voices/clones/) next to the copied reference clips and is
         pure of Qt / heavy deps so it is unit-tested headless.

Functions:
- clone_voice_id(name) -> str - the stable voice id for a clone (e.g. "clone:berk_de")
- is_clone_voice(voice_id) -> bool - True for a "clone:" voice id
- clone_slug(name) -> str - filesystem/id-safe slug for a clone name

Classes:
- VoiceClone - one clone: id, display name, language ('de'|'en'), reference clip path
- CloneRegistry - load/save the clones.json catalog; add / remove / list / lookup
============================================================
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .paths import atomic_write_text

# Cloned voices are addressed by a "clone:" prefixed id so per-language voice
# selection can tell a clone apart from a Kokoro / Piper voice id at a glance.
CLONE_PREFIX = "clone:"
CLONES_SUBDIR = "clones"
CLONES_INDEX = "clones.json"

_SLUG = re.compile(r"[^a-z0-9]+")


def clone_slug(name: str) -> str:
    """A lowercase, filesystem/id-safe slug for a clone display name.

    Collapses runs of non-alphanumerics to '_' and trims them. '' for empty input."""
    return _SLUG.sub("_", (name or "").strip().lower()).strip("_")


def clone_voice_id(name: str, lang: str = "") -> str:
    """The stable voice id for a clone, e.g. clone_voice_id("Berk", "de") -> 'clone:berk_de'.

    Appending the language keeps an English and a German clone of the same name apart."""
    slug = clone_slug(name)
    suffix = (lang or "").lower()[:2]
    return f"{CLONE_PREFIX}{slug}_{suffix}" if suffix else f"{CLONE_PREFIX}{slug}"


def is_clone_voice(voice_id: str) -> bool:
    """True when `voice_id` names a cloned voice ('clone:...')."""
    return (voice_id or "").startswith(CLONE_PREFIX)


@dataclass
class VoiceClone:
    """One cloned voice: a named reference clip for a given language."""

    voice_id: str          # 'clone:<slug>_<lang>'
    name: str              # human display name ("Berk", "Mum")
    lang: str              # 'de' | 'en'
    clip: str              # absolute path to the stored reference clip

    def exists(self) -> bool:
        """True when the reference clip is still on disk (a clone is useless without it)."""
        try:
            return bool(self.clip) and Path(self.clip).exists()
        except OSError:
            return False

    def label(self) -> str:
        """A picker label, e.g. 'Berk - cloned German voice'."""
        lang_name = "German" if (self.lang or "").lower().startswith("de") else "English"
        return f"{self.name} - cloned {lang_name} voice"


class CloneRegistry:
    """Load/save the cloned-voice catalog and copy reference clips into app-data.

    The catalog (clones.json) and the reference clips live under <voices_dir>/clones/.
    Pure of Qt; safe to construct and query even when the directory does not exist yet."""

    def __init__(self, voices_dir: Path) -> None:
        self.dir = Path(voices_dir) / CLONES_SUBDIR
        self.index_path = self.dir / CLONES_INDEX
        self._clones: dict[str, VoiceClone] = {}
        self.load()

    def load(self) -> "CloneRegistry":
        self._clones = {}
        if not self.index_path.exists():
            return self
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self
        for row in data.get("clones", []):
            try:
                c = VoiceClone(
                    voice_id=row["voice_id"], name=row["name"],
                    lang=row["lang"], clip=row["clip"])
            except (KeyError, TypeError):
                continue
            self._clones[c.voice_id] = c
        return self

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"clones": [asdict(c) for c in self._clones.values()]}
        atomic_write_text(
            self.index_path, json.dumps(payload, indent=2, ensure_ascii=False))

    def all(self) -> list[VoiceClone]:
        """Every clone, sorted by language then name (stable picker order)."""
        return sorted(self._clones.values(), key=lambda c: (c.lang, c.name.lower()))

    def for_lang(self, lang: str) -> list[VoiceClone]:
        """Clones usable for a language ('de' -> German clones, else English)."""
        want = "de" if (lang or "").lower().startswith("de") else "en"
        return [c for c in self.all() if (c.lang or "").lower().startswith(want)]

    def get(self, voice_id: str) -> Optional[VoiceClone]:
        return self._clones.get(voice_id)

    def add(self, name: str, lang: str, source_clip: Path,
            copy: bool = True) -> VoiceClone:
        """Register a clone: copy the reference clip into app-data and persist metadata.

        `lang` is normalized to 'de' or 'en'. The voice id is derived from name+lang, so
        re-adding the same name+language replaces the previous clip. Returns the clone.
        Raises FileNotFoundError if the source clip is missing."""
        src = Path(source_clip)
        if copy and not src.exists():
            raise FileNotFoundError(str(src))
        norm_lang = "de" if (lang or "").lower().startswith("de") else "en"
        vid = clone_voice_id(name, norm_lang)
        self.dir.mkdir(parents=True, exist_ok=True)
        if copy:
            dest = self.dir / f"{clone_slug(name)}_{norm_lang}{src.suffix.lower() or '.wav'}"
            if src.resolve() != dest.resolve():
                shutil.copyfile(src, dest)
            clip_path = str(dest)
        else:
            clip_path = str(src)
        clone = VoiceClone(voice_id=vid, name=name.strip(), lang=norm_lang, clip=clip_path)
        self._clones[vid] = clone
        self.save()
        return clone

    def remove(self, voice_id: str, delete_clip: bool = True) -> bool:
        """Drop a clone (and optionally its copied clip). Returns True if it existed."""
        clone = self._clones.pop(voice_id, None)
        if clone is None:
            return False
        if delete_clip and clone.clip:
            try:
                p = Path(clone.clip)
                # Only delete clips we copied into our own clones dir.
                if p.exists() and p.parent.resolve() == self.dir.resolve():
                    p.unlink()
            except OSError:
                pass
        self.save()
        return True
