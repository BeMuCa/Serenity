"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Pluggable, privacy-first text-to-speech so Serenity can read her lines aloud.
Role:    The mascot's speech bubble hands her line + language to speak(). A local
         engine (Piper, recommended) or the zero-dependency Windows SAPI5 baseline
         synthesizes it; a no-op stub keeps the app alive when no engine is present.
         All selection + text-cleanup logic is pure (no Qt, no heavy deps) so it is
         unit-tested headless; heavy imports happen lazily inside the engines.

Functions:
- clean_for_speech(text) - strip markdown / quotes, expand "-" to a pause, tidy for TTS
- pick_voice(lang, voice_de, voice_en) - choose the configured voice id for a language
- available_engines() - which backends can actually run right now
- choose_engine(preferred) - pick the best installed engine (preferred -> piper -> sapi -> noop)
- make_engine(settings) - build the configured engine, degrading gracefully to a stub

Classes:
- TtsEngine - abstract base: speak(text, lang), stop(), available
- PiperEngine - local, offline neural voices (.onnx); the recommended default
- Sapi5Engine - Windows built-in voices via pyttsx3 (offline baseline, sounds dated)
- NoopEngine - safe stub; the app never crashes when no engine is available
============================================================
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# Engine identifiers used in Settings and the factory.
PIPER = "piper"
SAPI = "sapi"
NOOP = "noop"


# --------------------------------------------------------------------------- #
# Pure logic (no Qt, no heavy deps) - unit-tested headless.
# --------------------------------------------------------------------------- #

# Markdown / formatting noise we strip before speaking.
_MD_BOLD_ITALIC = re.compile(r"[*_`]+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")     # [text](url) -> text
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_ARROW = re.compile(r"\s*->\s*")
_WS = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    """Normalize a bubble line into something a TTS engine reads naturally.

    - strips markdown emphasis (*, _, `) and turns [text](url) links into "text",
    - drops leading "# " heading markers,
    - removes the straight/typographic quotes Serenity wraps titles in,
    - expands a standalone "-" (her single-hyphen pause) and "->" into a spoken
      pause ("..."), so the reader does not say "minus" / "dash",
    - collapses whitespace.
    Returns "" for empty / whitespace-only input."""
    if not text:
        return ""
    out = _MD_LINK.sub(r"\1", text)
    out = _HEADING.sub("", out)
    out = _MD_BOLD_ITALIC.sub("", out)
    # Quotes around titles ("...", "...", '...') add nothing when spoken.
    out = out.replace('"', "").replace("“", "").replace("”", "").replace("„", "")
    # "->" reads as a transition; turn it into a pause.
    out = _ARROW.sub("... ", out)
    # A " - " dash (her em-dash substitute) becomes a spoken pause.
    out = re.sub(r"\s-\s", "... ", out)
    out = _WS.sub(" ", out).strip()
    return out


def pick_voice(lang: str, voice_de: str, voice_en: str) -> str:
    """Return the configured voice id for a language ('de' -> de voice, else en)."""
    return voice_de if (lang or "").lower().startswith("de") else voice_en


# --------------------------------------------------------------------------- #
# Engine abstraction.
# --------------------------------------------------------------------------- #

class TtsEngine:
    """A text-to-speech backend. Implementations must be safe to call headless.

    speak() should never raise into the caller - a backend that fails at runtime
    degrades to silence rather than crashing Serenity."""

    name = "base"
    available = False

    def speak(self, text: str, lang: str) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass


class NoopEngine(TtsEngine):
    """Says nothing. The always-safe fallback when no real engine is present."""

    name = NOOP
    available = True

    def speak(self, text: str, lang: str) -> None:
        return

    def stop(self) -> None:
        return


class PiperEngine(TtsEngine):
    """Local, offline Piper voices (.onnx). The recommended privacy-first default.

    Voices are looked up by id (e.g. 'de_DE-kerstin-low') in the voices directory;
    each id needs a matching <id>.onnx (+ optional <id>.onnx.json). Synthesis runs
    on a worker thread and is played via Qt multimedia, so import of piper / Qt is
    lazy and failures degrade to silence."""

    name = PIPER

    def __init__(self, voices_dir: Path, voice_de: str, voice_en: str,
                 rate: float = 1.0, volume: float = 1.0) -> None:
        self.voices_dir = Path(voices_dir)
        self.voice_de = voice_de
        self.voice_en = voice_en
        self.rate = rate
        self.volume = volume
        self._voices: dict[str, object] = {}        # id -> loaded PiperVoice
        self._thread = None
        self.available = self._probe()

    def _probe(self) -> bool:
        try:
            import piper  # noqa: F401
        except Exception:
            return False
        # At least one configured voice file must exist to be useful.
        return any(self.voice_path(v).exists()
                   for v in (self.voice_de, self.voice_en) if v)

    def voice_path(self, voice_id: str) -> Path:
        return self.voices_dir / f"{voice_id}.onnx"

    def _voice(self, voice_id: str):
        """Load (and cache) a PiperVoice by id, or None if unavailable."""
        if not voice_id:
            return None
        if voice_id in self._voices:
            return self._voices[voice_id]
        path = self.voice_path(voice_id)
        if not path.exists():
            return None
        try:
            from piper import PiperVoice
            voice = PiperVoice.load(str(path))
        except Exception:
            return None
        self._voices[voice_id] = voice
        return voice

    def synth_wav(self, text: str, lang: str, out_path: Path) -> Optional[Path]:
        """Synthesize cleaned `text` to a WAV file. Returns the path, or None on failure.

        Pure of Qt - used by both the live player and offline sample generation/tests."""
        import wave

        spoken = clean_for_speech(text)
        if not spoken:
            return None
        voice = self._voice(pick_voice(lang, self.voice_de, self.voice_en))
        if voice is None:
            return None
        try:
            # length_scale > 1 slows speech; map rate (0.5..2.0) to its inverse.
            length_scale = 1.0 / self.rate if self.rate else 1.0
            try:
                from piper import SynthesisConfig
                syn = SynthesisConfig(length_scale=length_scale, volume=self.volume)
            except Exception:
                syn = None
            out_path = Path(out_path)
            with wave.open(str(out_path), "wb") as wav:
                if syn is not None:
                    voice.synthesize_wav(spoken, wav, syn_config=syn)
                else:
                    voice.synthesize_wav(spoken, wav)
            return out_path
        except Exception:
            return None

    def speak(self, text: str, lang: str) -> None:
        # Synthesize on a worker thread (model inference blocks), then play via Qt.
        import tempfile
        import threading

        def _run():
            tmp = Path(tempfile.gettempdir()) / "serenity_tts.wav"
            if self.synth_wav(text, lang, tmp):
                self._play(tmp)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _play(self, wav_path: Path) -> None:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception:
            return
        # Keep player + output alive past this call (GC would stop playback).
        self._player = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        self._player.setSource(QUrl.fromLocalFile(str(wav_path)))
        self._player.play()

    def stop(self) -> None:
        player = getattr(self, "_player", None)
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass


