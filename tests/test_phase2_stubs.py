"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for the Phase-2 stub seams (router fallback + NotImplemented).
Role:    Guards that Phase-1 callers can use the entry points today: CaptureRouter
         falls back to the deterministic parser, and the model-backed methods raise
         NotImplementedError (no fake demos).

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

    def test_transcription_not_implemented(self):
        assert TranscriptionService().available is False
        with pytest.raises(NotImplementedError):
            TranscriptionService().transcribe("a.wav")

    def test_semantic_index_not_implemented(self):
        idx = SemanticIndex()
        assert idx.available is False
        with pytest.raises(NotImplementedError):
            idx.search("anything")
