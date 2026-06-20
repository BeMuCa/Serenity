"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Build the todo dependency graph (ready / in-progress / blocked + edges) - pure.
Role:    The Graph tab (spec sec 5 / sec 12) renders todo dependencies. This module turns
         the flat todo list + each todo's `depends_on` ids into graph nodes (one per
         active todo, classified ready / in-progress / blocked) and "blocks" edges, so the
         QGraphicsView layer just draws what it is handed. Pure of Qt - unit-tested
         headless. A todo is BLOCKED while any todo it depends on is still open; once all
         its dependencies are done (or gone) it is READY (or IN_PROGRESS if its timer
         runs). Done/deleted todos are dropped; dangling/self/cyclic deps are tolerated.

Functions:
- build_graph(todos) -> DepGraph - nodes + edges from the active todos
- node_status(todo, by_id) -> str - READY | IN_PROGRESS | BLOCKED for one todo

Classes:
- DepNode - one graph node: todo id, title, status
- DepEdge - a "blocks" edge: blocker id -> blocked id
- DepGraph - nodes + edges, with ready()/blocked()/in_progress() helpers
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Todo

READY = "ready"
IN_PROGRESS = "in_progress"
BLOCKED = "blocked"


@dataclass(frozen=True)
class DepNode:
    """A graph node for one active todo."""

    id: str
    title: str
    status: str        # READY | IN_PROGRESS | BLOCKED


@dataclass(frozen=True)
class DepEdge:
    """A directed "blocks" edge: the todo `blocker` blocks `blocked`."""

    blocker: str       # the dependency (must finish first)
    blocked: str       # the dependent todo (waits on the blocker)


@dataclass
class DepGraph:
    nodes: list[DepNode] = field(default_factory=list)
    edges: list[DepEdge] = field(default_factory=list)

    def ready(self) -> list[DepNode]:
        return [n for n in self.nodes if n.status == READY]

    def in_progress(self) -> list[DepNode]:
        return [n for n in self.nodes if n.status == IN_PROGRESS]

    def blocked(self) -> list[DepNode]:
        return [n for n in self.nodes if n.status == BLOCKED]


def _is_open(todo: Todo) -> bool:
    """A todo still counts as a blocker while it is neither done nor deleted."""
    return not todo.done and not todo.deleted


def node_status(todo: Todo, by_id: dict[str, Todo]) -> str:
    """Classify one todo: BLOCKED if any dependency is still open, else IN_PROGRESS / READY.

    A dependency id that is missing (deleted/unknown) or points at the todo itself does
    not block - only an existing, still-open OTHER todo blocks."""
    for dep_id in todo.depends_on:
        if dep_id == todo.id:
            continue
        dep = by_id.get(dep_id)
        if dep is not None and _is_open(dep):
            return BLOCKED
    if todo.in_progress or todo.timer_running:
        return IN_PROGRESS
    return READY


def build_graph(todos: list[Todo]) -> DepGraph:
    """Build the dependency graph from the active (non-done, non-deleted) todos.

    Nodes: one per active todo, classified ready / in-progress / blocked. Edges: a
    "blocks" edge from each still-open dependency to the todo that waits on it. Edges to
    deps that are done/deleted/unknown or self-edges are skipped (they no longer block).
    Edges are emitted only between nodes that are both in the graph."""
    active = [t for t in todos if _is_open(t)]
    by_id = {t.id: t for t in todos}
    active_ids = {t.id for t in active}

    nodes = [DepNode(id=t.id, title=t.title, status=node_status(t, by_id)) for t in active]

    edges: list[DepEdge] = []
    for t in active:
        for dep_id in t.depends_on:
            if dep_id == t.id or dep_id not in active_ids:
                continue
            edges.append(DepEdge(blocker=dep_id, blocked=t.id))
    return DepGraph(nodes=nodes, edges=edges)