class Sapi5Engine(TtsEngine):
    """Windows built-in voices via pyttsx3 (SAPI5). Zero-download offline baseline.

    Sounds dated next to Piper, but needs nothing fetched - it speaks with whatever
    voices ship in Windows (e.g. Zira EN, Hedda/Katja DE). No-op on non-Windows."""

    name = SAPI

    def __init__(self, voice_de: str = "", voice_en: str = "",
                 rate: float = 1.0, volume: float = 1.0) -> None:
        self.voice_de = voice_de
        self.voice_en = voice_en
        self.rate = rate
        self.volume = volume
        self._engine = None
        self.available = self._probe()

    def _probe(self) -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            import pyttsx3  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self):
        if self._engine is None:
            import pyttsx3
            self._engine = pyttsx3.init()
        return self._engine

    def _select_voice(self, eng, lang: str) -> None:
        """Best-effort: pick a SAPI voice whose id/name hints at the language."""
        configured = pick_voice(lang, self.voice_de, self.voice_en)
        want = (lang or "").lower()[:2]
        for v in eng.getProperty("voices"):
            blob = f"{v.id} {getattr(v, 'name', '')}".lower()
            if configured and configured.lower() in blob:
                eng.setProperty("voice", v.id)
                return
            langs = [l.decode() if isinstance(l, bytes) else str(l)
                     for l in (getattr(v, "languages", []) or [])]
            if want and (want in blob or any(want in l.lower() for l in langs)):
                eng.setProperty("voice", v.id)
                return

    def speak(self, text: str, lang: str) -> None:
        spoken = clean_for_speech(text)
        if not spoken:
            return
        try:
            eng = self._ensure()
            self._select_voice(eng, lang)
            # pyttsx3 rate is words/min (~200 default); scale by our 0.5..2.0 rate.
            eng.setProperty("rate", int(200 * self.rate))
            eng.setProperty("volume", max(0.0, min(1.0, self.volume)))
            eng.say(spoken)
            eng.runAndWait()
        except Exception:
            return

    def stop(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Engine selection / factory.
# --------------------------------------------------------------------------- #

def available_engines(voices_dir: Optional[Path] = None,
                       voice_de: str = "", voice_en: str = "") -> list[str]:
    """Names of backends that can actually run right now (NOOP always last)."""
    found = []
    if PiperEngine(voices_dir or Path("."), voice_de, voice_en).available:
        found.append(PIPER)
    if Sapi5Engine(voice_de, voice_en).available:
        found.append(SAPI)
    found.append(NOOP)
    return found


def choose_engine(preferred: str, installed: list[str]) -> str:
    """Pick an engine id: honor `preferred` if installed, else best -> noop.

    Order of preference: the requested engine, then piper, then sapi, then noop.
    Pure function so the fallback ladder is unit-tested without any backend."""
    order = [preferred, PIPER, SAPI, NOOP]
    for name in order:
        if name in installed:
            return name
    return NOOP


def make_engine(settings) -> TtsEngine:
    """Build the TTS engine the Settings ask for, degrading gracefully to a stub.

    Reads tts_engine / voices_dir / voice ids / rate / volume off `settings`.
    Never raises: if the preferred engine is not installed, falls back down the
    ladder to NoopEngine so the app always has a working (silent) engine."""
    from . import paths

    voices_dir = Path(getattr(settings, "voices_dir", "") or paths.voices_dir())
    voice_de = getattr(settings, "tts_voice_de", "")
    voice_en = getattr(settings, "tts_voice_en", "")
    rate = float(getattr(settings, "tts_rate", 1.0) or 1.0)
    volume = float(getattr(settings, "tts_volume", 1.0) or 1.0)
    preferred = getattr(settings, "tts_engine", PIPER) or PIPER

    installed = available_engines(voices_dir, voice_de, voice_en)
    chosen = choose_engine(preferred, installed)

    if chosen == PIPER:
        return PiperEngine(voices_dir, voice_de, voice_en, rate, volume)
    if chosen == SAPI:
        return Sapi5Engine(voice_de, voice_en, rate, volume)
    return NoopEngine()
