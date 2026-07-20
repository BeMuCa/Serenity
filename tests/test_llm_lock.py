"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Verify the process-wide inference lock on LlamaCppLLM serializes
         concurrent generate() calls and that blocking=False degrades to "".
Role:    Guards fold 11.2 (worker vs synchronous RAG/Ask race the shared llama).

Test classes:
- TestInferenceLock — serialization under threads + non-blocking degrade
============================================================
"""
import threading
import time

from serenity.core.llm import LlamaCppLLM, StubLLM


class _FakeModel:
    """Stands in for llama_cpp.Llama: records max concurrency across generate calls."""
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._probe = threading.Lock()

    def create_chat_completion(self, messages, max_tokens, temperature):
        with self._probe:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._probe:
            self.active -= 1
        return {"choices": [{"message": {"content": "ok"}}]}


class TestInferenceLock:
    def _engine(self, fake):
        eng = LlamaCppLLM(model_path=None)    # no real model file
        eng.model_path = "x"                  # non-None so _llama() proceeds past its guard
        eng.n_ctx = 4096
        LlamaCppLLM._shared = fake            # inject the fake as the loaded singleton
        LlamaCppLLM._shared_key = ("x", 4096) # matches (str(model_path), n_ctx) in _llama()
        return eng

    def teardown_method(self):
        LlamaCppLLM._shared = None
        LlamaCppLLM._shared_key = None

    def test_concurrent_generate_serializes(self):
        fake = _FakeModel()
        eng = self._engine(fake)
        threads = [threading.Thread(target=lambda: eng.generate("hi")) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert fake.max_active == 1        # never two inferences at once

    def test_non_blocking_returns_empty_when_held(self):
        fake = _FakeModel()
        eng = self._engine(fake)
        LlamaCppLLM._lock.acquire()
        try:
            assert eng.generate("hi", blocking=False) == ""
        finally:
            LlamaCppLLM._lock.release()

    def test_stub_accepts_blocking_kwarg(self):
        assert StubLLM().generate("hi", blocking=False) != None
