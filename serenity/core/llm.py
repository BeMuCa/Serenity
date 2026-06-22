"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The pluggable LOCAL text-generation seam - one small on-device LLM behind a
         Protocol, with a deterministic stub default and a lazy llama-cpp backend.
Role:    The foundation the Phase-2 capture router (and later break-time jobs) build on.
         Holds the LLMEngine seam (a Protocol so tests inject a deterministic StubLLM
         while the real backend, LlamaCppLLM, is a lazy llama-cpp-python class that loads
         a SMALL local GGUF and degrades to available=False when llama-cpp or the model
         file is absent). Mirrors core.semantic.FastEmbedBackend + core.tts.KokoroEngine:
         EVERYTHING heavy (the llama_cpp import + the model load) is lazy inside methods,
         the loaded model is shared per process (LlamaCppLLM._shared, like
         KokoroEngine._shared), and nothing heavy is resident at idle. The model's own
         chat template is applied INSIDE the backend (system + user roles), never by the
         caller - so a caller just hands a prompt + optional system string and gets text.

Functions:
- (none - the surface is the Protocol + its two implementations)

Classes:
- LLMEngine - typing.Protocol seam: name / available + generate(prompt, system, max_tokens)
- StubLLM - deterministic, dependency-free generator (tests + the always-safe default):
  returns a stable templated echo so a test can assert the exact output
- LlamaCppLLM - real backend: lazy llama-cpp-python + a small local GGUF (default
  Qwen3-1.7B per the low-RAM principle); chat template applied here; shared per process;
  available=False when llama-cpp or the model file is absent
============================================================
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

# Default SMALL generation model for THIS seam. The low-RAM principle: this is the always-
# warm tier, deliberately tiny so it stays resident with room to spare on a 16 GB box - the
# heavier Qwen3-4B capture router / break-time models are a separate concern. Qwen3-1.7B
# (Q4_K_M, ~1.1 GB, Apache-2.0) is the lead; Qwen3-0.6B is the even-lighter fallback for
# very low-RAM machines (swap DEFAULT_MODEL_FILE). The GGUF is downloaded/placed by the
# user into <config>/models/ - this seam never pre-fetches it.
QWEN3_1_7B_FILE = "Qwen3-1.7B-Q4_K_M.gguf"      # ~1.1 GB, Apache-2.0 (the lead)
QWEN3_0_6B_FILE = "Qwen3-0.6B-Q4_K_M.gguf"      # ~0.5 GB, Apache-2.0 (low-RAM fallback)
DEFAULT_MODEL_FILE = QWEN3_1_7B_FILE

# Per-user folder a GGUF is looked up in (mirrors the voices_dir / semantic subdir
# convention). Created by the user; this module never writes here.
MODELS_SUBDIR = "models"

# Reasoning models (Qwen3 et al.) emit a hidden chain-of-thought wrapped in <think>...</think>
# BEFORE the real answer. It helps the model on hard tasks but is internal scratch work we must
# not surface - and it silently eats the max_tokens budget (truncating the actual reply). We
# disable it at the prompt (/no_think soft switch) AND strip it here as a backstop, since a
# model can ignore the switch. A truncated reply may leave an UNCLOSED <think> (no </think>);
# we drop from the opening tag to the end in that case.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove Qwen3-style <think>...</think> reasoning blocks from model output."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK.sub("", text)
    open_at = cleaned.lower().find("<think>")   # unclosed (truncated) thinking block
    if open_at != -1:
        cleaned = cleaned[:open_at]
    return cleaned.strip()


# --------------------------------------------------------------------------- #
# LLM seam (a Protocol; tests inject the stub, llama-cpp is one real impl).
# --------------------------------------------------------------------------- #

@runtime_checkable
class LLMEngine(Protocol):
    """A prompt -> text backend. Implementations apply their own chat template.

    `available` is False when the dep / model is absent so callers (CaptureRouter) degrade
    to the deterministic parser; `name` tags the engine for logging / settings. generate()
    takes the user prompt, an optional `system` instruction, and a `max_tokens` cap, and
    returns the model's text reply (the backend wraps both in the model's chat template -
    the caller never sees role markers)."""

    name: str
    available: bool

    def generate(self, prompt: str, system: Optional[str] = None,
                 max_tokens: int = 256) -> str: ...


class StubLLM:
    """Deterministic, dependency-free generator for tests + the always-safe default.

    Returns a STABLE templated echo of its inputs so a test can assert the exact output
    string, and the same inputs always produce the same text (across calls and processes).
    It touches no network and no heavy deps. The reply is the prompt (trimmed to the token
    budget) wrapped in a fixed envelope, optionally prefixed with the system instruction -
    enough for a caller's parser to be exercised without a real model. max_tokens is honored
    as a coarse word cap so the budget path is testable too."""

    name = "stub"
    available = True

    def generate(self, prompt: str, system: Optional[str] = None,
                 max_tokens: int = 256) -> str:
        body = (prompt or "").strip()
        # Coarse, deterministic budget: cap the echoed prompt to `max_tokens` words so the
        # max_tokens path is exercised without a tokenizer. <= 0 means "no body".
        budget = int(max_tokens) if max_tokens else 0
        if budget <= 0:
            body = ""
        else:
            words = body.split()
            if len(words) > budget:
                body = " ".join(words[:budget])
        sys_part = (system or "").strip()
        prefix = f"[system:{sys_part}] " if sys_part else ""
        return f"{prefix}stub-llm: {body}"


