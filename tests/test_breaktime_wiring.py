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
- TestMaintenanceFactory - the factory builds the reindex + task-voicelines jobs; reindex
  no-ops without an index and calls SemanticIndex.index() with the active notes when one is
  available; eligibility gate
- TestTaskVoiceLinesJob - the HEAVY task-voicelines job: no-ops without an LLM / todo source,
  authors a bounded set of personalized lines into the shared store via a StubLLM, and is
  incremental (a repeat tick over an unchanged backlog writes nothing new)
- TestShellBreakWiring - headless shell builds the scheduler (both HEAVY jobs registered),
  ticks without crashing on a base install, derives the break state correctly (a running work
  span Working/Focus is a hard not-on-break override; with no span idle is measured from the
  last-interaction clock so a freshly-used app stays gated off and only genuine inactivity
  makes a job eligible), and a stored per-task line is read on todo-started
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


class _FakeTodoStore:
    """A stand-in TodoStore exposing only active() - the ranked active todos the job reads."""

    def __init__(self, todos):
        self._todos = list(todos)

    def active(self):
        return list(self._todos)


class _UnavailableLLM:
    """A wired-but-unavailable engine - generate() must never be called (mirrors test_digest)."""

    name = "down"
    available = False

    def generate(self, prompt, system=None, max_tokens=256):  # pragma: no cover
        raise AssertionError("generate() must not be called when available is False")


def _todos(n):
    """n simple active todos (real Todo models) with distinct ids + titles."""
    from serenity.core.models import Todo
    return [Todo(id=f"t{i}", title=f"Task {i}") for i in range(n)]


class TestMaintenanceFactory:
    def test_builds_the_reindex_job(self):
        # No backends at all -> still builds the two real HEAVY jobs (reindex + task-voicelines)
        # in registration order, each pinned to the HEAVY tier.
        jobs = build_maintenance_jobs(semantic=None, note_store=None)
        assert len(jobs) == 2
        assert all(isinstance(j, BreakJob) for j in jobs)
        assert [j.id for j in jobs] == ["semantic-reindex", "task-voicelines"]
        assert all(j.tier == Tier.HEAVY for j in jobs)
        # The reindex job is first (its result is results[0] in the tick tests below).
        assert jobs[0].id == "semantic-reindex"

    def test_reindex_noops_without_index(self):
        # The core degrade-on-base-install guarantee: an unavailable index returns a clean
        # status, loads no model, and never raises into the scheduler.
        s = BreakScheduler()
        for job in build_maintenance_jobs(semantic=None, note_store=None):
            s.register(job)
        results = s.tick(T0, _state_all_ok())
        reindex = next(r for r in results if r.job_id == "semantic-reindex")
        assert reindex.ok is True
        assert reindex.value == "skipped - no index"

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


