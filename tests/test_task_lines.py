"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Headless unit tests for the per-task voice lines (core.task_lines).
Role:    Guards FEATURE 5's data + generation half: the bounded in-memory TaskLineStore
         (set / get / has / clear, FIFO eviction at the cap) and generate_task_lines, which
         authors a personalized line per active todo via the pluggable core.llm.LLMEngine
         seam. Asserts the StubLLM path stores sanitized lines, that it DEGRADES to a no-op
         when no engine / an unavailable engine is wired, that generation is BOUNDED by the
         limit and INCREMENTAL (only_missing skips already-authored todos), and that a model
         that violates the voice rules is sanitized before it is stored. No llama-cpp / no
         model file - StubLLM and small fakes only.

Test classes:
- TestTaskLineStore - bounded store: set/get/has/clear, ignores empty lines, FIFO eviction
- TestGenerateTaskLines - StubLLM authoring, degrade-to-no-op, bounded + incremental, sanitize
============================================================
"""

from serenity.core.llm import StubLLM
from serenity.core.models import Todo
from serenity.core.task_lines import (
    DEFAULT_LIMIT,
    TaskLineStore,
    generate_task_lines,
)


def _todos(n):
    return [Todo(id=f"t{i}", title=f"Task {i}") for i in range(n)]


class _UnavailableLLM:
    name = "down"
    available = False

    def generate(self, prompt, system=None, max_tokens=256):  # pragma: no cover
        raise AssertionError("generate() must not be called when available is False")


class _RaisingLLM:
    name = "boom"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        raise RuntimeError("inference failed")


class _EmptyLLM:
    name = "empty"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        return "   "


class _DirtyLLM:
    """Emits emoji + em/en dashes - must be sanitized before being stored (mirrors digest)."""

    name = "dirty"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        return "Lets go \U0001f389 - this one matters — you have got this –"


class TestTaskLineStore:
    def test_set_get_has(self):
        s = TaskLineStore()
        assert s.get("a") is None
        assert s.has("a") is False
        s.set("a", "Go for it.")
        assert s.get("a") == "Go for it."
        assert s.has("a") is True
        assert len(s) == 1

    def test_ignores_empty_and_missing_id(self):
        s = TaskLineStore()
        s.set("a", "")
        s.set("a", "   ")
        s.set("", "non-empty")
        assert len(s) == 0

    def test_trims_stored_line(self):
        s = TaskLineStore()
        s.set("a", "  padded  ")
        assert s.get("a") == "padded"

    def test_clear(self):
        s = TaskLineStore()
        s.set("a", "x")
        s.clear()
        assert len(s) == 0
        assert s.get("a") is None

    def test_bounded_fifo_eviction(self):
        # At the cap, the OLDEST inserted id is evicted - the store can never grow unbounded.
        s = TaskLineStore(cap=2)
        s.set("a", "1")
        s.set("b", "2")
        s.set("c", "3")        # evicts "a"
        assert len(s) == 2
        assert s.has("a") is False
        assert s.has("b") and s.has("c")

    def test_reset_existing_refreshes_recency(self):
        # Re-setting an id moves it to most-recent so it is not the next evicted.
        s = TaskLineStore(cap=2)
        s.set("a", "1")
        s.set("b", "2")
        s.set("a", "1b")       # "a" becomes most-recent
        s.set("c", "3")        # evicts the now-oldest, which is "b"
        assert s.has("a") and s.get("a") == "1b"
        assert s.has("b") is False
        assert s.has("c")


class TestGenerateTaskLines:
    def test_authors_a_line_per_active_todo(self):
        todos = _todos(3)
        store = TaskLineStore()
        n = generate_task_lines(todos, StubLLM(), store)
        assert n == 3
        for t in todos:
            line = store.get(t.id)
            assert line and "stub-llm:" in line
            assert t.title in line        # the todo title reached the prompt -> the stub echo

    def test_noop_without_llm(self):
        store = TaskLineStore()
        assert generate_task_lines(_todos(3), None, store) == 0
        assert len(store) == 0

    def test_noop_when_llm_unavailable(self):
        store = TaskLineStore()
        assert generate_task_lines(_todos(3), _UnavailableLLM(), store) == 0
        assert len(store) == 0

    def test_bounded_by_limit(self):
        store = TaskLineStore()
        n = generate_task_lines(_todos(50), StubLLM(), store, limit=DEFAULT_LIMIT)
        assert n == DEFAULT_LIMIT
        assert len(store) == DEFAULT_LIMIT

    def test_incremental_skips_already_authored(self):
        todos = _todos(3)
        store = TaskLineStore()
        assert generate_task_lines(todos, StubLLM(), store) == 3
        # A repeat pass writes nothing new (only_missing default True).
        assert generate_task_lines(todos, StubLLM(), store) == 0
        assert len(store) == 3

    def test_only_missing_false_regenerates(self):
        todos = _todos(2)
        store = TaskLineStore()
        generate_task_lines(todos, StubLLM(), store)
        # Forcing regeneration re-authors every candidate.
        assert generate_task_lines(todos, StubLLM(), store, only_missing=False) == 2

    def test_skips_a_raising_todo_without_aborting(self):
        # A per-todo inference error is swallowed; nothing is stored, nothing raises.
        store = TaskLineStore()
        assert generate_task_lines(_todos(3), _RaisingLLM(), store) == 0
        assert len(store) == 0

    def test_skips_empty_reply(self):
        store = TaskLineStore()
        assert generate_task_lines(_todos(3), _EmptyLLM(), store) == 0
        assert len(store) == 0

    def test_skips_todo_with_no_title(self):
        store = TaskLineStore()
        todos = [Todo(id="a", title=""), Todo(id="b", title="Real task")]
        n = generate_task_lines(todos, StubLLM(), store)
        assert n == 1
        assert store.has("b") and not store.has("a")

    def test_sanitizes_dirty_reply(self):
        # A model that emits emoji + dashes must be cleaned before the line is stored/spoken.
        store = TaskLineStore()
        generate_task_lines([Todo(id="a", title="Ship it")], _DirtyLLM(), store)
        line = store.get("a")
        assert line
        assert "—" not in line and "–" not in line
        assert "\U0001f389" not in line
        assert not any(ord(ch) > 0x2190 for ch in line)
