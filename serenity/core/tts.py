"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Pluggable, privacy-first text-to-speech so Serenity can read her lines aloud.
Role:    The mascot's speech bubble hands her line + language to speak(). A local engine
         (Kokoro for natural English, Chatterbox for natural + cloneable German/English,
         Piper for offline German, or the zero-dependency Windows SAPI5 baseline)
         synthesizes it; a no-op stub keeps the app alive when no engine is present.
         Engine + voice are chosen PER LANGUAGE: English can use Kokoro-82M (Apache-2.0)
         or a Chatterbox clone; German can use Chatterbox (MIT, natural + cloneable) or
         Piper (Kokoro has no German). All selection + text-cleanup logic is pure (no Qt,
         no heavy deps) so it is unit-tested headless; heavy imports happen lazily inside
         the engines. A render cache (core.tts_cache) + pre-warm make repeat lines instant.

Functions:
- clean_for_speech(text) - strip markdown / quotes, expand "-" to a pause, tidy for TTS
- pick_voice(lang, voice_de, voice_en) - choose the configured voice id for a language
- is_german(lang) / kokoro_lang(voice_id) - language helpers (Kokoro voice -> espeak lang)
- kokoro_voices(prefix) - the bundled Kokoro voice ids (all 54 by default)
- kokoro_voices_by_language() - all Kokoro voices grouped by language (for the picker)
- engine_for_lang(settings, lang) - the configured engine id for a language (per-language)
- voice_for_lang(settings, lang) - the configured voice id for a language
- available_engines() - which backends can actually run right now
- choose_engine(preferred) - best installed engine (preferred -> kokoro -> chatterbox -> piper -> sapi -> noop)
- make_engine(settings, lang) - build the configured engine for a language, degrading to a stub

Classes:
- TtsEngine - abstract base: speak(text, lang), stop(), available
- KokoroEngine - local, offline Kokoro-82M voices (ONNX); natural English (NO German)
- ChatterboxEngine - Resemble AI Chatterbox Multilingual (PyTorch); natural German + English,
  zero-shot voice cloning from a reference clip; MIT-licensed, lazy + graceful
- PiperEngine - local, offline neural voices (.onnx); an offline German default
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
KOKORO = "kokoro"
PIPER = "piper"
SAPI = "sapi"
CHATTERBOX = "chatterbox"
NOOP = "noop"

# Kokoro-82M model + voice-pack filenames (kokoro-onnx release v1.0). They live in
# <voices_dir>/kokoro/ and are downloaded once (~310 MB model + ~27 MB voices).
KOKORO_MODEL_FILE = "kokoro-v1.0.onnx"
KOKORO_VOICES_FILE = "voices-v1.0.bin"
KOKORO_SUBDIR = "kokoro"

# Chatterbox Multilingual (Resemble AI). Repo: ResembleAI/chatterbox on Hugging Face,
# pip package `chatterbox-tts`, MIT-licensed (commercially usable). It does zero-shot
# voice cloning from a short reference clip and supports 23+ languages INCLUDING German
# and English - so it is the natural + cloneable choice for German (where Kokoro has no
# voices) and an alternative for English. It is heavy (PyTorch); model weights download
# once via huggingface_hub. Chatterbox's `generate` takes a language_id ('de'/'en') and
# an optional audio_prompt_path (the reference clip) for cloning. We lazy-import all of
# it and degrade to available=False when torch / the package / weights are absent.
CHATTERBOX_MODEL_REPO = "ResembleAI/chatterbox"
CHATTERBOX_LANGS = {"de", "en"}            # the two Serenity surfaces of the 23+ supported