class TestTaskVoiceLinesJob:
    """FEATURE 5: the HEAVY task-voicelines job authors per-todo lines via the LLM seam.

    Uses a deterministic StubLLM (no llama-cpp / no model) so the contract is asserted
    headless: no-op without an LLM / a todo source, bounded + incremental generation into the
    shared TaskLineStore, and a clean skip on a base install through the scheduler's gate."""

    def _job(self, **kw):
        from serenity.core.maintenance import build_maintenance_jobs
        jobs = build_maintenance_jobs(**kw)
        return next(j for j in jobs if j.id == "task-voicelines")

    def test_noops_without_llm(self):
        from serenity.core.task_lines import TaskLineStore
        store = TaskLineStore()
        job = self._job(todo_store=_FakeTodoStore(_todos(3)), task_lines=store)
        assert job.run() == "skipped - no llm"
        assert len(store) == 0

    def test_noops_when_llm_unavailable(self):
        from serenity.core.task_lines import TaskLineStore
        store = TaskLineStore()
        job = self._job(llm=_UnavailableLLM(), todo_store=_FakeTodoStore(_todos(3)),
                        task_lines=store)
        assert job.run() == "skipped - no llm"
        assert len(store) == 0

    def test_noops_without_todo_source(self):
        from serenity.core.llm import StubLLM
        from serenity.core.task_lines import TaskLineStore
        store = TaskLineStore()
        # LLM available but no todo_store / store wired -> a clean skip, nothing authored.
        job = self._job(llm=StubLLM(), todo_store=None, task_lines=store)
        assert job.run() == "skipped - no todos"
        assert len(store) == 0

    def test_authors_lines_for_active_todos(self):
        from serenity.core.llm import StubLLM
        from serenity.core.task_lines import TaskLineStore
        todos = _todos(3)
        store = TaskLineStore()
        job = self._job(llm=StubLLM(), todo_store=_FakeTodoStore(todos), task_lines=store)
        assert job.run() == "voicelines 3"
        # Every active todo now has a stored, non-empty, sanitized line (the stub echo).
        for t in todos:
            line = store.get(t.id)
            assert line and "stub-llm:" in line

    def test_generation_is_bounded(self):
        # A backlog far larger than the per-pass limit only ever authors DEFAULT_LIMIT lines,
        # so a synchronous break tick stays bounded regardless of how many todos exist.
        from serenity.core.llm import StubLLM
        from serenity.core.task_lines import DEFAULT_LIMIT, TaskLineStore
        store = TaskLineStore()
        job = self._job(llm=StubLLM(), todo_store=_FakeTodoStore(_todos(50)),
                        task_lines=store)
        assert job.run() == f"voicelines {DEFAULT_LIMIT}"
        assert len(store) == DEFAULT_LIMIT

    def test_incremental_repeat_tick_writes_nothing_new(self):
        # The scheduler re-runs every eligible job each tick; a repeat pass over an unchanged
        # backlog must do no new work (already-authored todos are skipped) so it stays cheap.
        from serenity.core.llm import StubLLM
        from serenity.core.task_lines import TaskLineStore
        todos = _todos(3)
        store = TaskLineStore()
        job = self._job(llm=StubLLM(), todo_store=_FakeTodoStore(todos), task_lines=store)
        assert job.run() == "voicelines 3"
        assert job.run() == "voicelines 0"   # nothing new the second pass
        assert len(store) == 3

    def test_runs_under_the_heavy_gate_only(self):
        # The job is HEAVY: it must never fire off a break / on battery, and runs (a clean
        # skip here, no LLM) only on AC after the heavy-idle threshold - same gate as reindex.
        from serenity.core.task_lines import TaskLineStore
        s = BreakScheduler()
        store = TaskLineStore()
        for job in build_maintenance_jobs(todo_store=_FakeTodoStore(_todos(3)),
                                          task_lines=store):
            s.register(job)
        # off a break -> nothing runs at all
        assert s.tick(T0, BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS + 1,
                                     on_ac=True)) == []   # light idle < heavy gate
        # on a break + heavy idle + AC -> the job runs (skips: no LLM in this base install)
        results = s.tick(T0, _state_all_ok())
        vl = next(r for r in results if r.job_id == "task-voicelines")
        assert vl.ok is True and vl.value == "skipped - no llm"


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
            assert "task-voicelines" in ids        # FEATURE 5 job registered
            assert hasattr(shell, "task_lines")     # shared per-task line store built
            assert hasattr(shell, "_break_timer")
            # Ticking on a base install (semantic unavailable, detect_on_ac() -> None) must
            # not raise - the whole degrade path the env runs.
            shell._break_tick()
        finally:
            shell.tray.hide()

    def test_started_todo_prefers_a_stored_personalized_line(self, qapp, tmp_path, monkeypatch):
        # FEATURE 5 read path: when the break job has authored a line for a todo it is what the
        # mascot speaks; with none stored it falls back to the deterministic VoiceLines catalog.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.core.models import Todo
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            spoken = []
            monkeypatch.setattr(shell.mascot, "says", lambda text, *a, **k: spoken.append(text))
            todo = Todo(id="vl1", title="Write the report")

            # No stored line -> the deterministic VoiceLines catalog line (never empty).
            shell._on_todo_started(todo)
            assert spoken and spoken[-1]
            fallback = spoken[-1]

            # A stored personalized line -> the mascot speaks exactly that.
            shell.task_lines.set("vl1", "You have got this - the report is the next win.")
            shell._on_todo_started(todo)
            assert spoken[-1] == "You have got this - the report is the next win."
            assert spoken[-1] != fallback
        finally:
            shell.tray.hide()

    def test_language_switch_clears_stored_task_lines(self, qapp, tmp_path, monkeypatch):
        # FEATURE 5 invalidation: the LLM authored the per-task lines in one language, so a
        # language switch must drop them (the next break repopulates in the new language and
        # _on_todo_started falls back to the bilingual catalog meanwhile).
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            shell.task_lines.set("vl1", "You have got this - the report is the next win.")
            assert len(shell.task_lines) == 1
            other = "de" if shell._lang == "en" else "en"
            shell.settings.language = other
            shell._apply_settings()
            assert len(shell.task_lines) == 0
        finally:
            shell.tray.hide()

    def test_same_language_apply_keeps_task_lines(self, qapp, tmp_path, monkeypatch):
        # Re-applying settings WITHOUT a language change must NOT discard the authored lines
        # (e.g. the user only flipped the accent or the mute toggle).
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            shell.task_lines.set("vl1", "You have got this - the report is the next win.")
            assert len(shell.task_lines) == 1
            shell.settings.language = shell._lang   # unchanged
            shell._apply_settings()
            assert len(shell.task_lines) == 1
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
