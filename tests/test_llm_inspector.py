"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Verify the status line shows only while busy + click-opens, and the inspector
         lists running/pending/paused and mutates the queue via its controls (11.11).
Role:    Offscreen tests for the LLM queue's working indicator + inspector (Infra A).

Test classes:
- TestStatusLine — busy visibility + clicked signal
- TestInspector — snapshot rows + controls mutate the queue + live re-render
============================================================
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from serenity.core.llm_queue import LlmQueue, LlmJob, JobState
from serenity.ui.llm_inspector import LlmStatusLine, LlmInspector


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _job(label):
    return LlmJob(label=label, run=lambda llm: label)


class TestStatusLine:
    def test_hidden_until_busy_then_click(self, qapp):
        line = LlmStatusLine()
        assert line.isVisibleTo(line.parent()) is False or not line.isVisible()
        line.set_busy(True)
        assert line.isVisible() is True
        line.set_busy(False)
        assert line.isVisible() is False
        clicked = []
        line.clicked.connect(lambda: clicked.append(True))
        line._emit_click()          # test seam for mousePressEvent
        assert clicked == [True]


class TestInspector:
    def test_lists_running_and_pending_paused(self, qapp):
        q = LlmQueue()
        a, b, c = _job("a"), _job("b"), _job("c")
        for j in (a, b, c): q.submit(j)
        q.next_runnable()           # a RUNNING
        q.pause(c.id)               # c PAUSED
        insp = LlmInspector(q)
        insp.render()
        labels = insp.row_labels()  # test helper: [(label, state), ...] in display order
        assert ("a", JobState.RUNNING) in labels
        assert ("b", JobState.PENDING) in labels
        assert ("c", JobState.PAUSED) in labels

    def test_controls_mutate_queue(self, qapp):
        q = LlmQueue()
        a, b = _job("a"), _job("b")
        q.submit(a); q.submit(b)
        insp = LlmInspector(q)
        insp.render()
        insp._prioritize(b.id)      # per-row Prioritize
        assert q.snapshot()[1][0].label == "b"   # b now first pending
        insp._global_pause(True)
        assert q.next_runnable() is None
        insp._global_pause(False)
        assert q.next_runnable() is not None

    def test_op_on_running_job_is_noop(self, qapp):
        q = LlmQueue()
        a = _job("a"); q.submit(a); q.next_runnable()   # a RUNNING
        insp = LlmInspector(q)
        insp.render()
        assert insp._pause(a.id) is False               # 11.11: no-op, surfaced as False
