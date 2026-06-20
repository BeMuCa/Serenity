"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The break-time deep-work framework - a background-job QUEUE + a SCHEDULER that
         decides WHEN the Stage-2 maintenance jobs (the Job 14/4/3/5 detection tasks) may
         run, so they never steal cycles while the user is working.
Role:    The framework half of the break-time mode (the registry + gating logic only - it
         is NOT wired into the Qt event loop here, and it auto-runs no real embeds). The
         app registers BreakJobs (e.g. "reindex", "find-duplicates", "tidy-tags"); on each
         tick the scheduler runs only the jobs that are ELIGIBLE right now, gated by three
         independent signals carried on a BreakState: (a) a break / idle signal, (b) an
         AC-power guard, and (c) a model-TIER swap policy (light jobs may run on a short
         break; heavy jobs run only on AC + enough idle, so a big model never spins up on
         battery). Everything is INJECTABLE and PURE: the clock, the break/idle provider,
         and the power-state provider are all passed in (stubbed in tests), so the whole
         decision is deterministic and unit-tested headless - no Qt, no real clock, no
         psutil. The ONE optional/heavy seam is detect_on_ac(): a lazy, gracefully-degrading
         psutil probe (mirrors semantic.E5Embedder / tts engines) that returns a tri-state
         and, when the answer is unknown, the scheduler treats it as NOT on AC so heavy work
         is conservatively SKIPPED (the documented safe default).

Functions:
- detect_on_ac() -> Optional[bool] - lazy, optional psutil AC-power probe (None = unknown)