# Kokoro voice-id prefix -> (espeak language code, human language name). The first
# letter of an id is the language ('a'/'b' = English variants), the second is the
# gender ('f'/'m'). Kokoro v1.0 ships 54 voices across nine variants - but NO German
# (the one language Serenity falls back to Piper / Chatterbox for).
KOKORO_LANG_BY_PREFIX: dict[str, tuple[str, str]] = {
    "a": ("en-us", "American English"),
    "b": ("en-gb", "British English"),
    "j": ("ja", "Japanese"),
    "z": ("cmn", "Mandarin Chinese"),
    "e": ("es", "Spanish"),
    "f": ("fr-fr", "French"),
    "h": ("hi", "Hindi"),
    "i": ("it", "Italian"),
    "p": ("pt-br", "Brazilian Portuguese"),
}

# The ALL bundled Kokoro voices (v1.0 voice pack), id -> short description. English
# (American 'a*' + British 'b*') stays the sweet mascot default tier; the other
# languages are surfaced too so the user can pick any of the 54 voices, grouped by
# language in the Settings picker. (Kept human-readable for that picker.)
KOKORO_VOICE_INFO: dict[str, str] = {
    # American female (the sweet default tier)
    "af_heart": "American female - flagship, warm and natural (grade A)",
    "af_bella": "American female - warm, most training data (grade A-)",
    "af_nicole": "American female - soft, gentle, intimate tone",
    "af_aoede": "American female - bright, friendly",
    "af_sarah": "American female - clear, even, assistant-like",
    "af_sky": "American female - light, youthful",
    "af_nova": "American female - calm, neutral narrator",
    "af_alloy": "American female - smooth, measured",
    "af_jessica": "American female - expressive, conversational",
    "af_kore": "American female - steady, composed",
    "af_river": "American female - relaxed, mellow",
    # American male
    "am_adam": "American male - deep, steady",
    "am_michael": "American male - warm, friendly",
    "am_echo": "American male - neutral narrator",
    "am_eric": "American male - bright, clear",
    "am_liam": "American male - young, casual",
    "am_onyx": "American male - rich, low",
    "am_puck": "American male - playful, lively",
    "am_fenrir": "American male - bold, resonant",
    "am_santa": "American male - jolly, characterful",
    # British female
    "bf_emma": "British female - warm, refined",
    "bf_isabella": "British female - elegant, measured",
    "bf_alice": "British female - bright, crisp",
    "bf_lily": "British female - soft, gentle",
    # British male
    "bm_george": "British male - mature, calm",
    "bm_lewis": "British male - deep, steady",
    "bm_daniel": "British male - clear, even",
    "bm_fable": "British male - storyteller, expressive",
    # Japanese
    "jf_alpha": "Japanese female - clear, natural",
    "jf_gongitsune": "Japanese female - storyteller",
    "jf_nezumi": "Japanese female - light, soft",
    "jf_tebukuro": "Japanese female - warm",
    "jm_kumo": "Japanese male - steady",
    # Mandarin Chinese
    "zf_xiaobei": "Mandarin female - clear",
    "zf_xiaoni": "Mandarin female - soft",
    "zf_xiaoxiao": "Mandarin female - bright",
    "zf_xiaoyi": "Mandarin female - gentle",
    "zm_yunjian": "Mandarin male - firm",
    "zm_yunxi": "Mandarin male - even",
    "zm_yunxia": "Mandarin male - warm",
    "zm_yunyang": "Mandarin male - resonant",
    # Spanish
    "ef_dora": "Spanish female - clear",
    "em_alex": "Spanish male - even",
    "em_santa": "Spanish male - characterful",
    # French
    "ff_siwis": "French female - clear, natural",
    # Hindi
    "hf_alpha": "Hindi female - clear",
    "hf_beta": "Hindi female - soft",
    "hm_omega": "Hindi male - steady",
    "hm_psi": "Hindi male - even",
    # Italian
    "if_sara": "Italian female - clear",
    "im_nicola": "Italian male - even",
    # Brazilian Portuguese
    "pf_dora": "Portuguese female - clear",
    "pm_alex": "Portuguese male - even",
    "pm_santa": "Portuguese male - characterful",
}


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
    return voice_de if is_german(lang) else voice_en


