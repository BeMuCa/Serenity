"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the compact mini-window todo selection.
Role:    Guards core.window_mode.mini_todos: it surfaces the most-actionable few todos
         (full ranking order), drops blocked todos, and honors the count limit.

Test classes:
- TestMiniTodos - limit, ranking order carried through, blocked excluded, edge cases
============================================================
"""

from datetime import datetime, timedelta

from serenity.core.models import Todo
from serenity.core.window_mode import DEFAULT_LIMIT, mini_todos

NOW = datetime(2026, 6, 19, 12, 0, 0)


def mk(title, order, **kw):
    return Todo(id=title, title=title, order=order, **kw)


class TestMiniTodos:
    def test_default_limit_caps_count(self):
        todos = [mk(str(i), i) for i in range(6)]
        out = mini_todos(todos, now=NOW)
        assert len(out) == DEFAULT_LIMIT

    def test_keeps_ranking_order(self):
        far = mk("far", 0, due=NOW + timedelta(days=3))
        soon = mk("soon", 9, due=NOW + timedelta(minutes=10))
        out = mini_todos([far, soon], now=NOW, limit=2)
        # urgent (soon) floats to the top of the mini list
        assert [t.title for t in out] == ["soon", "far"]

    def test_blocked_todos_excluded(self):
        dep = mk("dep", 0)                                   # open blocker
        blocked = mk("blocked", 1, depends_on=["dep"])
        out = mini_todos([dep, blocked], now=NOW, limit=5)
        assert [t.title for t in out] == ["dep"]

    def test_unblocked_when_dep_done_is_included(self):
        dep = mk("dep", 0, done=True)                        # finished blocker
        ready = mk("ready", 1, depends_on=["dep"])
        out = mini_todos([dep, ready], now=NOW, limit=5)
        # the done dep is excluded by ranking; the now-ready todo shows
        assert [t.title for t in out] == ["ready"]

    def test_done_and_deleted_never_shown(self):
        todos = [mk("a", 0), mk("done", 1, done=True), mk("del", 2, deleted=True)]
        out = mini_todos(todos, now=NOW, limit=5)
        assert [t.title for t in out] == ["a"]

    def test_zero_limit_returns_empty(self):
        todos = [mk("a", 0)]
        assert mini_todos(todos, now=NOW, limit=0) == []

    def test_empty_input(self):
        assert mini_todos([], now=NOW) == []