Classes:
- Tier - LIGHT | HEAVY (a job's cost class; HEAVY needs AC + the heavy-idle threshold)
- BreakJob - one registered maintenance job: id + name + tier + a zero-arg callable
- BreakState - the gating snapshot for a tick: on_break, idle_seconds, on_ac
- JobResult - what one job run produced: job id/name/tier + ok + value / error
- BreakScheduler - the registry + queue; register (id-dedup) / tick(now, state) gates and
  runs the eligible jobs in registration order, returns the JobResults that ran
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

# How much continuous idle each tier needs before its jobs are allowed to run. A LIGHT job
# (cheap, no big model) may run after a short pause; a HEAVY job (loads a big model / scans
# the whole vault) waits for a longer, clearly-on-a-break idle so it never competes with the
# user mid-keystroke. These are the framework defaults; a scheduler can override them.
LIGHT_IDLE_SECONDS = 60          # 1 min of idle -> light maintenance may run
HEAVY_IDLE_SECONDS = 300         # 5 min of idle -> heavy (big-model) work may run


class Tier(str, Enum):
    """A job's cost class, which decides how hard the gate is.

    LIGHT = cheap, model-free work (e.g. the incremental hash check, a token-Jaccard pass);
    allowed on a short break. HEAVY = work that spins up a big model or scans the whole
    vault (e.g. a full e5 re-embed); allowed ONLY on AC power AND after the longer
    heavy-idle threshold - the "tier swap" that keeps a big model off battery."""

    LIGHT = "light"
    HEAVY = "heavy"


@dataclass(frozen=True)
class BreakState:
    """The gating snapshot the scheduler decides from on a single tick.

    Pure data, supplied by the caller (stubbed in tests). `on_break` is the break/idle
    signal (the user is on a break or the app is idle); `idle_seconds` is how long the user
    has been continuously idle; `on_ac` is the AC-power guard as a TRI-STATE - True (on
    mains), False (on battery), or None (unknown / probe unavailable). None is treated by
    the scheduler exactly like False for the AC guard, so heavy work is conservatively
    skipped when power cannot be determined (the documented safe default)."""

    on_break: bool = False
    idle_seconds: float = 0.0
    on_ac: Optional[bool] = None

    @property
    def ac_ok(self) -> bool:
        """True only when we KNOW we are on mains power. Unknown (None) -> False (safe default)."""
        return self.on_ac is True


@dataclass
class BreakJob:
    """One registered maintenance job: a stable id, a human name, a tier, and a callable.

    `id` is the dedup key (re-registering the same id replaces the prior job, never queues a
    duplicate). `tier` decides the gate (see Tier). `run` is a zero-argument callable that
    does the actual work and returns whatever the caller wants surfaced; it is invoked ONLY
    when the job is eligible. The framework never calls it speculatively and catches its
    exceptions (see BreakScheduler.tick) so one failing job cannot break the others."""

    id: str
    name: str
    tier: Tier
    run: Callable[[], object]


@dataclass(frozen=True)
class JobResult:
    """The outcome of one job that the scheduler actually ran this tick.

    `ok` is False when the job's callable raised; `value` holds its return value on success
    and `error` the stringified exception on failure - so a caller can log / surface both
    without the scheduler ever propagating a job's crash."""

    job_id: str
    name: str
    tier: Tier
    ok: bool
    value: object = None
    error: Optional[str] = None


def detect_on_ac() -> Optional[bool]:
    """Best-effort AC-power probe as a tri-state: True (mains) / False (battery) / None.

    The ONE optional, heavy-ish seam - and it degrades gracefully, mirroring
    semantic.E5Embedder and the tts engines: psutil is imported LAZILY inside the function
    and any failure (psutil absent, no battery sensor, a platform that does not report
    power) returns None = "unknown". The scheduler maps None to "not on AC" so heavy work is
    conservatively skipped when power cannot be determined - the documented SAFE default
    (better to defer a big-model job than to drain a laptop battery). A desktop with no
    battery legitimately reports power_plugged=True (always on mains), so it is NOT penalised."""
    try:
        import psutil  # lazy + optional - never in the base install
    except Exception:
        return None
    try:
        battery = psutil.sensors_battery()
    except Exception:
        return None
    if battery is None:
        # No battery sensor at all - typically a desktop, i.e. on mains. But we cannot be
        # certain it is a desktop (some platforms just do not report), so stay conservative
        # and return unknown; the caller can override with an explicit provider if it knows.
        return None
    plugged = getattr(battery, "power_plugged", None)
    if plugged is None:
        return None
    return bool(plugged)


class BreakScheduler:
    """A registry + queue of BreakJobs with a pure, deterministic eligibility gate.

    register(job) adds a job, de-duplicating by id (re-registering an id REPLACES the
    earlier job in place, preserving its queue position - so the same logical job is never
    queued twice). tick(now, state) walks the queue in REGISTRATION ORDER and runs each job
    that is eligible under `state`, returning the JobResults for the ones that ran (skipped
    jobs are simply absent). Eligibility:
      - nothing runs unless state.on_break is True (the break/idle signal gate);
      - a LIGHT job additionally needs idle_seconds >= light_idle_seconds;
      - a HEAVY job additionally needs state.ac_ok (the AC-power guard - unknown counts as
        off) AND idle_seconds >= heavy_idle_seconds (the TIER SWAP: heavy work waits for a
        longer, clearly-on-a-break idle on mains power).
    The scheduler is pure (no Qt, no clock, no psutil): `now` and `state` are injected, and a
    job's own exception is caught and recorded as a failed JobResult so one bad job cannot
    abort the rest of the queue. `last_tick` records the last `now` it was ticked at (for the
    caller's own cadence logic); the framework does not auto-run on a timer here."""

    def __init__(self, light_idle_seconds: float = LIGHT_IDLE_SECONDS,
                 heavy_idle_seconds: float = HEAVY_IDLE_SECONDS) -> None:
        self.light_idle_seconds = float(light_idle_seconds)
        self.heavy_idle_seconds = float(heavy_idle_seconds)
        # Insertion-ordered queue; the id index gives O(1) dedup + in-place replace.
        self._jobs: list[BreakJob] = []
        self._index: dict[str, int] = {}
        self.last_tick: Optional[datetime] = None

    def register(self, job: BreakJob) -> None:
        """Add `job`, de-duplicating by id (re-registering an id replaces it in place).

        Replacing in place keeps the job's queue position stable, so the registration order
        the caller relies on for tick() is preserved across a re-register."""
        existing = self._index.get(job.id)
        if existing is not None:
            self._jobs[existing] = job
            return
        self._index[job.id] = len(self._jobs)
        self._jobs.append(job)

    def unregister(self, job_id: str) -> bool:
        """Remove the job with `job_id`. Returns True if one was removed, else False."""
        idx = self._index.pop(job_id, None)
        if idx is None:
            return False
        del self._jobs[idx]
        # Reindex the jobs after the removed one (positions shifted down by one).
        self._index = {j.id: i for i, j in enumerate(self._jobs)}
        return True

    def jobs(self) -> list[BreakJob]:
        """The registered jobs in registration order (a copy; the queue is not exposed)."""
        return list(self._jobs)

    def is_eligible(self, job: BreakJob, state: BreakState) -> bool:
        """True when `job` may run under `state`, applying the break/AC/idle/tier gates.

        No work runs off a break at all; LIGHT needs the light-idle threshold; HEAVY also
        needs AC power (unknown counts as off) and the longer heavy-idle threshold."""
        if not state.on_break:
            return False
        if job.tier == Tier.HEAVY:
            return state.ac_ok and state.idle_seconds >= self.heavy_idle_seconds
        # LIGHT (and any unknown tier defaults to the light gate).
        return state.idle_seconds >= self.light_idle_seconds

    def eligible_jobs(self, state: BreakState) -> list[BreakJob]:
        """The jobs that WOULD run under `state`, in registration order (does not run them)."""
        return [j for j in self._jobs if self.is_eligible(j, state)]

    def tick(self, now: datetime, state: BreakState) -> list[JobResult]:
        """Run every eligible job once, in registration order; return the results that ran.

        Skipped (ineligible) jobs produce no result. A job's own exception is caught and
        recorded as a failed JobResult (ok=False, error=...), so one bad job never aborts the
        rest of the queue. `now` is recorded as last_tick for the caller's cadence logic; the
        scheduler itself does not schedule the next tick (no Qt timer wiring here)."""
        self.last_tick = now
        results: list[JobResult] = []
        for job in self._jobs:
            if not self.is_eligible(job, state):
                continue
            try:
                value = job.run()
                results.append(JobResult(job_id=job.id, name=job.name, tier=job.tier,
                                         ok=True, value=value))
            except Exception as exc:  # a job must never crash the scheduler / its siblings
                results.append(JobResult(job_id=job.id, name=job.name, tier=job.tier,
                                         ok=False, error=str(exc)))
        return results