def is_german(lang: str) -> bool:
    """True when `lang` is German ('de', 'de-DE', ...). The one language Kokoro lacks."""
    return (lang or "").lower().startswith("de")


def kokoro_voices(prefix: str = "") -> list[str]:
    """The bundled Kokoro voice ids, optionally filtered by id prefix.

    Pure (reads the static catalog, never touches disk/model). With no prefix returns
    ALL 54 voices sorted; 'a'/'b' -> English variants, 'j'/'z'/'e'/'f'/'h'/'i'/'p' for
    the other languages, second letter 'f'/'m' for female/male."""
    ids = sorted(KOKORO_VOICE_INFO)
    return [v for v in ids if v.startswith(prefix)] if prefix else ids


def kokoro_english_voices() -> list[str]:
    """All Kokoro English voice ids (American 'a*' + British 'b*'), sorted."""
    return [v for v in kokoro_voices() if v[:1] in ("a", "b")]


def kokoro_language_name(voice_id: str) -> str:
    """Human language name for a Kokoro voice id ('af_heart' -> 'American English')."""
    return KOKORO_LANG_BY_PREFIX.get((voice_id or "")[:1], ("", "Other"))[1]


def kokoro_voices_by_language() -> dict[str, list[str]]:
    """All Kokoro voices grouped by human language name, English first then the rest.

    Drives the grouped Settings voice picker so the user can choose any of the 54
    voices. Each group's ids are sorted; group order follows KOKORO_LANG_BY_PREFIX
    (English variants first)."""
    grouped: dict[str, list[str]] = {}
    for prefix, (_code, name) in KOKORO_LANG_BY_PREFIX.items():
        ids = kokoro_voices(prefix)
        if ids:
            grouped.setdefault(name, [])
            grouped[name].extend(ids)
    for name in grouped:
        grouped[name] = sorted(grouped[name])
    return grouped


def kokoro_lang(voice_id: str) -> str:
    """espeak language code for a Kokoro voice id ('af_*' -> en-us, 'b*' -> en-gb, 'jf_*' -> ja)."""
    code, _name = KOKORO_LANG_BY_PREFIX.get((voice_id or "")[:1], ("en-us", ""))
    return code


def engine_for_lang(settings, lang: str) -> str:
    """The configured TTS engine id for a language (per-language selection).

    English reads `tts_engine_en` (defaults to the global `tts_engine`); German reads
    `tts_engine_de`. German may now use Chatterbox (natural + cloneable) instead of only
    Piper; Kokoro is still never used for German (it has no German voices), so a German
    'kokoro' setting degrades to Piper. Pure: reads attributes only."""
    default = getattr(settings, "tts_engine", PIPER) or PIPER
    if is_german(lang):
        chosen = getattr(settings, "tts_engine_de", "") or default
        return PIPER if chosen == KOKORO else chosen
    return getattr(settings, "tts_engine_en", "") or default


def voice_for_lang(settings, lang: str) -> str:
    """The configured voice id for a language.

    The voice depends on the engine chosen for that language:
      - Chatterbox: the per-language clone voice id (`tts_clone_de` / `tts_clone_en`),
        a 'clone:...' id resolved against the clone registry at synthesis time.
      - Kokoro (English only): `tts_voice_kokoro`.
      - Piper / SAPI: the Piper voice id (`tts_voice_de` / `tts_voice_en`)."""
    engine = engine_for_lang(settings, lang)
    if is_german(lang):
        if engine == CHATTERBOX:
            return getattr(settings, "tts_clone_de", "") or ""
        return getattr(settings, "tts_voice_de", "") or ""
    if engine == CHATTERBOX:
        return getattr(settings, "tts_clone_en", "") or ""
    if engine == KOKORO:
        return getattr(settings, "tts_voice_kokoro", "") or ""
    return getattr(settings, "tts_voice_en", "") or ""


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


