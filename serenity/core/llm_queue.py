"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Pure, thread-safe FIFO queue of LLM jobs (Qt-free) for the off-thread
         worker. Serializes inference; supports pause/resume/prioritize/global-pause.
Role:    Core of the LLM job queue (Infra A). One threading.Condition guards the
         ordered job list; the ui/ worker drains it, ui/ inspector reads snapshot().

Models / Functions:
- JobState — PENDING|PAUSED|RUNNING|DONE|FAILED
- LlmJob — one unit of off-thread work (label + run/on_done/on_error callbacks)
- JobView — immutable (id,label,state) row for the inspector snapshot
- LlmQueue — submit/pause/resume/prioritize/pause_all/resume_all/next_runnable/
             mark_done/mark_failed/is_busy/snapshot/wake
============================================================
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMEngine


class JobState(str, Enum):
    PENDING = "pending"
    PAUSED = "paused"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _noop_done(_result: str) -> None:
    pass


def _noop_error(_exc: Exception) -> None:
    pass


@dataclass
class LlmJob:
    label: str
    run: "Callable[[LLMEngine], str]"
    on_done: Callable[[str], None] = _noop_done
    on_error: Callable[[Exception], None] = _noop_error
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.PENDING


@dataclass(frozen=True)
class JobView:
    id: str
    label: str
    state: JobState


class LlmQueue:
    """Ordered job list behind a single Condition. All public methods are atomic."""

    def __init__(self) -> None:
        self._jobs: list[LlmJob] = []
        self._paused_all = False
        self._cond = threading.Condition()   # its lock IS the queue lock

    def submit(self, job: LlmJob) -> bool:
        """Enqueue unless a same-id job exists or an identical-label job is PENDING/RUNNING."""
        with self._cond:
            for j in self._jobs:
                if j.id == job.id:
                    return False
                if j.label == job.label and j.state in (JobState.PENDING, JobState.RUNNING):
                    return False
            self._jobs.append(job)
            self._cond.notify()
            return True

    def pause(self, job_id: str) -> bool:
        with self._cond:
            j = self._find(job_id)
            if j is None or j.state != JobState.PENDING:
                return False
            j.state = JobState.PAUSED
            return True

    def resume(self, job_id: str) -> bool:
        with self._cond:
            j = self._find(job_id)
            if j is None or j.state != JobState.PAUSED:
                return False
            j.state = JobState.PENDING
            self._cond.notify()
            return True

    def prioritize(self, job_id: str) -> bool:
        with self._cond:
            j = self._find(job_id)
            if j is None or j.state != JobState.PENDING:
                return False
            self._jobs.remove(j)
            self._jobs.insert(0, j)          # first PENDING the picker meets
            self._cond.notify()
            return True

    def pause_all(self) -> None:
        with self._cond:
            self._paused_all = True

    def resume_all(self) -> None:
        with self._cond:
            self._paused_all = False
            self._cond.notify()

    def next_runnable(self, wait_timeout: Optional[float] = None) -> Optional[LlmJob]:
        """Pick+RUNNING the first PENDING job; if none, wait (under the same lock -> no
        lost wakeup, fold 11.5) up to wait_timeout, then try once more."""
        with self._cond:
            job = self._pick()
            if job is not None:
                return job
            if wait_timeout is not None or not self._paused_all:
                self._cond.wait(wait_timeout)
            return self._pick()

    def mark_done(self, job: LlmJob) -> None:
        with self._cond:
            job.state = JobState.DONE
            if job in self._jobs:
                self._jobs.remove(job)

    def mark_failed(self, job: LlmJob) -> None:
        with self._cond:
            job.state = JobState.FAILED
            if job in self._jobs:
                self._jobs.remove(job)

    def is_busy(self) -> bool:
        """A RUNNING job -> busy; else a runnable PENDING (not globally paused) -> busy."""
        with self._cond:
            if any(j.state == JobState.RUNNING for j in self._jobs):
                return True
            if self._paused_all:
                return False
            return any(j.state == JobState.PENDING for j in self._jobs)

    def snapshot(self) -> "tuple[Optional[JobView], list[JobView]]":
        with self._cond:
            running = next((JobView(j.id, j.label, j.state)
                            for j in self._jobs if j.state == JobState.RUNNING), None)
            pending = [JobView(j.id, j.label, j.state) for j in self._jobs
                       if j.state in (JobState.PENDING, JobState.PAUSED)]
            return running, pending

    def wake(self) -> None:
        """Wake any waiter (used by the worker on shutdown)."""
        with self._cond:
            self._cond.notify_all()

    def _pick(self) -> Optional[LlmJob]:
        # caller holds self._cond
        if self._paused_all:
            return None
        for j in self._jobs:
            if j.state == JobState.PENDING:
                j.state = JobState.RUNNING
                return j
        return None

    def _find(self, job_id: str) -> Optional[LlmJob]:
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None