class LlamaCppLLM:
    """Real backend: a small local GGUF via llama-cpp-python. Lazy + shared + graceful.

    llama-cpp-python runs the GGUF in-process (no daemon - the verified runtime choice).
    EVERYTHING heavy is lazy: the llama_cpp import and the model load happen only on the
    first generate(), the loaded Llama is shared per process (mirrors
    core.semantic.FastEmbedBackend._shared / KokoroEngine._shared), and a missing llama-cpp /
    GGUF degrades the engine to available=False so callers fall back. The model's OWN chat
    template is applied here via create_chat_completion (system + user roles), so the
    caller hands a plain prompt + optional system string and gets text back - role markers
    never leak out. Default model is the small Qwen3-1.7B GGUF (low-RAM principle); point
    `model_path` at any GGUF, or drop one named DEFAULT_MODEL_FILE into <models_dir>/."""

    name = "llama-cpp"

    # One loaded model per process - it is large and slow to load (mirrors FastEmbedBackend).
    _shared = None            # the loaded llama_cpp.Llama, or False if it failed
    _shared_key = None        # the (model_path, n_ctx) the shared instance was built for

    def __init__(self, model_path: Optional[Path] = None,
                 models_dir: Optional[Path] = None,
                 n_ctx: int = 4096) -> None:
        # Explicit model_path wins; otherwise look for the default GGUF in models_dir.
        if model_path is not None:
            self.model_path = Path(model_path)
        elif models_dir is not None:
            self.model_path = Path(models_dir) / DEFAULT_MODEL_FILE
        else:
            self.model_path = None
        self.n_ctx = int(n_ctx) if n_ctx and n_ctx > 0 else 4096
        self.available = self._probe()

    def _probe(self) -> bool:
        """True only if llama-cpp-python is importable AND the GGUF file exists.

        Cheap - it does not load the model (the first generate() does the heavy work) - so
        the engine is advertised whenever the dep + file are present and degrades
        (available=False) the moment either is missing."""
        if self.model_path is None or not self.model_path.exists():
            return False
        try:
            import llama_cpp  # noqa: F401
        except Exception:
            return False
        return True

    def _llama(self):
        """Load (and cache, per process) the Llama model, or None on any failure."""
        if self.model_path is None:
            return None
        # Key on (path, n_ctx) so an instance that tunes n_ctx (e.g. a break-time job that
        # wants a wider window) forces a reload instead of silently inheriting the first
        # loader's context size - the context window is baked into the loaded model.
        key = (str(self.model_path), self.n_ctx)
        if LlamaCppLLM._shared is not None and LlamaCppLLM._shared_key == key:
            return LlamaCppLLM._shared or None
        try:
            from llama_cpp import Llama

            model = Llama(model_path=key[0], n_ctx=self.n_ctx, verbose=False)
        except Exception:
            LlamaCppLLM._shared = False        # remember the failure; don't retry
            LlamaCppLLM._shared_key = key
            return None
        LlamaCppLLM._shared = model
        LlamaCppLLM._shared_key = key
        return model

    def generate(self, prompt: str, system: Optional[str] = None,
                 max_tokens: int = 256) -> str:
        """Generate a text reply for `prompt`, applying the model's chat template.

        Returns "" on any failure (model absent / load error / inference error) so callers
        degrade rather than crash. The system + user messages are passed to
        create_chat_completion, which applies the GGUF's own chat template - so Qwen3's
        role markers / special tokens are handled by llama-cpp, never hand-rolled here."""
        text = (prompt or "").strip()
        if not text:
            return ""
        model = self._llama()
        if model is None:
            return ""
        messages = []
        # /no_think disables Qwen3's chain-of-thought: our tasks (routing, RAG, one-line
        # digest) are simple, so thinking only burns the max_tokens budget. strip_think()
        # below is the backstop if the model emits it anyway.
        sys_part = ((system or "").strip() + " /no_think").strip()
        messages.append({"role": "system", "content": sys_part})
        messages.append({"role": "user", "content": text})
        try:
            out = model.create_chat_completion(
                messages=messages,
                max_tokens=int(max_tokens) if max_tokens else 256,
                temperature=0.0,        # deterministic single-shot (capture routing)
            )
            return strip_think(out["choices"][0]["message"]["content"] or "")
        except Exception:
            return ""