class KokoroEngine(TtsEngine):
    """Local, offline Kokoro-82M voices (ONNX). Natural English; NO German.

    Kokoro-82M is Apache-2.0 and runs fully offline once its model
    (kokoro-v1.0.onnx, ~310 MB) and voice pack (voices-v1.0.bin, ~27 MB) are in
    <voices_dir>/kokoro/. Synthesis needs a phonemizer; we point phonemizer-fork at
    the espeak-ng bundled by espeakng-loader so no system espeak install is required.
    All imports (kokoro_onnx, phonemizer, espeakng_loader, Qt) are lazy and every
    failure path degrades to silence - the engine reports `available=False` and the
    factory falls back, so the module loads and the app runs with none of this present.

    Used for English only; German callers should use PiperEngine (see engine_for_lang)."""

    name = KOKORO

    # One shared Kokoro session per process - the model is large and slow to load.
    _shared = None            # the loaded kokoro_onnx.Kokoro, or False if it failed
    _shared_key = None        # (model_path, voices_path) the shared session was built for

    def __init__(self, voices_dir: Path, voice_en: str = "af_heart",
                 rate: float = 1.0, volume: float = 1.0) -> None:
        self.kokoro_dir = Path(voices_dir) / KOKORO_SUBDIR
        self.voice_en = voice_en or "af_heart"
        self.rate = rate
        self.volume = volume
        self._thread = None
        self.available = self._probe()

    def model_path(self) -> Path:
        return self.kokoro_dir / KOKORO_MODEL_FILE

    def voices_path(self) -> Path:
        return self.kokoro_dir / KOKORO_VOICES_FILE

    def _probe(self) -> bool:
        """True only if the package, phonemizer and both model files are present."""
        if not (self.model_path().exists() and self.voices_path().exists()):
            return False
        try:
            import kokoro_onnx  # noqa: F401
        except Exception:
            return False
        try:
            import espeakng_loader  # noqa: F401
            from phonemizer.backend.espeak.wrapper import EspeakWrapper  # noqa: F401
        except Exception:
            return False
        return True

    def _kokoro(self):
        """Load (and cache, per process) the Kokoro session, or None on any failure."""
        key = (str(self.model_path()), str(self.voices_path()))
        if KokoroEngine._shared is not None and KokoroEngine._shared_key == key:
            return KokoroEngine._shared or None
        try:
            import espeakng_loader
            from phonemizer.backend.espeak.wrapper import EspeakWrapper

            # Route phonemizer at the bundled espeak-ng (no system install needed).
            EspeakWrapper.set_library(espeakng_loader.get_library_path())
            EspeakWrapper.set_data_path(espeakng_loader.get_data_path())

            from kokoro_onnx import Kokoro
            session = Kokoro(str(self.model_path()), str(self.voices_path()))
        except Exception:
            KokoroEngine._shared = False        # remember the failure; don't retry
            KokoroEngine._shared_key = key
            return None
        KokoroEngine._shared = session
        KokoroEngine._shared_key = key
        return session

    def synth_wav(self, text: str, lang: str, out_path: Path) -> Optional[Path]:
        """Synthesize cleaned `text` to a WAV file. Returns the path, or None on failure.

        Pure of Qt - used by both the live player and offline sample generation/tests.
        `lang` is accepted for parity with the other engines; Kokoro is English-only,
        the espeak code is derived from the voice id (US vs UK)."""
        spoken = clean_for_speech(text)
        if not spoken:
            return None
        session = self._kokoro()
        if session is None:
            return None
        voice = self.voice_en
        if voice not in getattr(session, "voices", {}):
            return None
        try:
            import soundfile as sf

            # Kokoro speed clamps to 0.5..2.0; our rate already lives in that band.
            speed = max(0.5, min(2.0, self.rate or 1.0))
            samples, sample_rate = session.create(
                spoken, voice=voice, speed=speed, lang=kokoro_lang(voice))
            if self.volume != 1.0:
                samples = samples * max(0.0, min(1.0, self.volume))
            out_path = Path(out_path)
            sf.write(str(out_path), samples, sample_rate)
            return out_path
        except Exception:
            return None

    def speak(self, text: str, lang: str) -> None:
        # Synthesize on a worker thread (model inference blocks), then play via Qt.
        import tempfile
        import threading

        def _run():
            tmp = Path(tempfile.gettempdir()) / "serenity_tts_kokoro.wav"
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


