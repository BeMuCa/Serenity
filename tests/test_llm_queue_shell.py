"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Verify _quit tears the worker down bounded-ly and stashes a still-running
         worker so GC never destroys a live QThread (fold 11.3).
Role:    Offscreen test for shell<->llm-queue lifecycle wiring (Infra A).

Test classes:
- TestQuitTeardown — stop+bounded-wait; stash on timeout
============================================================
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

import serenity.ui.shell as shell_mod


class _FakeWorker:
    def __init__(self, waits_ok):
        self._waits_ok = waits_ok
        self.stopped = False
    def stop(self): self.stopped = True
    def wait(self, ms): return self._waits_ok


def test_quit_stashes_worker_that_does_not_finish(monkeypatch):
    shell_mod._abandoned_workers.clear()
    w = _FakeWorker(waits_ok=False)
    # exercise the teardown snippet directly (avoids constructing a full Shell)
    stashed = shell_mod._teardown_worker(w)
    assert w.stopped is True
    assert stashed is True
    assert w in shell_mod._abandoned_workers


def test_quit_does_not_stash_clean_worker():
    shell_mod._abandoned_workers.clear()
    w = _FakeWorker(waits_ok=True)
    stashed = shell_mod._teardown_worker(w)
    assert w.stopped is True
    assert stashed is False
    assert w not in shell_mod._abandoned_workers
