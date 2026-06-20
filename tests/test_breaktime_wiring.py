"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Tests for the break-time WIRING - the maintenance job factory (core.maintenance)
         and its hook-up into the live shell (ui.shell) via a BreakScheduler + QTimer.
Role:    Guards the degrade contract (on a base install every job no-ops and HEAVY is gated
         off, so the app behaves exactly as today) and the shell wiring (the scheduler is
         built, ticking does not crash, and the break/idle state is derived from the activity
         tracker). The framework's own eligibility gate is unit-tested in test_breaktime.py;
         here we only confirm the wiring relies on it correctly and the reindex job is safe.

Test classes:
- TestMaintenanceFactory - the factory builds the reindex job; it no-ops without an index and
  calls SemanticIndex.index() with the active notes when one is available; eligibility gate
- TestShellBreakWiring - headless shell builds the scheduler, ticks without crashing on a base
  install, and derives the break state correctly: a running work span (Working/Focus) is a hard
  not-on-break override, and with no span idle is measured from the last-interaction clock so a
  freshly-used app stays gated off and only genuine inactivity makes a job eligible
============================================================
"""

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from serenity.core.breaktime import (  # noqa: E402
    HEAVY_IDLE_SECONDS,
    LIGHT_IDLE_SECONDS,
    BreakJob,
    BreakScheduler,
    BreakState,
    Tier,
    detect_on_ac,
)
from serenity.core.maintenance import build_maintenance_jobs  # noqa: E402

T0 = datetime(2026, 6, 20, 12, 0, 0)


def _state_all_ok():
    """A state where HEAVY is allowed: on a break, on AC, well past the heavy-idle gate."""
    return BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=True)


class _FakeIndex:
    """A stand-in SemanticIndex that records the notes index() was called with."""

    def __init__(self, available=True):
        self.available = available
        self.indexed = None

    def index(self, notes):
        self.indexed = list(notes)


class _FakeNoteStore:
    def __init__(self, notes):
        self._notes = list(notes)

    def all_active(self):
        return list(self._notes)


class TestMaintenanceFactory:
    def test_builds_the_reindex_job(self):
        # No backends at all -> still builds exactly the one real HEAVY job.
        jobs = build_maintenance_jobs(semantic=None, note_store=None)
        assert len(jobs) == 1
        job = jobs[0]
        assert isinstance(job, BreakJob)
        assert job.id == "semantic-reindex"
        assert job.tier == Tier.HEAVY

    def test_reindex_noops_without_index(self):
        # The core degrade-on-base-install guarantee: an unavailable index returns a clean
        # status, loads no model, and never raises into the scheduler.
        s = BreakScheduler()
        for job in build_maintenance_jobs(semantic=None, note_store=None):
            s.register(job)
        results = s.tick(T0, _state_all_ok())
        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].value == "skipped - no index"

    def test_reindex_noops_when_index_unavailable(self):
        # available=False (e.g. no [semantic] extra) is also a clean skip, not a crash.
        s = BreakScheduler()
        for job in build_maintenance_jobs(semantic=_FakeIndex(available=False),
                                          note_store=_FakeNoteStore([])):
            s.register(job)
        results = s.tick(T0, _state_all_ok())
        assert results[0].ok is True
        assert results[0].value == "skipped - no index"

    def test_reindex_calls_index_when_available(self):
        from serenity.core.models import Note
        notes = [Note(id="a"), Note(id="b"), Note(id="c")]
        idx = _FakeIndex(available=True)
        s = BreakScheduler()
        for job in build_maintenance_jobs(semantic=idx, note_store=_FakeNoteStore(notes)):
            s.register(job)
        results = s.tick(T0, _state_all_ok())
        assert idx.indexed is not None
        assert [n.id for n in idx.indexed] == ["a", "b", "c"]
        assert results[0].ok is True
        assert results[0].value == "reindexed 3"

    def test_reindex_skips_off_a_break_and_off_ac(self):
        # The wiring relies on the framework's gate: the HEAVY reindex never runs off a break,
        # nor on battery / unknown power, even with the index available.
        idx = _FakeIndex(available=True)
        s = BreakScheduler()
        for job in build_maintenance_jobs(semantic=idx, note_store=_FakeNoteStore([])):
            s.register(job)
        # off a break -> nothing
        assert s.tick(T0, BreakState(on_break=False, idle_seconds=HEAVY_IDLE_SECONDS + 10,
                                     on_ac=True)) == []
        # on a break + long idle but power unknown (base install) -> HEAVY gated off
        assert s.tick(T0, BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 10,
                                     on_ac=None)) == []
        assert idx.indexed is None  # never ran

    def test_eligibility_gate_light_vs_heavy(self):
        # A stub LIGHT job alongside the HEAVY reindex confirms the tiered gate the wiring
        # depends on (this duplicates nothing of substance in test_breaktime.py - it just
        # pins the factory job to the right tier behaviour).
        ran = []
        light = BreakJob(id="light", name="Light", tier=Tier.LIGHT,
                         run=lambda: ran.append("light"))
        idx = _FakeIndex(available=True)
        s = BreakScheduler()
        s.register(light)
        for job in build_maintenance_jobs(semantic=idx, note_store=_FakeNoteStore([])):
            s.register(job)

        # on a break + light idle + battery -> only LIGHT runs
        ran.clear()
        idx.indexed = None
        s.tick(T0, BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS + 1, on_ac=False))
        assert ran == ["light"]
        assert idx.indexed is None

        # on a break + heavy idle + AC -> both run
        ran.clear()
        idx.indexed = None
        s.tick(T0, BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 1, on_ac=True))
        assert ran == ["light"]
        assert idx.indexed == []


# --------------------------------------------------------------------------- #
# Shell wiring (headless)
# --------------------------------------------------------------------------- #
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestShellBreakWiring:
    def test_scheduler_built_and_tick_does_not_crash(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            assert hasattr(shell, "_break_scheduler")
            ids = [j.id for j in shell._break_scheduler.jobs()]
            assert "semantic-reindex" in ids
            assert hasattr(shell, "_break_timer")
            # Ticking on a base install (semantic unavailable, detect_on_ac() -> None) must
            # not raise - the whole degrade path the env runs.
            shell._break_tick()
        finally:
            shell.tray.hide()

    def test_break_state_derives_from_activity_tracker(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            # A real work span -> hard override: not on a break, zero idle (so HEAVY can never
            # fire mid-work even on an AC machine with the [semantic] extra).
            shell._on_activity("Working")
            s = shell._derive_break_state()
            assert s.on_break is False
            assert s.idle_seconds == 0.0
            # Focus (Pomodoro) is work, NOT a break - same override.
            shell._on_activity("Focus")
            s = shell._derive_break_state()
            assert s.on_break is False
            assert s.idle_seconds == 0.0
            # AC mirrors the standalone probe (None in this env, no [power] extra)
            assert shell._derive_break_state().on_ac == detect_on_ac()
        finally:
            shell.tray.hide()

    def test_no_span_uses_last_interaction_idle_clock(self, qapp, tmp_path, monkeypatch):
        # The load-bearing degrade-while-working guard: with NO tracked span, idle is measured
        # from the last user interaction, NOT assumed to be a long break. A fresh interaction
        # keeps on_break False (the app's default 'just used it' state must not invite HEAVY
        # maintenance); only genuine inactivity past the light threshold flips on_break True.
        from datetime import datetime, timedelta
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            # 'Idle' stops tracking -> no running span; _touch() resets the idle clock, so we
            # look busy and nothing is eligible (the old proxy wrongly treated this as a break).
            shell._on_activity("Idle")
            assert shell.activity_store.running() is None
            s = shell._derive_break_state()
            assert s.on_break is False
            assert s.idle_seconds < shell._break_scheduler.light_idle_seconds

            # Simulate the user having been away well past the heavy-idle threshold.
            shell._last_interaction = datetime.now() - timedelta(
                seconds=shell._break_scheduler.heavy_idle_seconds + 30)
            s = shell._derive_break_state()
            assert s.on_break is True
            assert s.idle_seconds >= shell._break_scheduler.heavy_idle_seconds
        finally:
            shell.tray.hide()