class ChatterboxEngine(TtsEngine):
    """Resemble AI Chatterbox Multilingual (PyTorch). Natural German + English, cloneable.

    Chatterbox does ZERO-SHOT voice cloning: given a short reference clip (the user's
    "drop a clip" voice), it reproduces that voice in the target language. It is the
    natural + cloneable engine for German (Kokoro has no German) and an English option.
    It is heavy (PyTorch + model weights via huggingface_hub), so EVERYTHING is lazy:
    torch, the chatterbox package and the model load only on first synthesis, and any
    missing dep / weight / GPU degrades the engine to available=False (the factory then
    falls back). MIT-licensed, runs offline once weights are cached.

    The voice id is a 'clone:...' registry id; the engine resolves it to a reference
    clip via the CloneRegistry. With no clone selected it speaks in Chatterbox's default
    voice. Used for German and (optionally) English; see engine_for_lang / voice_for_lang."""

    name = CHATTERBOX

    # One shared multilingual model per process - weights are large and slow to load.
    _shared = None            # the loaded ChatterboxMultilingualTTS, or False if it failed

    def __init__(self, voices_dir: Path, voice_id: str = "",
                 rate: float = 1.0, volume: float = 1.0) -> None:
        self.voices_dir = Path(voices_dir)
        self.voice_id = voice_id or ""
        self.rate = rate
        self.volume = volume
        self._thread = None
        self.available = self._probe()

    def _probe(self) -> bool:
        """True only if torch + the chatterbox package import (weights load lazily).

        We do not download weights here - that happens on first real synthesis - so the
        probe is cheap and the engine is advertised whenever the deps are installed."""
        try:
            import torch  # noqa: F401
            import chatterbox  # noqa: F401
        except Exception:
            return False
        return True

    def _clip_for_voice(self) -> Optional[str]:
        """Resolve our 'clone:...' voice id to a reference clip path, or None.

        None means "no clone selected" -> Chatterbox uses its built-in default voice."""
        from .voice_clones import CloneRegistry, is_clone_voice
        if not is_clone_voice(self.voice_id):
            return None
        clone = CloneRegistry(self.voices_dir).get(self.voice_id)
        if clone is not None and clone.exists():
            return clone.clip
        return None

    def _model(self):
        """Load (and cache, per process) the Chatterbox multilingual model, or None."""
        if ChatterboxEngine._shared is not None:
            return ChatterboxEngine._shared or None
        try:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        except Exception:
            ChatterboxEngine._shared = False        # remember the failure; don't retry
            return None
        ChatterboxEngine._shared = model
        return model

    def synth_wav(self, text: str, lang: str, out_path: Path) -> Optional[Path]:
        """Synthesize cleaned `text` to a WAV file. Returns the path, or None on failure.

        Pure of Qt - used by the live player, the cache pre-warm and offline samples.
        `lang` selects the Chatterbox language_id ('de'/'en'); a selected clone supplies
        the reference clip (audio_prompt_path). Degrades to None on any failure."""
        spoken = clean_for_speech(text)
        if not spoken:
            return None
        model = self._model()
        if model is None:
            return None
        language_id = "de" if is_german(lang) else "en"
        clip = self._clip_for_voice()
        try:
            import soundfile as sf

            kwargs = {"language_id": language_id}
            if clip:
                kwargs["audio_prompt_path"] = clip
            wav = model.generate(spoken, **kwargs)
            # Chatterbox returns a torch tensor (1, N) at model.sr; flatten to 1-D numpy.
            samples = wav.detach().cpu().numpy().squeeze() if hasattr(wav, "detach") else wav
            if self.volume != 1.0:
                samples = samples * max(0.0, min(1.0, self.volume))
            sample_rate = int(getattr(model, "sr", 24000))
            out_path = Path(out_path)
            sf.write(str(out_path), samples, sample_rate)
            return out_path
        except Exception:
            return None

    def speak(self, text: str, lang: str) -> None:
        # Synthesize on a worker thread (model inference blocks), then play via Qt.
        import tempfile
        import threading

        def _run():
            tmp = Path(tempfile.gettempdir()) / "serenity_tts_chatterbox.wav"
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
                      voice_de: str = "", voice_en: str = "",
                      voice_kokoro: str = "") -> list[str]:
    """Names of backends that can actually run right now (NOOP always last).

    Kokoro is listed only when its model + voice pack and deps are present; it is
    English-only, so it never appears for the German side of the picker. Chatterbox is
    listed when torch + the chatterbox package are installed (weights load lazily); it
    works for both German and English and supports voice cloning."""
    found = []
    base = voices_dir or Path(".")
    if KokoroEngine(base, voice_kokoro or "af_heart").available:
        found.append(KOKORO)
    if ChatterboxEngine(base).available:
        found.append(CHATTERBOX)
    if PiperEngine(base, voice_de, voice_en).available:
        found.append(PIPER)
    if Sapi5Engine(voice_de, voice_en).available:
        found.append(SAPI)
    found.append(NOOP)
    return found


