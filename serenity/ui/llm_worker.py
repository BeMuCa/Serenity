"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Single QThread that drains the LlmQueue off the UI thread, runs each job's
         run(llm), and delivers on_done/on_error on the UI thread via queued signals.
Role:    The only QThread in Serenity (Infra A). Bridges the pure core LlmQueue to Qt;
         emits busyChanged/queueChanged for the mascot bracket + inspector.

Class:
- LlmWorker(QThread) — run() drain loop; _deliver_result/_deliver_error (UI thread,
  callback-isolated, fold 11.6); stop() (flag + wake; in-flight abandoned, fold 11.3)
============================================================
"""
from __future__ import annotations

import logging
import weakref

from PySide6.QtCore import QCoreApplication, QThread, Signal

from ..core.llm_queue import LlmQueue

_log = logging.getLogger(__name__)

# Every live worker, weakly. Lets stop_all_workers() drain them on app shutdown (a path
# bypassing Shell._quit) and lets the test suite tear down workers it never quit.
_live_workers: "weakref.WeakSet[LlmWorker]" = weakref.WeakSet()
_quit_hook_installed = False


def stop_all_workers(timeout_ms: int = 3000) -> None:
    """Stop every live worker and wait (bounded) so no QThread is destroyed mid-run."""
    for w in list(_live_workers):
        w.stop()
        w.wait(timeout_ms)


class LlmWorker(QThread):
    resultReady = Signal(object, str)     # (LlmJob, result_text)
    errorReady = Signal(object, object)   # (LlmJob, Exception)
    busyChanged = Signal(bool)
    queueChanged = Signal()

    def __init__(self, queue: LlmQueue, llm, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._llm = llm
        self._stopping = False
        # queued (cross-thread) auto-connection -> these slots run on the UI thread
        self.resultReady.connect(self._deliver_result)
        self.errorReady.connect(self._deliver_error)
        _live_workers.add(self)
        # Safety net: drain all workers if the app quits by a path that bypasses
        # Shell._quit's bounded teardown, so no QThread is destroyed mid-run (fold 11.3).
        global _quit_hook_installed
        app = QCoreApplication.instance()
        if app is not None and not _quit_hook_installed:
            app.aboutToQuit.connect(stop_all_workers)
            _quit_hook_installed = True

    def run(self) -> None:                # executes on the worker thread
        while not self._stopping:
            job = self._queue.next_runnable(wait_timeout=0.2)
            if self._stopping:
                break
            if job is None:
                continue
            self.queueChanged.emit()      # a PENDING became RUNNING
            self.busyChanged.emit(True)
            try:
                result = job.run(self._llm)
            except Exception as exc:      # noqa: BLE001 - a job must never kill the worker
                self._queue.mark_failed(job)
                self.errorReady.emit(job, exc)
            else:
                self._queue.mark_done(job)
                self.resultReady.emit(job, result)

    def _deliver_result(self, job, result) -> None:   # UI thread
        try:
            job.on_done(result)
        except Exception:                 # noqa: BLE001 - 11.6: never suppress the revert
            _log.exception("llm job on_done failed: %s", getattr(job, "label", "?"))
        finally:
            self.queueChanged.emit()
            self.busyChanged.emit(self._queue.is_busy())

    def _deliver_error(self, job, exc) -> None:        # UI thread
        try:
            job.on_error(exc)
        except Exception:                 # noqa: BLE001 - 11.6
            _log.exception("llm job on_error failed: %s", getattr(job, "label", "?"))
        finally:
            self.queueChanged.emit()
            self.busyChanged.emit(self._queue.is_busy())

    def stop(self) -> None:
        """Signal the loop to exit and wake it if waiting. In-flight inference is
        abandoned (it cannot be interrupted); the caller bounds .wait() (fold 11.3)."""
        self._stopping = True
        self._queue.wake()
