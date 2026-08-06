"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Verify _quit tears the worker down bounded-ly and stashes a still-running
         worker so GC never destroys a live QThread (fold 11.3).
Role:    Offscreen test for shell<->llm-queue lifecycle wiring (Infra A).

Test classes:
- TestQuitTeardown — stop+bounded-wait; stash on timeout
- TestSubmitRendersInspector — a submit re-renders an OPEN inspector (not the worker's job)
- TestQuitCallsTeardown — _quit really calls the bounded teardown
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


class TestSubmitRendersInspector:
    """QA: only the worker emits queueChanged (on pick / after delivery), so a job queued
    BEHIND a running one stays invisible in an already-open inspector - un-pausable."""

    def _fake_self(self, visible):
        from types import SimpleNamespace
        from serenity.core.llm_queue import LlmQueue
        rendered = []
        fs = SimpleNamespace(
            llm_queue=LlmQueue(),
            llm_inspector=SimpleNamespace(isVisible=lambda: visible,
                                          render=lambda: rendered.append(1)),
        )
        return fs, rendered

    def _job(self, label="A"):
        from serenity.core.llm_queue import LlmJob
        return LlmJob(label=label, run=lambda llm: "", on_done=lambda text: None)

    def test_successful_submit_rerenders_an_open_inspector(self):
        fs, rendered = self._fake_self(visible=True)
        assert shell_mod.Shell._submit_llm_job(fs, self._job()) is True
        assert rendered == [1]

    def test_dropped_submit_does_not_rerender(self):
        fs, rendered = self._fake_self(visible=True)
        shell_mod.Shell._submit_llm_job(fs, self._job())
        assert shell_mod.Shell._submit_llm_job(fs, self._job()) is False   # same-label dedup
        assert rendered == [1]

    def test_hidden_inspector_is_not_rendered(self):
        fs, rendered = self._fake_self(visible=False)
        assert shell_mod.Shell._submit_llm_job(fs, self._job()) is True
        assert rendered == []


class TestQuitCallsTeardown:
    def test_quit_tears_the_worker_down(self, monkeypatch):
        """Without this call the QThread outlives the window and Qt destroys a running
        thread (the aboutToQuit hook is a net, not the primary path)."""
        from types import SimpleNamespace
        torn = []
        monkeypatch.setattr(shell_mod, "_teardown_worker", lambda w: torn.append(w) or False)
        monkeypatch.setattr(shell_mod, "QApplication",
                            SimpleNamespace(instance=lambda: SimpleNamespace(quit=lambda: None)))
        worker = object()
        fs = SimpleNamespace(
            todo_store=SimpleNamespace(save=lambda: None),
            activity_store=SimpleNamespace(save=lambda: None),
            note_store=SimpleNamespace(close=lambda: None),
            _break_timer=None, llm_worker=worker, _mini=None, _expanded=None,
        )
        shell_mod.Shell._quit(fs)
        assert torn == [worker]
