"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: A tiny, optional performance-history sampler for the Settings 'AI & Voice' panel -
         a rolling last-minute window of (timestamp, cpu%, rss-MB) samples plus the most
         recent break-time job results, so the user can glance at "is anything running and
         how heavy is it".
Role:    The data half of FEATURE 4. PerfSampler keeps a BOUNDED, time-windowed deque of
         resource samples and a bounded ring of the last few maintenance JobResults. It is
         INJECTABLE and PURE of Qt: the clock is passed in (a zero-arg callable returning a
         float seconds value, default time.monotonic) so the rolling-window behaviour is
         deterministic in tests. psutil is the ONE optional seam - imported lazily inside
         sample() and degrading to None (cpu/rss unknown) exactly like core.breaktime.
         detect_on_ac, so it records a timestamp-only sample without psutil and never raises.

Classes:
- PerfSample - one snapshot: ts (clock seconds) + cpu_percent + rss_mb (None when unknown)
- PerfSampler - bounded 60s rolling window of samples + the last K job results; sample() /
  record_job_result() / recent_samples() / latest() / job_history()
============================================================
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

# Rolling-window defaults: keep ~the last minute of samples (a few-minute break tick means a
# handful of points, so the deque also has a generous hard cap as a belt-and-braces bound).
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_MAX_SAMPLES = 240          # hard cap so a fast-sampling caller cannot grow it unbounded
DEFAULT_JOB_HISTORY = 8            # the last few break-time job results to surface


@dataclass(frozen=True)
class PerfSample:
    """One resource snapshot. cpu_percent / rss_mb are None when psutil is unavailable.

    `ts` is the injected clock's seconds value at capture (monotonic by default), so the
    sampler's rolling-window pruning is comparing like with like. A psutil-less sample still
    carries a real `ts` (the timeline is always recorded), it just has no cpu / rss numbers."""

    ts: float
    cpu_percent: Optional[float] = None
    rss_mb: Optional[float] = None


class PerfSampler:
    """A bounded, time-windowed history of resource samples + recent break-time job results.

    Holds the last `window_seconds` of PerfSamples in a deque (also hard-capped at
    `max_samples`) and the last `job_history` JobResults in a ring. Both `sample()` and
    `record_job_result()` prune the window to "now - window_seconds" using the injected
    clock, so the window rolls as time passes regardless of which method is called. psutil is
    lazy + optional inside sample(): when it is absent (the base install) a timestamp-only
    sample is still recorded - cpu_percent / rss_mb come back None - and nothing raises. Pure
    of Qt; the shell drives it from its break tick and the Settings panel reads it back."""

    def __init__(self, window_seconds: float = DEFAULT_WINDOW_SECONDS,
                 max_samples: int = DEFAULT_MAX_SAMPLES,
                 job_history: int = DEFAULT_JOB_HISTORY,
                 clock: Optional[Callable[[], float]] = None) -> None:
        self.window_seconds = float(window_seconds) if window_seconds and window_seconds > 0 \
            else DEFAULT_WINDOW_SECONDS
        cap = int(max_samples) if max_samples and max_samples > 0 else DEFAULT_MAX_SAMPLES
        self._samples: deque[PerfSample] = deque(maxlen=cap)
        hist = int(job_history) if job_history and job_history > 0 else DEFAULT_JOB_HISTORY
        self._jobs: deque = deque(maxlen=hist)
        if clock is not None:
            self._clock = clock
        else:
            import time
            self._clock = time.monotonic

    def _now(self) -> float:
        return float(self._clock())

    def _prune(self, now: float) -> None:
        """Drop samples older than the rolling window (oldest are at the left of the deque)."""
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0].ts < cutoff:
            self._samples.popleft()

    def sample(self) -> PerfSample:
        """Capture + store one resource sample, pruning the window. Never raises.

        psutil is imported lazily and any failure (absent, no process handle, a platform that
        does not report) degrades to a timestamp-only sample (cpu_percent / rss_mb = None) -
        the same graceful-degrade contract as core.breaktime.detect_on_ac. Returns the sample
        that was stored so the caller can use it directly."""
        now = self._now()
        cpu, rss = self._probe()
        s = PerfSample(ts=now, cpu_percent=cpu, rss_mb=rss)
        self._samples.append(s)
        self._prune(now)
        return s

    @staticmethod
    def _probe() -> tuple[Optional[float], Optional[float]]:
        """Best-effort (cpu_percent, rss_mb) for THIS process via psutil, or (None, None).

        Lazy + optional, mirroring core.breaktime.detect_on_ac: psutil is imported inside the
        function and every failure path returns unknowns rather than raising. cpu_percent is
        the process CPU since the last call (non-blocking, interval=None - the first reading is
        0.0 by design, which is fine for a rolling panel); rss_mb is the resident set in MiB."""
        try:
            import psutil  # lazy + optional - never in the base install
        except Exception:
            return (None, None)
        try:
            proc = psutil.Process()
            cpu = float(proc.cpu_percent(interval=None))
            rss = float(proc.memory_info().rss) / (1024.0 * 1024.0)
            return (cpu, rss)
        except Exception:
            return (None, None)

    def record_job_result(self, result) -> None:
        """Remember one break-time JobResult (bounded ring) and roll the sample window.

        Pruning here too means the window stays correct even on a tick that only ran jobs and
        took no resource sample. `result` is whatever core.breaktime.tick() returned (a
        JobResult); we store it opaquely so this module need not import breaktime."""
        if result is None:
            return
        self._jobs.append(result)
        self._prune(self._now())

    def record_job_results(self, results) -> None:
        """Convenience: record each JobResult from a scheduler tick (a list), in order."""
        for r in results or []:
            self.record_job_result(r)

    def recent_samples(self) -> list[PerfSample]:
        """The samples inside the current rolling window (oldest first), pruning first."""
        self._prune(self._now())
        return list(self._samples)

    def latest(self) -> Optional[PerfSample]:
        """The most recent sample, or None if none has been taken yet."""
        return self._samples[-1] if self._samples else None

    def job_history(self) -> list:
        """The last few break-time JobResults (oldest first)."""
        return list(self._jobs)
