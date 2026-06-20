"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Per-task PERSONALIZED voice lines - Serenity's short, friendly one-liner for an
         individual active todo, authored ahead of time by the local LLM during a break so
         the mascot can read a tailored line the moment a task is started.
Role:    The data + generation half of FEATURE 5 (the break-time per-task voice-line job;
         the job that drives this lives in core.maintenance, off the UI path). Two pieces:
         a TaskLineStore (a BOUNDED, in-memory map of todo-id -> a sanitized spoken line)
         and generate_task_lines(...), which mirrors core.digest.generate_digest's seam:
         ask the injected core.llm.LLMEngine for a line per active todo, sanitize it onto
         Serenity's voice rules (no emojis, single hyphen - reusing digest._sanitize), and
         store it; and when no engine is wired / it is unavailable / it returns nothing
         usable it cleanly DEGRADES to a no-op (nothing stored), so the mascot just falls
         back to the deterministic VoiceLines catalog. No Qt, no DB, no heavy deps: the LLM
         is injected and the store is plain memory, so this stays unit-tested headless. The
         store is in-memory by design (cheap, lost on restart - the next break regenerates),
         and the generation is INCREMENTAL + BOUNDED so a repeat break tick is cheap and a
         huge backlog can never blow the token budget or block the (synchronous) break tick.

Functions:
- generate_task_lines(todos, llm, store, *, limit, max_tokens, only_missing) -> int
  - author + store a personalized line per active todo via the LLM; returns how many were
    written this pass; a no-op (returns 0) when no usable engine is wired

Classes:
- TaskLineStore - a bounded in-memory todo-id -> spoken-line map: set / get / has / clear,
  evicting the oldest entry when the cap is reached so it can never grow unbounded
============================================================
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Optional

from .digest import _sanitize

if TYPE_CHECKING:
    from .llm import LLMEngine
    from .models import Todo


# How many active todos one break pass will author lines for. A small cap so a synchronous
# break tick stays bounded (each line is a separate generate() call) and a long backlog can
# never run away with the token budget - the top-ranked active todos are the ones the user
# is most likely to start next, so they are the ones worth a tailored line.
DEFAULT_LIMIT = 5

# Per-line token budget: one short spoken sentence, nothing more. Keeps a real model terse
# and bounds the StubLLM echo, mirroring digest._DIGEST_MAX_TOKENS (this is much smaller -
# a single line, not a few-sentence paragraph).
DEFAULT_MAX_TOKENS = 40

# How many lines the store keeps before evicting the oldest. The generator only writes up to
# DEFAULT_LIMIT per pass, but the cap is a hard belt-and-braces bound so even a future caller
# cannot grow the map without limit; comfortably larger than the per-pass limit so a few
# passes' worth of started-then-replaced lines coexist.
DEFAULT_STORE_CAP = 64

# The system instruction handed to the LLM per todo. Constrains it to Serenity's voice: ONE
# short, warm, encouraging spoken line about starting this specific task - plain text only,
# no emojis, single "-" never a dash (CLAUDE.md user-string rules, enforced by _sanitize).
_TASK_SYSTEM = (
    "You are Serenity, a warm and encouraging personal secretary. The user is about to start "
    "the task named below. Reply with ONE short, friendly, encouraging sentence in your own "
    "voice that names or nods to the task and motivates them to begin. Plain text only, "
    "spoken aloud - no emojis, no lists, no quotes, and use a single hyphen, never a dash."
)


class TaskLineStore:
    """A bounded in-memory map of todo-id -> a sanitized, ready-to-speak personalized line.

    Plain memory by design: lines are cheap to regenerate (the next break authors fresh ones)
    and nothing personal should outlive the process, so there is no disk persistence - a
    restart simply clears it and the mascot falls back to the deterministic VoiceLines catalog
    until the next break pass refills it. BOUNDED: at most `cap` entries are kept; setting a
    new id when full evicts the OLDEST inserted id (FIFO via an OrderedDict), so a long-running
    session that starts many tasks can never grow the map without limit. Pure, Qt-free, so the
    generator and the shell can both share one instance and tests can assert its contents."""

    def __init__(self, cap: int = DEFAULT_STORE_CAP) -> None:
        self.cap = max(1, int(cap))
        self._lines: "OrderedDict[str, str]" = OrderedDict()

    def set(self, todo_id: str, line: str) -> None:
        """Store `line` for `todo_id`, evicting the oldest entry if the cap is reached.

        An empty / whitespace-only line or a missing id is ignored (nothing to speak), so the
        store only ever holds usable lines. Re-setting an existing id refreshes it in place
        AND moves it to the most-recent position, so it is not the next one evicted."""
        if not todo_id or not line or not line.strip():
            return
        if todo_id in self._lines:
            self._lines.move_to_end(todo_id)
        self._lines[todo_id] = line.strip()
        while len(self._lines) > self.cap:
            self._lines.popitem(last=False)   # evict the oldest inserted id

    def get(self, todo_id: str) -> Optional[str]:
        """The stored line for `todo_id`, or None if none was authored (the degrade signal)."""
        return self._lines.get(todo_id)

    def has(self, todo_id: str) -> bool:
        """True if a personalized line is stored for `todo_id`."""
        return todo_id in self._lines

    def clear(self) -> None:
        """Drop all stored lines (e.g. on a language change or an explicit reset)."""
        self._lines.clear()

    def __len__(self) -> int:
        return len(self._lines)


def generate_task_lines(
    todos: "list[Todo]",
    llm: "Optional[LLMEngine]",
    store: TaskLineStore,
    *,
    limit: int = DEFAULT_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    only_missing: bool = True,
) -> int:
    """Author + store a personalized spoken line for up to `limit` active todos via the LLM.

    Mirrors core.digest.generate_digest's seam shape: ask the injected LLMEngine for a line,
    sanitize it onto Serenity's voice rules (digest._sanitize - no emojis, single hyphen),
    and store it keyed by todo id. On ANY failure for the whole pass - no engine, engine
    unavailable - this is a clean NO-OP that stores nothing and returns 0, so the break job
    cleanly degrades on a base install (no [llm] extra) and the mascot just keeps using the
    deterministic VoiceLines catalog. A per-todo inference error or empty reply is skipped
    (that todo simply gets no tailored line) without aborting the rest of the pass; nothing
    ever raises into the caller.

    BOUNDED + INCREMENTAL: only the first `limit` todos are considered (the ranked-active
    list the shell passes is most-relevant-first), and with `only_missing` True a todo that
    already has a stored line is skipped - so a repeat break tick over an unchanged backlog
    does little to no work and never re-spends the token budget. Returns the number of lines
    actually written this pass (0 when the engine is unusable or every candidate was already
    present)."""
    if llm is None or not getattr(llm, "available", False):
        return 0
    written = 0
    for todo in list(todos)[: max(0, int(limit))]:
        todo_id = getattr(todo, "id", None)
        title = (getattr(todo, "title", "") or "").strip()
        if not todo_id or not title:
            continue
        if only_missing and store.has(todo_id):
            continue
        try:
            reply = llm.generate(title, system=_TASK_SYSTEM, max_tokens=max_tokens)
        except Exception:
            continue   # one bad todo never aborts the pass; it just gets no tailored line
        line = _sanitize((reply or "").strip())
        if not line:
            continue   # empty / unusable reply -> leave it to the deterministic fallback
        store.set(todo_id, line)
        written += 1
    return written
