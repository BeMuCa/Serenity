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
- TestInspectorWidgets — render() really builds/clears the row widgets + their controls
- TestStatusLineVisibility — hidden at construction inside a SHOWN parent; busy toggles it
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
        assert line.isVisible() is False     # (real hide() coverage: TestStatusLineVisibility)
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


class TestInspectorWidgets:
    """row_labels() reads the QUEUE, so it cannot see whether render() built anything -
    these assert on the real widgets so an empty render() fails."""

    def test_render_builds_a_row_widget_per_job(self, qapp):
        from PySide6.QtWidgets import QLabel, QPushButton
        q = LlmQueue()
        a, b = _job("running one"), _job("pending one")
        q.submit(a); q.submit(b); q.next_runnable()      # a RUNNING, b PENDING
        insp = LlmInspector(q)
        insp.render()
        rows = [insp._rows_box.itemAt(i).widget() for i in range(insp._rows_box.count())]
        assert len(rows) == 2
        texts = [lbl.text() for r in rows for lbl in r.findChildren(QLabel)]
        assert texts == ["running one — running", "pending one — pending"]
        # the RUNNING row carries no controls; the PENDING row carries Pause + Play next
        assert [b.text() for b in rows[0].findChildren(QPushButton)] == []
        assert [b.text() for b in rows[1].findChildren(QPushButton)] == ["Pause", "Play next"]

    def test_render_clears_rows_of_finished_jobs(self, qapp):
        q = LlmQueue()
        a = _job("a"); q.submit(a)
        insp = LlmInspector(q)
        insp.render()
        assert insp._rows_box.count() == 1
        q.mark_done(q.next_runnable())
        insp.render()
        assert insp._rows_box.count() == 0


class TestStatusLineVisibility:
    def test_hidden_at_construction_inside_a_shown_parent(self, qapp):
        """An unparented, never-shown widget reports invisible anyway - park the line in a
        SHOWN parent so the constructor's hide() is what actually keeps it invisible."""
        from PySide6.QtWidgets import QVBoxLayout, QWidget
        holder = QWidget()
        lay = QVBoxLayout(holder)
        line = LlmStatusLine()
        lay.addWidget(line)
        holder.show()
        try:
            qapp.processEvents()
            assert line.isVisible() is False      # idle: truly hidden, not just unmapped
            line.set_busy(True)
            qapp.processEvents()
            assert line.isVisible() is True
            line.set_busy(False)
            qapp.processEvents()
            assert line.isVisible() is False
        finally:
            holder.hide()
