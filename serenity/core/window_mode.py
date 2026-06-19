"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Pick which todos show in the compact "mini" window mode - pure logic.
Role:    Serenity can shrink to a small always-on-top mini-dock that shows only a handful
         of todos. This module chooses that handful: the most actionable few from the
         ranked active list, dropping ones whose dependencies are still open (you cannot
         act on a blocked todo). No Qt - the mini view just renders the returned list. The
         full ranking rule lives in core.ranking; the blocked check in core.depgraph.

Functions:
- mini_todos(todos, now=None, limit=3) -> list[Todo] - the mini-window selection
============================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .depgraph import node_status, BLOCKED
from .models import Todo
from .ranking import rank_todos

DEFAULT_LIMIT = 3      # the mini-dock shows at most this many todos


def mini_todos(todos: list[Todo], now: Optional[datetime] = None,
               limit: int = DEFAULT_LIMIT) -> list[Todo]:
    """The todos to show in the compact mini window, most-actionable first.

    Starts from the full display ranking (running timers / nearing deadlines float up),
    drops blocked todos (a dependency is still open, so they are not actionable), and
    keeps the top `limit`. A limit <= 0 returns nothing."""
    if limit <= 0:
        return []
    now = now or datetime.now()
    by_id = {t.id: t for t in todos}
    ranked = rank_todos(todos, now=now)
    actionable = [t for t in ranked if node_status(t, by_id) != BLOCKED]
    return actionable[:limit]
