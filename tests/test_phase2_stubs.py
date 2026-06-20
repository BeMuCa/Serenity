"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for the Phase-2 stub seams (router fallback + NotImplemented).
Role:    Guards that Phase-1 callers can use the entry points today: CaptureRouter
         falls back to the deterministic parser, the model-backed router/transcription
         methods raise NotImplementedError (no fake demos), and a bare SemanticIndex
         (no embedder) reports available=False and degrades search() to [] (the semantic
         engine itself is exercised in test_semantic.py).

Test classes:
- TestPhase2Stubs
============================================================
"""

import pytest

from serenity.core.phase2_stubs import CaptureRouter, SemanticIndex, TranscriptionService


class TestPhase2Stubs:
    def test_router_falls_back_to_parser(self):
        r = CaptureRouter()
        assert r.available is False
        cap = r.route("Todo buy milk tomorrow")
        assert cap.intent == "todo"
        assert "buy milk" in cap.title

    def test_router_model_load_not_implemented(self):
        with pytest.raises(NotImplementedError):
            CaptureRouter().load_model("model.gguf")

    def test_transcription_default_degrades_without_backend(self):
        # The default backend is the lazy WhisperTranscriber: without faster-whisper it
        # reports available=False and transcribe() degrades to "" instead of raising
        # (the seam is now pluggable - see test_stt.py for the StubTranscriber path).
        svc = TranscriptionService()
        assert svc.available is False
        assert svc.transcribe("a.wav") == ""

    def test_semantic_index_no_embedder_degrades(self):
        # A bare SemanticIndex (no embedder) stays unavailable and degrades: search()
        # returns [] (no longer raises) and index() is a harmless no-op.
        idx = SemanticIndex()
        assert idx.available is False
        assert idx.search("anything") == []
        idx.index([])  # must not raise
