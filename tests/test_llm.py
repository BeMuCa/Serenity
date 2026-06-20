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

import sys
import types

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

    def test_shared_model_reloads_on_different_n_ctx(self, tmp_path, monkeypatch):
        # The shared-model cache is keyed by (path, n_ctx): two instances with the SAME path
        # but DIFFERENT n_ctx must each get a model loaded with their own context window,
        # not silently inherit the first loader's. We fake llama_cpp.Llama to record n_ctx.
        gguf = tmp_path / "model.gguf"
        gguf.write_bytes(b"gguf")
        loaded = []

        class _FakeLlama:
            def __init__(self, model_path, n_ctx, verbose=False):
                loaded.append(n_ctx)
                self.n_ctx_value = n_ctx

        fake_mod = types.ModuleType("llama_cpp")
        fake_mod.Llama = _FakeLlama
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_mod)
        # Isolate the process-wide shared slot for this test.
        monkeypatch.setattr(LlamaCppLLM, "_shared", None, raising=False)
        monkeypatch.setattr(LlamaCppLLM, "_shared_key", None, raising=False)

        m1 = LlamaCppLLM(model_path=gguf, n_ctx=2048)._llama()
        m2 = LlamaCppLLM(model_path=gguf, n_ctx=8192)._llama()
        assert m1.n_ctx_value == 2048
        assert m2.n_ctx_value == 8192
        assert loaded == [2048, 8192]  # the n_ctx change forced a reload
        # A second instance with the SAME (path, n_ctx) reuses the cached model.
        m3 = LlamaCppLLM(model_path=gguf, n_ctx=8192)._llama()
        assert m3 is m2
        assert loaded == [2048, 8192]  # no extra load


class TestProtocol:
    def test_stub_satisfies_protocol(self):
        assert isinstance(StubLLM(), LLMEngine)

    def test_llamacpp_satisfies_protocol(self, tmp_path):
        # Even unavailable, the backend structurally satisfies the seam.
        assert isinstance(LlamaCppLLM(models_dir=tmp_path), LLMEngine)
