"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the on-device STT (speech-to-text) seam (core.stt).
Role:    Guards the pluggable transcription backend exercised entirely via the
         deterministic StubTranscriber (no faster-whisper, no model, no audio decode):
         transcribe() is deterministic, transcribe_to_capture() yields a Capture through
         the EXISTING CaptureRouter.route (parse_capture) path, and the real
         WhisperTranscriber degrades to available=False / "" when its optional dep is
         absent. TranscriptionService's pluggable wiring is covered here too.

Test classes:
- TestStubTranscriber
- TestTranscribeToCapture
- TestWhisperDegrade
- TestTranscriptionServiceWiring
============================================================
"""

from serenity.core.parser import Capture
from serenity.core.phase2_stubs import CaptureRouter, TranscriptionService
from serenity.core.stt import (
    StubTranscriber,
    Transcriber,
    WhisperTranscriber,
    transcribe_to_capture,
)


class TestStubTranscriber:
    def test_is_a_transcriber(self):
        # The stub satisfies the runtime-checkable Transcriber Protocol.
        tr = StubTranscriber()
        assert isinstance(tr, Transcriber)
        assert tr.available is True
        assert tr.name == "stub"

    def test_transcribe_is_deterministic(self):
        # Same audio path -> identical text across calls (and a second instance).
        tr = StubTranscriber()
        first = tr.transcribe("/captures/todo.wav")
        second = tr.transcribe("/captures/todo.wav")
        assert first == second
        assert first == StubTranscriber().transcribe("/elsewhere/todo.m4a")

    def test_canned_utterance_keyed_on_stem(self):
        # A known stem yields the canned capture grammar (extension/dir ignored).
        assert StubTranscriber().transcribe("todo.wav") == "Todo buy milk tomorrow"
        assert StubTranscriber().transcribe("/a/b/MEETING.ogg") == "Meeting with Anna on Monday"

    def test_unknown_stem_falls_back_deterministically(self):
        # An unmapped stem becomes a stable note-like utterance; hyphens become spaces.
        out = StubTranscriber().transcribe("/x/buy-milk.wav")
        assert out == "Note buy milk"
        assert out == StubTranscriber().transcribe("/y/buy-milk.flac")

    def test_empty_stem_yields_empty(self):
        assert StubTranscriber().transcribe("") == ""


class TestTranscribeToCapture:
    def test_yields_a_capture_via_router(self):
        # The recognized text is routed through the EXISTING CaptureRouter.route
        # (parse_capture) path into a structured Capture.
        cap = transcribe_to_capture("todo.wav", CaptureRouter(), StubTranscriber())
        assert isinstance(cap, Capture)
        assert cap.intent == "todo"
        assert "buy milk" in cap.title

    def test_defaults_to_stub_transcriber(self):
        # No transcriber passed -> the dependency-free StubTranscriber is used, so the
        # seam works without the optional faster-whisper backend installed.
        cap = transcribe_to_capture("meeting.wav", CaptureRouter())
        assert isinstance(cap, Capture)
        assert cap.intent == "meeting"

    def test_empty_transcription_returns_none(self):
        # Nothing usable transcribed -> None, so the caller can skip the confirm dialog
        # rather than route an empty capture.
        assert transcribe_to_capture("", CaptureRouter(), StubTranscriber()) is None

    def test_routes_raw_text_through_parser_grammar(self):
        # The full STT -> parse path: an idea utterance maps to the note_idea intent.
        cap = transcribe_to_capture("idea.wav", CaptureRouter(), StubTranscriber())
        assert cap is not None
        assert cap.intent == "note_idea"


class TestWhisperDegrade:
    def test_unavailable_without_faster_whisper(self):
        # faster-whisper is NOT installed in the test venv: the backend degrades to
        # available=False (mirrors E5Embedder / the TTS engines) - no heavy import, no
        # model download, the module still imports.
        tr = WhisperTranscriber()
        assert tr.available is False
        assert tr.name == "whisper"

    def test_transcribe_degrades_to_empty(self):
        # With no model loadable, transcribe() returns "" rather than raising.
        assert WhisperTranscriber().transcribe("nope.wav") == ""

    def test_missing_file_returns_empty(self):
        assert WhisperTranscriber().transcribe("/does/not/exist.wav") == ""

    def test_low_ram_default_model(self):
        # Default size honours the low-RAM idle principle.
        assert WhisperTranscriber().model_size == "tiny"


class TestTranscriptionServiceWiring:
    def test_wraps_injected_backend(self):
        # An injected StubTranscriber makes the service available and transcribing.
        svc = TranscriptionService(StubTranscriber())
        assert svc.available is True
        assert svc.transcribe("todo.wav") == "Todo buy milk tomorrow"

    def test_default_backend_degrades(self):
        # The default WhisperTranscriber is unavailable here; transcribe() degrades to "".
        svc = TranscriptionService()
        assert svc.available is False
        assert svc.transcribe("todo.wav") == ""

    def test_service_transcribe_to_capture(self):
        # The service convenience routes through CaptureRouter just like the helper.
        svc = TranscriptionService(StubTranscriber())
        cap = svc.transcribe_to_capture("todo.wav", CaptureRouter())
        assert isinstance(cap, Capture)
        assert cap.intent == "todo"

    def test_available_reads_through_live_backend(self):
        # available is a live read-through, not a construction-time snapshot: a backend
        # whose readiness flips AFTER the service is built is reported correctly (STT-2).
        class LazyBackend:
            name = "lazy"
            available = False

            def transcribe(self, audio_path: str) -> str:
                return ""

        backend = LazyBackend()
        svc = TranscriptionService(backend)
        assert svc.available is False
        backend.available = True  # e.g. a model file appeared / lazy probe succeeded
        assert svc.available is True

    def test_transcribe_swallows_injected_backend_errors(self):
        # The wrapper honours its own "never raises" contract even for a third-party
        # backend that raises - it yields "" instead of propagating (STT-3).
        class RaisingBackend:
            name = "boom"
            available = True

            def transcribe(self, audio_path: str) -> str:
                raise RuntimeError("backend blew up")

        svc = TranscriptionService(RaisingBackend())
        assert svc.transcribe("todo.wav") == ""
