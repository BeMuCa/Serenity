"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Wired-up Phase-2 entry points - LLM routing, voice transcription, embeddings.
Role:    Clean interfaces the Phase-1 app can call today; they raise / no-op until the
         Phase-2 backends land (see notes/2_System_Arch.md, serenity-spec.md sec 11).
         NOT fake demos - real seams so Phase 2 slots in without reworking callers.

Classes:
- CaptureRouter - transcript -> structured JSON (llama-cpp-python + Qwen3-4B). STUB.
- TranscriptionService - audio -> text (whisper.cpp, on-device). STUB.
- SemanticIndex - note embeddings -> "Meaning" search (e5 + sqlite-vec). STUB.
============================================================
"""

from __future__ import annotations

from typing import Optional

from .models import Note
from .parser import Capture, parse_capture


class CaptureRouter:
    """Phase 2: route a transcript to a structured capture via a local LLM.

    The LLM never writes directly - its result goes through the confirm + undo flow.
    Phase 1 falls back to the deterministic parser so the seam is exercised today."""

    available = False  # flips True when a model is loaded in Phase 2

    def route(self, text: str) -> Capture:
        # Phase-1 behavior: deterministic parser (rule-based fallback path).
        return parse_capture(text)

    def load_model(self, gguf_path: str) -> None:
        raise NotImplementedError(
            "Phase 2: load a Qwen3-4B GGUF via llama-cpp-python with GBNF/json_schema "
            "constrained decoding. Validate the grammar at init and fail closed."
        )


class TranscriptionService:
    """Phase 2: on-device speech-to-text. The mic never streams out."""

    available = False

    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError(
            "Phase 2: local transcription via whisper.cpp / faster-whisper. "
            "Phase 1 captures text only - no audio is recorded."
        )


class SemanticIndex:
    """Phase 2: 'Meaning' search over note embeddings (multilingual-e5-base + sqlite-vec)."""

    available = False

    def index(self, notes: list[Note]) -> None:
        raise NotImplementedError(
            "Phase 2: embed notes with multilingual-e5-base (fastembed/ONNX) into sqlite-vec."
        )

    def search(self, query: str, top_k: int = 10) -> list[Note]:
        raise NotImplementedError(
            "Phase 2: nearest-neighbour search in sqlite-vec. Phase 1 uses keyword 'Text' search."
        )
