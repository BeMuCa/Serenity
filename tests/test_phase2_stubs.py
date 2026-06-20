"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for the Phase-2 stub seams (router fallback + NotImplemented).
Role:    Guards that Phase-1 callers can use the entry points today: CaptureRouter
         falls back to the deterministic parser, routes via an injected LLMEngine when one
         is available (and degrades on bad / non-JSON output), the model-backed load_model
         / transcription methods raise NotImplementedError (no fake demos), and a bare
         SemanticIndex (no embedder) reports available=False and degrades search() to []
         (the semantic engine itself is exercised in test_semantic.py; the LLM seam in
         test_llm.py).

Test classes:
- TestPhase2Stubs - router fallback + load_model NotImplemented
- TestCaptureRouterLLM - LLM-assisted routing via a stub engine + degrade paths
============================================================
"""

import pytest

from serenity.core.phase2_stubs import CaptureRouter, SemanticIndex, TranscriptionService


class _StubEngine:
    """A minimal LLMEngine for the router tests: returns a fixed canned reply.

    `available` and `name` mirror the real seam; `generate` ignores its args and returns
    whatever canned text the test configured (so we can feed valid JSON, junk, or '')."""

    name = "test-stub"

    def __init__(self, reply: str, available: bool = True) -> None:
        self._reply = reply
        self.available = available
        self.calls: list[tuple] = []

    def generate(self, prompt, system=None, max_tokens=256):
        self.calls.append((prompt, system, max_tokens))
        return self._reply


class _BoomEngine:
    """An available engine whose generate() raises - the router must still not crash."""

    name = "boom"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        raise RuntimeError("inference exploded")


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


class TestCaptureRouterLLM:
    def test_available_reflects_engine(self):
        assert CaptureRouter().available is False
        assert CaptureRouter(engine=None).available is False
        assert CaptureRouter(_StubEngine('{}', available=False)).available is False
        assert CaptureRouter(_StubEngine('{}', available=True)).available is True

    def test_routes_via_engine_intent_and_title(self):
        # The parser would call this a plain note; the LLM relabels it a todo + cleans title.
        eng = _StubEngine('{"intent": "todo", "title": "Buy oat milk"}')
        cap = CaptureRouter(eng).route("oat milk thing")
        assert cap.intent == "todo"
        assert cap.title == "Buy oat milk"
        assert eng.calls and eng.calls[0][1] is not None  # a system prompt was passed

    def test_engine_json_in_prose_is_extracted(self):
        # Real models wrap JSON in fences / chatter; the first {...} object is used.
        eng = _StubEngine('Sure!\n```json\n{"intent": "note_idea", "title": "App idea"}\n```')
        cap = CaptureRouter(eng).route("an app idea")
        assert cap.intent == "note_idea"
        assert cap.title == "App idea"

    def test_brace_in_think_block_before_object_is_skipped(self):
        # The default model (Qwen3) is a reasoning model: it emits a <think>...</think> block
        # that routinely contains a stray brace while reasoning about the output format. A
        # greedy regex would splice that brace into the real object and fail to parse,
        # discarding a valid result. The balanced scan must take the first COMPLETE object.
        eng = _StubEngine(
            '<think>format is {intent, title}</think>\n'
            '{"intent": "todo", "title": "Buy oat milk"}'
        )
        cap = CaptureRouter(eng).route("oat milk thing")
        assert cap.intent == "todo"
        assert cap.title == "Buy oat milk"

    def test_first_of_multiple_objects_is_used(self):
        # Two JSON objects in the reply: the FIRST complete top-level object wins (not a
        # greedy span from the first '{' to the last '}', which would not parse).
        eng = _StubEngine(
            '{"intent": "meeting", "title": "Standup"}\n'
            '{"intent": "note", "title": "ignored second object"}'
        )
        cap = CaptureRouter(eng).route("standup")
        assert cap.intent == "meeting"
        assert cap.title == "Standup"

    def test_brace_inside_json_string_is_not_a_delimiter(self):
        # A '}' inside a JSON string literal must not close the object early.
        eng = _StubEngine('{"intent": "note", "title": "use {curly} braces"}')
        cap = CaptureRouter(eng).route("braces note")
        assert cap.intent == "note"
        assert cap.title == "use {curly} braces"

    def test_reminder_intent_sets_flag(self):
        eng = _StubEngine('{"intent": "reminder", "title": "Call mom"}')
        cap = CaptureRouter(eng).route("call mom")
        assert cap.intent == "reminder"
        assert cap.reminder is True

    def test_degrades_when_engine_none(self):
        # No engine -> pure parse_capture (Phase-1 behavior).
        cap = CaptureRouter(engine=None).route("Todo buy milk tomorrow")
        assert cap.intent == "todo"
        assert "buy milk" in cap.title

    def test_degrades_when_engine_unavailable(self):
        # An unavailable engine is never called; the parser baseline is returned.
        eng = _StubEngine('{"intent": "meeting", "title": "Hijacked"}', available=False)
        cap = CaptureRouter(eng).route("Todo buy milk tomorrow")
        assert cap.intent == "todo"
        assert "buy milk" in cap.title
        assert eng.calls == []  # not consulted

    def test_degrades_on_non_json_output(self):
        eng = _StubEngine("I cannot help with that.")
        cap = CaptureRouter(eng).route("Todo buy milk tomorrow")
        assert cap.intent == "todo"          # parser baseline kept
        assert "buy milk" in cap.title

    def test_degrades_on_invalid_json(self):
        eng = _StubEngine('{"intent": "todo", "title": ')  # truncated / unparseable
        cap = CaptureRouter(eng).route("Todo buy milk tomorrow")
        assert cap.intent == "todo"
        assert "buy milk" in cap.title

    def test_degrades_on_empty_output(self):
        eng = _StubEngine("")
        cap = CaptureRouter(eng).route("Todo buy milk tomorrow")
        assert cap.intent == "todo"
        assert "buy milk" in cap.title

    def test_invalid_intent_is_ignored_but_title_kept(self):
        # An out-of-vocabulary intent is rejected (baseline intent kept); a valid title
        # still merges - a partially-valid reply improves without corrupting.
        eng = _StubEngine('{"intent": "purchase", "title": "Buy milk"}')
        cap = CaptureRouter(eng).route("Todo grab milk tomorrow")
        assert cap.intent == "todo"          # parser baseline (purchase is not valid)
        assert cap.title == "Buy milk"       # title still taken from the model
        # The deterministic date survives the merge (LLM never touches it).
        assert cap.date is not None

    def test_engine_exception_degrades(self):
        cap = CaptureRouter(_BoomEngine()).route("Todo buy milk tomorrow")
        assert cap.intent == "todo"
        assert "buy milk" in cap.title

    def test_missing_slots_recomputed_after_merge(self):
        # LLM upgrades a bare note to a meeting with no date -> 'date' becomes required.
        eng = _StubEngine('{"intent": "meeting", "title": "Sync with team"}')
        cap = CaptureRouter(eng).route("sync with team")
        assert cap.intent == "meeting"
        assert "date" in cap.missing

    def test_confidence_bumped_on_clean_llm_merge(self):
        # A weak parse ('oat milk thing' -> low-confidence note) upgraded by the LLM into a
        # clean todo+title must report a confident score, not the stale parser baseline, so
        # the documented confirm flow (gates on confidence < 0.55) does not misfire.
        weak = CaptureRouter().route("oat milk thing")
        assert weak.confidence < 0.75  # the parser baseline is genuinely low here
        eng = _StubEngine('{"intent": "todo", "title": "Buy oat milk"}')
        cap = CaptureRouter(eng).route("oat milk thing")
        assert cap.confidence >= 0.75

    def test_confidence_not_lowered_for_partial_merge(self):
        # An invalid intent with only a title is a partial merge - confidence must stay the
        # parser baseline (the bump needs BOTH a valid intent and a title); never lowered.
        base = CaptureRouter().route("Todo grab milk tomorrow")
        eng = _StubEngine('{"intent": "purchase", "title": "Buy milk"}')
        cap = CaptureRouter(eng).route("Todo grab milk tomorrow")
        assert cap.confidence == base.confidence

    def test_transcription_not_implemented(self):
        assert TranscriptionService().available is False
        with pytest.raises(NotImplementedError):
            TranscriptionService().transcribe("a.wav")

    def test_semantic_index_no_embedder_degrades(self):
        # A bare SemanticIndex (no embedder) stays unavailable and degrades: search()
        # returns [] (no longer raises) and index() is a harmless no-op.
        idx = SemanticIndex()
        assert idx.available is False
        assert idx.search("anything") == []
        idx.index([])  # must not raise