def choose_engine(preferred: str, installed: list[str]) -> str:
    """Pick an engine id: honor `preferred` if installed, else best -> noop.

    Order of preference: the requested engine, then kokoro, chatterbox, piper, sapi,
    then noop. Pure function so the fallback ladder is unit-tested without a backend."""
    order = [preferred, KOKORO, CHATTERBOX, PIPER, SAPI, NOOP]
    for name in order:
        if name in installed:
            return name
    return NOOP


def make_engine(settings, lang: str = "en") -> TtsEngine:
    """Build the TTS engine for `lang`, degrading gracefully to a stub.

    Engine + voice are chosen PER LANGUAGE (engine_for_lang / voice_for_lang): English
    may use Kokoro (natural) or a Chatterbox clone; German may use Chatterbox (natural +
    cloneable) or Piper (Kokoro has no German). Reads voices_dir / per-language voice ids
    / rate / volume off `settings`. Never raises: if the preferred engine is not
    installed, falls back down the ladder to NoopEngine so the app always has a working
    (silent) engine."""
    from . import paths

    voices_dir = Path(getattr(settings, "voices_dir", "") or paths.voices_dir())
    voice_de = getattr(settings, "tts_voice_de", "")
    voice_en = getattr(settings, "tts_voice_en", "")
    voice_kokoro = getattr(settings, "tts_voice_kokoro", "") or "af_heart"
    rate = float(getattr(settings, "tts_rate", 1.0) or 1.0)
    volume = float(getattr(settings, "tts_volume", 1.0) or 1.0)
    preferred = engine_for_lang(settings, lang)
    clone_voice = voice_for_lang(settings, lang) if preferred == CHATTERBOX else ""

    installed = available_engines(voices_dir, voice_de, voice_en, voice_kokoro)
    # German must never land on Kokoro (it has no German voices); drop it from the
    # ladder so a German request degrades chatterbox -> piper -> sapi -> noop, not Kokoro.
    if is_german(lang):
        installed = [e for e in installed if e != KOKORO]
    chosen = choose_engine(preferred, installed)

    if chosen == KOKORO:
        return KokoroEngine(voices_dir, voice_kokoro, rate, volume)
    if chosen == CHATTERBOX:
        return ChatterboxEngine(voices_dir, clone_voice, rate, volume)
    if chosen == PIPER:
        return PiperEngine(voices_dir, voice_de, voice_en, rate, volume)
    if chosen == SAPI:
        return Sapi5Engine(voice_de, voice_en, rate, volume)
    return NoopEngine()


