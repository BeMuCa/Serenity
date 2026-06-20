"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Pluggable, privacy-first speech-to-text (STT) so Serenity can capture by voice.
Role:    The on-device transcription seam behind phase2_stubs.TranscriptionService. Takes
         an audio FILE path (mic/recording UI is platform-specific and lives in the app
         layer, NOT here) and returns text. A Transcriber Protocol lets tests inject a
         deterministic StubTranscriber while the real backend, WhisperTranscriber, is a lazy
         faster-whisper class that degrades to available=False when its optional dep/model
         is absent - mirroring core.tts engines and semantic.E5Embedder. transcribe_to_capture
         bridges STT to the EXISTING CaptureRouter.route so a spoken utterance flows into the
         same confirm + undo capture path as typed text. Nothing heavy is resident at idle:
         the faster-whisper import + model load happen only on the first transcribe(), and the
         model is shared per process like KokoroEngine._shared / E5Embedder._shared.

Functions:
- transcribe_to_capture(audio_path, router, transcriber=None) -> Capture | None - transcribe
  an audio file then route the text through CaptureRouter.route (parse_capture path)

Classes:
- Transcriber - typing.Protocol seam: name / available + transcribe(audio_path) -> str
- StubTranscriber - deterministic, dependency-free transcriber (tests + the always-safe default)
- WhisperTranscriber - real backend: lazy faster-whisper (tiny/base, low-RAM), shared model
  per process, available=False when faster-whisper / the model is absent
============================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .parser import Capture
    from .phase2_stubs import CaptureRouter

# faster-whisper model sizes. tiny (~75 MB) / base (~145 MB) keep the low-RAM idle
# principle: a personal secretary should transcribe a short capture without a big model.
# Bigger sizes stay reachable by passing model_size=, but the default is low-RAM.
WHISPER_TINY = "tiny"
WHISPER_BASE = "base"


# --------------------------------------------------------------------------- #
# Transcriber seam (a Protocol; tests inject a stub, faster-whisper is one real impl).
# --------------------------------------------------------------------------- #

@runtime_checkable
class Transcriber(Protocol):
    """An audio-file -> text backend. Implementations must be safe to call headless.

    `available` is False when the dep / model is absent so the caller can degrade rather
    than crash; `name` tags the backend. transcribe() takes a path to an audio FILE (the
    recording UI is platform-specific and lives in the app layer, not here) and returns the
    recognized text, or "" when nothing can be transcribed."""

    name: str
    available: bool

    def transcribe(self, audio_path: str) -> str: ...


class StubTranscriber:
    """Deterministic, dependency-free transcriber for tests + the always-safe default.

    Returns a fixed canned transcript keyed off the audio file's stem (its base name
    without extension), so the same file always yields the same text across calls and
    processes - making transcribe()/transcribe_to_capture() unit-testable with no model or
    audio decoding. A small canned map covers the common capture utterances; anything else
    falls back to a deterministic string derived from the stem. It never touches the file's
    bytes, so a path that does not exist still transcribes (tests pass synthetic names)."""

    name = "stub"
    available = True

    # Canned transcripts keyed on the audio file stem (lowercased). Mirrors the voice
    # grammar used by parser._INTENT_KEYWORDS so transcribe_to_capture yields real intents.
    _CANNED: dict[str, str] = {
        "todo": "Todo buy milk tomorrow",
        "meeting": "Meeting with Anna on Monday",
        "reminder": "Remind me to call the dentist tomorrow",
        "note": "Note the wifi password is in the drawer",
        "idea": "Idea a privacy-first secretary app",
    }

    def transcribe(self, audio_path: str) -> str:
        stem = Path(audio_path).stem.lower()
        if stem in self._CANNED:
            return self._CANNED[stem]
        # Deterministic fallback: stem -> a stable note-like utterance. Hyphens/underscores
        # become spaces so a name like "buy-milk" reads naturally; never an em-dash.
        words = stem.replace("-", " ").replace("_", " ").strip()
        return f"Note {words}".strip() if words else ""


