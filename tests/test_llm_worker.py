"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Verify LlmWorker runs jobs off the UI thread, serializes them, delivers
         on_done/on_error on the UI thread, isolates a raising callback, and stops
         cleanly (in-flight abandoned).
Role:    Offscreen tests for the LLM queue's QThread worker (Infra A).

Test classes:
- TestWorker — off-thread run, serialization, delivery thread, error path, stop
============================================================
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time

import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from serenity.core.llm import StubLLM
from serenity.core.llm_queue import LlmQueue, LlmJob, JobState
from serenity.ui.llm_worker import LlmWorker


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(qapp, predicate, timeout=3.0):
    """Spin the Qt event loop until predicate() or timeout (no pytest-qt in this repo)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestWorker:
    def test_runs_off_ui_thread_and_delivers_on_ui_thread(self, qapp):
        q = LlmQueue()
        rec = {}
        main_tid = threading.get_ident()
        def run(llm):
            rec["run_tid"] = threading.get_ident()
            return llm.generate("x")
        job = LlmJob(label="a", run=run,
                     on_done=lambda r: rec.update(done_tid=threading.get_ident(), result=r))
        w = LlmWorker(q, StubLLM()); w.start()
        try:
            q.submit(job)
            assert _pump(qapp, lambda: "result" in rec)
            assert rec["run_tid"] != main_tid          # ran off the UI thread
            assert rec["done_tid"] == main_tid         # delivered on the UI thread
        finally:
            w.stop(); w.wait(2000)

    def test_serializes_two_jobs(self, qapp):
        q = LlmQueue()
        state = {"active": 0, "max": 0, "done": 0}
        lock = threading.Lock()
        def run(llm):
            with lock:
                state["active"] += 1; state["max"] = max(state["max"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return "ok"
        done = lambda r: state.__setitem__("done", state["done"] + 1)
        w = LlmWorker(q, StubLLM()); w.start()
        try:
            q.submit(LlmJob(label="a", run=run, on_done=done))
            q.submit(LlmJob(label="b", run=run, on_done=done))
            assert _pump(qapp, lambda: state["done"] == 2)
            assert state["max"] == 1                   # never concurrent
        finally:
            w.stop(); w.wait(2000)

    def test_error_path_marks_failed_and_continues(self, qapp):
        q = LlmQueue()
        rec = {"err": None, "ok": None}
        bad = LlmJob(label="bad", run=lambda llm: (_ for _ in ()).throw(ValueError("boom")),
                     on_error=lambda e: rec.update(err=str(e)))
        good = LlmJob(label="good", run=lambda llm: "fine", on_done=lambda r: rec.update(ok=r))
        w = LlmWorker(q, StubLLM()); w.start()
        try:
            q.submit(bad); q.submit(good)
            assert _pump(qapp, lambda: rec["ok"] == "fine")
            assert rec["err"] == "boom"                # worker survived the raise
            assert bad.state == JobState.FAILED
        finally:
            w.stop(); w.wait(2000)

    def test_raising_on_done_does_not_freeze_busy(self, qapp):  # fold 11.6
        q = LlmQueue()
        seen = []
        job = LlmJob(label="a", run=lambda llm: "r",
                     on_done=lambda r: (_ for _ in ()).throw(RuntimeError("cb")))
        w = LlmWorker(q, StubLLM())
        w.busyChanged.connect(lambda b: seen.append(b))
        w.start()
        try:
            q.submit(job)
            assert _pump(qapp, lambda: seen and seen[-1] is False)  # reverted despite callback raise
            assert q.is_busy() is False
        finally:
            w.stop(); w.wait(2000)

    def test_busy_goes_true_when_a_job_is_picked(self, qapp):
        """The mascot bracket needs the rising edge: busyChanged(True) at pick time, not
        only the falling edge after delivery."""
        q = LlmQueue()
        seen = []
        w = LlmWorker(q, StubLLM())
        w.busyChanged.connect(lambda b: seen.append(b))
        w.start()
        try:
            q.submit(LlmJob(label="a", run=lambda llm: "r", on_done=lambda r: None))
            assert _pump(qapp, lambda: seen and seen[-1] is False)
            assert seen[0] is True                  # rose before it fell
        finally:
            w.stop(); w.wait(2000)

    def test_raising_on_error_still_reverts_busy(self, qapp):   # fold 11.6 (error path)
        q = LlmQueue()
        seen = []
        job = LlmJob(label="a",
                     run=lambda llm: (_ for _ in ()).throw(RuntimeError("boom")),
                     on_error=lambda exc: (_ for _ in ()).throw(RuntimeError("cb")))
        w = LlmWorker(q, StubLLM())
        w.busyChanged.connect(lambda b: seen.append(b))
        w.start()
        try:
            q.submit(job)
            assert _pump(qapp, lambda: seen and seen[-1] is False)
            assert q.is_busy() is False             # isolated: a raising on_error still reverts
        finally:
            w.stop(); w.wait(2000)

    def test_stop_abandons_in_flight(self, qapp):
        q = LlmQueue()
        w = LlmWorker(q, StubLLM())
        w.start()
        q.submit(LlmJob(label="slow", run=lambda llm: time.sleep(0.2) or "done"))
        time.sleep(0.05)          # let it start running
        w.stop()
        assert w.wait(2000) is True   # thread exits after the in-flight run finishes
