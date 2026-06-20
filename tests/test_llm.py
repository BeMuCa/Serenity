"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Headless unit tests for the pluggable local-LLM seam (core.llm).
Role:    Exercises the StubLLM (deterministic, dependency-free) and the lazy LlamaCppLLM's
         graceful-degrade contract WITHOUT installing llama-cpp-python or downloading any
         GGUF. Guards: StubLLM.generate() determinism + exact output + max_tokens budget +
         the always-on `available` flag; LlamaCppLLM reports available=False when the model
         file is absent and generate() returns "" rather than raising; the LLMEngine
         Protocol is satisfied by both backends.

Test classes:
- TestStubLLM - determinism, exact templated output, system prefix, max_tokens budget
- TestLlamaCppLLM - degrade-to-unavailable when the GGUF / dep is absent, safe generate()
- TestProtocol - StubLLM (and a missing-model LlamaCppLLM) satisfy LLMEngine
============================================================
"""

from serenity.core.llm import DEFAULT_MODEL_FILE, LLMEngine, LlamaCppLLM, StubLLM


class TestStubLLM:
    def test_available_is_true(self):
        # The stub is always usable - no deps, no model file.
        assert StubLLM().available is True
        assert StubLLM().name == "stub"

    def test_generate_is_deterministic(self):
        a = StubLLM().generate("buy milk tomorrow")
        b = StubLLM().generate("buy milk tomorrow")
        # Same input -> byte-identical output, every call.
        assert a == b

    def test_generate_exact_output(self):
        # The templated echo is a stable, assertable string (no model needed).
        out = StubLLM().generate("buy milk")
        assert out == "stub-llm: buy milk"

    def test_generate_with_system_prefix(self):
        out = StubLLM().generate("buy milk", system="route this")
        assert out == "[system:route this] stub-llm: buy milk"

    def test_empty_prompt(self):
        assert StubLLM().generate("") == "stub-llm: "
        assert StubLLM().generate("   ") == "stub-llm: "

    def test_max_tokens_word_budget(self):
        # max_tokens is honored as a coarse word cap, deterministically.
        out = StubLLM().generate("one two three four five", max_tokens=2)
        assert out == "stub-llm: one two"

    def test_max_tokens_zero_drops_body(self):
        out = StubLLM().generate("anything at all", max_tokens=0)
        assert out == "stub-llm: "


class TestLlamaCppLLM:
    def test_unavailable_without_model_file(self, tmp_path):
        # No GGUF in the models dir (and llama-cpp not installed here) -> not available.
        eng = LlamaCppLLM(models_dir=tmp_path)
        assert eng.available is False
        assert eng.name == "llama-cpp"
        # Its expected default model path points at the small Qwen3 GGUF.
        assert eng.model_path == tmp_path / DEFAULT_MODEL_FILE

    def test_unavailable_with_no_path(self):
        eng = LlamaCppLLM()
        assert eng.available is False
        assert eng.model_path is None

    def test_generate_degrades_to_empty_string(self, tmp_path):
        # With no usable model, generate() returns "" rather than raising, so callers
        # (CaptureRouter) fall back cleanly.
        eng = LlamaCppLLM(models_dir=tmp_path)
        assert eng.generate("buy milk", system="route this") == ""

    def test_explicit_missing_path_is_unavailable(self, tmp_path):
        missing = tmp_path / "nope.gguf"
        eng = LlamaCppLLM(model_path=missing)
        assert eng.available is False
        assert eng.model_path == missing


class TestProtocol:
    def test_stub_satisfies_protocol(self):
        assert isinstance(StubLLM(), LLMEngine)

    def test_llamacpp_satisfies_protocol(self, tmp_path):
        # Even unavailable, the backend structurally satisfies the seam.
        assert isinstance(LlamaCppLLM(models_dir=tmp_path), LLMEngine)