class WhisperTranscriber:
    """Real backend: faster-whisper (CTranslate2 Whisper), on-device. Lazy + graceful.

    faster-whisper runs Whisper locally with no network once the model is cached; the model
    (tiny ~75 MB / base ~145 MB) downloads once into a per-user cache on first transcribe.
    EVERYTHING heavy is lazy: the faster_whisper import and the model load happen only on
    the first transcribe(), the model is shared per process (mirrors KokoroEngine._shared /
    E5Embedder._shared), and a missing faster-whisper / model degrades the backend to
    available=False so the caller falls back. Defaults to the 'tiny' model for the low-RAM
    idle principle; pass model_size='base' (or larger) for better accuracy on more RAM."""

    name = "whisper"

    # One faster-whisper model per (size, device, compute_type) per process - loading is
    # slow and the model is large. False marks a load that already failed (do not retry).
    _shared = None
    _shared_key = None

    def __init__(self, model_size: str = WHISPER_TINY,
                 model_dir: Optional[Path] = None,
                 device: str = "cpu", compute_type: str = "int8",
                 language: Optional[str] = None) -> None:
        self.model_size = model_size or WHISPER_TINY
        self.model_dir = Path(model_dir) if model_dir else None
        self.device = device or "cpu"
        # int8 keeps the CPU footprint small (low-RAM principle); callers on a GPU can pass
        # device='cuda' / compute_type='float16'.
        self.compute_type = compute_type or "int8"
        # None lets Whisper auto-detect (DE/EN both supported); a caller may pin 'de'/'en'.
        self.language = language
        self.available = self._probe()

    def _probe(self) -> bool:
        """True only if faster_whisper is importable (the model itself downloads lazily).

        Cheap - it does not load or download the model - so the backend is advertised
        whenever the dep is installed; the first transcribe() does the heavy work."""
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False
        return True

    def _model(self):
        """Load (and cache, per process) the faster-whisper model, or None on any failure."""
        key = (self.model_size, self.device, self.compute_type,
               str(self.model_dir) if self.model_dir else None)
        if WhisperTranscriber._shared is not None and WhisperTranscriber._shared_key == key:
            return WhisperTranscriber._shared or None
        try:
            from faster_whisper import WhisperModel

            kwargs = {"device": self.device, "compute_type": self.compute_type}
            if self.model_dir is not None:
                kwargs["download_root"] = str(self.model_dir)
            model = WhisperModel(self.model_size, **kwargs)
        except Exception:
            WhisperTranscriber._shared = False        # remember the failure; don't retry
            WhisperTranscriber._shared_key = key
            return None
        WhisperTranscriber._shared = model
        WhisperTranscriber._shared_key = key
        return model

    def transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file to text on-device. Returns "" on any failure.

        Degrades rather than raising: a missing model / unreadable file / runtime error all
        yield "" so the caller stays silent instead of crashing. The recognized segments are
        joined and whitespace-collapsed into a single capture utterance."""
        path = str(audio_path or "")
        if not path or not Path(path).exists():
            return ""
        model = self._model()
        if model is None:
            return ""
        try:
            segments, _info = model.transcribe(path, language=self.language)
            text = " ".join((seg.text or "").strip() for seg in segments)
            return " ".join(text.split()).strip()
        except Exception:
            return ""


# --------------------------------------------------------------------------- #
# STT -> capture bridge (reuses the EXISTING CaptureRouter.route / parse_capture path).
# --------------------------------------------------------------------------- #

def transcribe_to_capture(audio_path: str, router: "CaptureRouter",
                          transcriber: "Optional[Transcriber]" = None) -> "Optional[Capture]":
    """Transcribe an audio file, then route the text into a Capture via CaptureRouter.route.

    The thin seam that joins on-device STT to the existing confirm + undo capture flow: the
    transcriber turns the audio FILE into text and that text is handed to the SAME
    CaptureRouter.route the typed-capture path uses (which today runs parse_capture), so a
    spoken utterance and a typed one converge on one structured Capture. The router NEVER
    writes directly - its Capture goes through the confirm + undo flow, exactly as typed
    captures do. `transcriber` defaults to a StubTranscriber (deterministic, dependency-free)
    so callers without the optional faster-whisper backend still exercise the seam. Returns
    None when transcription yields no usable text (empty / whitespace), so the caller can
    skip the confirm dialog rather than route an empty capture."""
    tr = transcriber if transcriber is not None else StubTranscriber()
    text = (tr.transcribe(audio_path) or "").strip()
    if not text:
        return None
    return router.route(text)