# --------------------------------------------------------------------------- #
# Render cache + pre-warm (latency optimization).
# --------------------------------------------------------------------------- #

def cache_voice_id(engine: TtsEngine) -> str:
    """The voice id to key the render cache on for this engine instance.

    The cache key is (engine name, this id, exact text); the id pins which voice/clone
    rendered the audio so two voices never share a cached file. Pure (reads attributes)."""
    for attr in ("voice_id", "voice_en", "voice_de"):
        val = getattr(engine, attr, "")
        if val:
            return str(val)
    return ""


def synth_cached(engine: TtsEngine, cache, text: str, lang: str) -> Optional[Path]:
    """Synthesize `text` for `lang`, serving / filling the render cache. Returns a WAV path.

    The cache is keyed on (engine name, voice id, EXACT final spoken text) - the same
    cleanup the engine applies, so a hit replays byte-identical audio. On a miss it
    synthesizes to a temp file, adopts it into the cache, and returns the cached path.
    Returns None when synthesis fails or the engine cannot speak (caller stays silent).
    `cache` may be None to bypass caching entirely (then this just synthesizes)."""
    spoken = clean_for_speech(text)
    if not spoken or not hasattr(engine, "synth_wav"):
        return None
    voice_id = cache_voice_id(engine)
    if cache is not None:
        hit = cache.get(engine.name, voice_id, spoken)
        if hit is not None:
            return hit
    import tempfile
    tmp = Path(tempfile.gettempdir()) / f"serenity_tts_{engine.name}_synth.wav"
    rendered = engine.synth_wav(spoken, lang, tmp)
    if rendered is None:
        return None
    if cache is not None:
        cached = cache.put(engine.name, voice_id, spoken, rendered)
        if cached is not None:
            return cached
    return rendered


def fixed_voice_lines(lines_data: dict, lang: str) -> list[str]:
    """Every fully-FIXED voice line (no {slots}) for a language, for pre-warming.

    Pre-warm renders WHOLE sentences only - we never stitch fixed + variable audio
    (prosody breaks, it sounds choppy), so slotted lines are skipped here and cached on
    first real synthesis instead. Pure: reads the loaded voice_lines catalog. Falls back
    to the 'en' bucket for an event when the requested language bucket is missing."""
    out: list[str] = []
    seen = set()
    for _event, buckets in (lines_data or {}).items():
        arr = buckets.get(lang) or buckets.get("en") or []
        for line in arr:
            if "{" in line or "}" in line:
                continue            # slotted - cached on first real use, not pre-warmed
            if line not in seen:
                seen.add(line)
                out.append(line)
    return out


def prewarm(engine: TtsEngine, cache, lines: list[str], lang: str,
            should_stop=None) -> int:
    """Render + cache each fixed line so it plays instantly later. Returns lines warmed.

    Synchronous and pure of Qt (call it on a background thread). Honors an optional
    `should_stop()` predicate so a voice change can cancel an in-flight pre-warm, and
    skips lines already cached. Safe with an unavailable engine (renders nothing)."""
    if cache is None or not getattr(engine, "available", False):
        return 0
    warmed = 0
    voice_id = cache_voice_id(engine)
    for line in lines:
        if should_stop is not None and should_stop():
            break
        spoken = clean_for_speech(line)
        if not spoken or cache.has(engine.name, voice_id, spoken):
            continue
        if synth_cached(engine, cache, line, lang) is not None:
            warmed += 1
    return warmed
