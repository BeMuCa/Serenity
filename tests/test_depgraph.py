"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for dependency-graph building (ready / in-progress / blocked + edges).
Role:    Guards core.depgraph.build_graph + node_status: a todo is blocked while any
         dependency is still open; ready/in-progress once its deps are done; done/deleted
         todos are dropped; dangling / self / cyclic deps are tolerated (spec sec 5 graph).

Test classes:
- TestNodeStatus - the ready / in-progress / blocked classification per todo
- TestBuildGraph - node set, "blocks" edges, dropping done/deleted, edge hygiene
- TestRoundTrip - depends_on survives Todo.to_dict / from_dict
============================================================
"""

from serenity.core.depgraph import (
    BLOCKED,
    IN_PROGRESS,
    READY,
    build_graph,
    node_status,
)
from serenity.core.models import Todo


def by(*todos):
    return {t.id: t for t in todos}


class TestNodeStatus:
    def test_no_deps_is_ready(self):
        t = Todo(id="t", title="T")
        assert node_status(t, by(t)) == READY

    def test_in_progress_when_timer_runs(self):
        from datetime import datetime
        t = Todo(id="t", title="T", timer_running_since=datetime.now())
        assert node_status(t, by(t)) == IN_PROGRESS

    def test_in_progress_flag(self):
        t = Todo(id="t", title="T", in_progress=True)
        assert node_status(t, by(t)) == IN_PROGRESS

    def test_blocked_by_open_dependency(self):
        dep = Todo(id="dep", title="Dep")
        t = Todo(id="t", title="T", depends_on=["dep"])
        assert node_status(t, by(dep, t)) == BLOCKED

    def test_unblocked_when_dependency_done(self):
        dep = Todo(id="dep", title="Dep", done=True)
        t = Todo(id="t", title="T", depends_on=["dep"])
        assert node_status(t, by(dep, t)) == READY

    def test_missing_dependency_does_not_block(self):
        # dependency id refers to a deleted/unknown todo -> not a blocker
        t = Todo(id="t", title="T", depends_on=["ghost"])
        assert node_status(t, by(t)) == READY

    def test_self_dependency_does_not_block(self):
        t = Todo(id="t", title="T", depends_on=["t"])
        assert node_status(t, by(t)) == READY

    def test_blocked_takes_priority_over_in_progress(self):
        dep = Todo(id="dep", title="Dep")
        t = Todo(id="t", title="T", depends_on=["dep"], in_progress=True)
        assert node_status(t, by(dep, t)) == BLOCKED


class TestBuildGraph:
    def test_drops_done_and_deleted(self):
        a = Todo(id="a", title="A", done=True)
        b = Todo(id="b", title="B", deleted=True)
        c = Todo(id="c", title="C")
        g = build_graph([a, b, c])
        assert {n.id for n in g.nodes} == {"c"}

    def test_chain_classification(self):
        a = Todo(id="a", title="A", done=True)
        b = Todo(id="b", title="B", depends_on=["a"])     # dep done -> ready
        c = Todo(id="c", title="C", depends_on=["b"])     # dep open -> blocked
        g = build_graph([a, b, c])
        status = {n.id: n.status for n in g.nodes}
        assert status == {"b": READY, "c": BLOCKED}

    def test_blocks_edge_emitted(self):
        b = Todo(id="b", title="B")
        c = Todo(id="c", title="C", depends_on=["b"])
        g = build_graph([b, c])
        assert (("b", "c")) in [(e.blocker, e.blocked) for e in g.edges]

    def test_edge_to_done_dependency_skipped(self):
        a = Todo(id="a", title="A", done=True)
        b = Todo(id="b", title="B", depends_on=["a"])
        g = build_graph([a, b])
        # a is dropped from the graph, so no edge points at it
        assert g.edges == []

    def test_edge_to_unknown_dependency_skipped(self):
        b = Todo(id="b", title="B", depends_on=["ghost"])
        g = build_graph([b])
        assert g.edges == []

    def test_self_edge_skipped(self):
        b = Todo(id="b", title="B", depends_on=["b"])
        g = build_graph([b])
        assert g.edges == []

    def test_cycle_is_tolerated(self):
        # a <-> b cycle: both are open, so both are blocked; two edges, no crash
        a = Todo(id="a", title="A", depends_on=["b"])
        b = Todo(id="b", title="B", depends_on=["a"])
        g = build_graph([a, b])
        assert {n.status for n in g.nodes} == {BLOCKED}
        assert len(g.edges) == 2

    def test_helpers_partition_nodes(self):
        from datetime import datetime
        a = Todo(id="a", title="A")                                  # ready
        b = Todo(id="b", title="B", in_progress=True)                # in progress
        c = Todo(id="c", title="C", depends_on=["a"])                # blocked
        g = build_graph([a, b, c])
        assert [n.id for n in g.ready()] == ["a"]
        assert [n.id for n in g.in_progress()] == ["b"]
        assert [n.id for n in g.blocked()] == ["c"]


class TestRoundTrip:
    def test_depends_on_survives_serialization(self):
        t = Todo(id="t", title="T", depends_on=["a", "b"])
        restored = Todo.from_dict(t.to_dict())
        assert restored.depends_on == ["a", "b"]

    def test_missing_depends_on_defaults_empty(self):
        # old documents without the field load as no-deps
        restored = Todo.from_dict({"id": "x", "title": "X"})
        assert restored.depends_on == []
