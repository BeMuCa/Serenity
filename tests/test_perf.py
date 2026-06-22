"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Tests for FEATURE 4 - the Settings 'AI and voice' status panel (Active/Fallback off
         the cheap `available` flags) and the last-minute performance-history sampler.
Role:    Guards the locked decision "Settings: an AI/Voice status panel + a last-minute
         performance history" without installing heavy deps or downloading models. The status
         probes read only the existing `available` flags, so on the headless base install
         every backend reports Fallback; the perf sampler is driven with an INJECTED clock so
         the 60s rolling window is deterministic and works with NO psutil (timestamp-only
         samples). The shell wiring (a live PerfSampler fed from the break tick + passed to the
         Settings dialog) is exercised headlessly.

Test classes:
- TestPerfSamplerWindow - records (ts,cpu,rss); rolls a 60s window with an injected clock;
  honors the hard sample cap; works without psutil (cpu/rss None, timestamp still recorded)
- TestPerfSamplerJobs - record_job_result(s) keeps the last K results and prunes the window too
- TestStatusPanel - the AI&voice tab reflects the available flags (all Fallback on the base
  install); the perf lines summarize the injected sampler / say so when there is none
- TestShellPerfWiring - the shell builds a PerfSampler, the break tick samples into it, and
  open_settings hands it to the dialog
============================================================
"""

import os
from importlib.util import find_spec

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from serenity.core.perf import (  # noqa: E402
    DEFAULT_JOB_HISTORY,
    DEFAULT_WINDOW_SECONDS,
    PerfSampler,
)


class _Clock:
    """A hand-cranked monotonic clock so the rolling window is deterministic."""

    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


class _Result:
    """A stand-in for core.breaktime.JobResult (the sampler stores results opaquely)."""

    def __init__(self, name, ok=True, value=None, error=None):
        self.name = name
        self.ok = ok
        self.value = value
        self.error = error


class TestPerfSamplerWindow:
    def test_sample_without_psutil_records_timestamp_only(self, monkeypatch):
        # Force the psutil path to be unavailable (the base install): the sample is still
        # recorded with a real ts, just no cpu / rss numbers - the degrade contract.
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (None, None)))
        clk = _Clock()
        ps = PerfSampler(clock=clk)
        s = ps.sample()
        assert s.ts == 1000.0
        assert s.cpu_percent is None
        assert s.rss_mb is None
        assert ps.latest() is s
        assert len(ps.recent_samples()) == 1

    def test_rolls_a_60s_window(self, monkeypatch):
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (None, None)))
        clk = _Clock()
        ps = PerfSampler(clock=clk)  # default 60s window
        assert ps.window_seconds == DEFAULT_WINDOW_SECONDS
        ps.sample()                 # t=1000
        clk.advance(30)
        ps.sample()                 # t=1030
        assert len(ps.recent_samples()) == 2
        # Step past the window: the first sample (1000) is now older than now-60 and is pruned.
        clk.advance(40)            # t=1070, cutoff = 1010
        ps.sample()                 # t=1070
        tss = [round(s.ts) for s in ps.recent_samples()]
        assert tss == [1030, 1070]   # the 1000 sample rolled off
        # Advance far enough that everything rolls off, then recent_samples prunes lazily.
        clk.advance(1000)
        assert ps.recent_samples() == []

    def test_window_rolls_even_when_only_reading(self, monkeypatch):
        # recent_samples()/latest are read paths but recent_samples prunes; advancing the clock
        # and reading drops stale samples without a new sample() call.
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (None, None)))
        clk = _Clock()
        ps = PerfSampler(window_seconds=10.0, clock=clk)
        ps.sample()
        clk.advance(100)
        assert ps.recent_samples() == []

    def test_honors_hard_sample_cap(self, monkeypatch):
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (None, None)))
        clk = _Clock()
        # A huge window but a tiny cap: the deque maxlen bounds memory regardless of the window.
        ps = PerfSampler(window_seconds=1e9, max_samples=3, clock=clk)
        for _ in range(10):
            ps.sample()
            clk.advance(0.001)
        assert len(ps.recent_samples()) == 3

    def test_real_cpu_rss_numbers_surface_when_probe_reports(self, monkeypatch):
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (12.5, 256.0)))
        ps = PerfSampler(clock=_Clock())
        s = ps.sample()
        assert s.cpu_percent == 12.5
        assert s.rss_mb == 256.0


class TestPerfSamplerJobs:
    def test_keeps_last_k_results(self):
        ps = PerfSampler(clock=_Clock())
        for i in range(DEFAULT_JOB_HISTORY + 5):
            ps.record_job_result(_Result(name=f"job{i}", value=f"v{i}"))
        hist = ps.job_history()
        assert len(hist) == DEFAULT_JOB_HISTORY
        # the OLDEST were dropped; the most recent survive in order
        assert hist[-1].name == f"job{DEFAULT_JOB_HISTORY + 4}"

    def test_record_results_list_and_none(self):
        ps = PerfSampler(clock=_Clock())
        ps.record_job_result(None)            # ignored, no crash
        ps.record_job_results(None)            # ignored, no crash
        ps.record_job_results([_Result("a"), _Result("b")])
        assert [r.name for r in ps.job_history()] == ["a", "b"]

    def test_recording_a_job_also_rolls_the_window(self, monkeypatch):
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (None, None)))
        clk = _Clock()
        ps = PerfSampler(window_seconds=10.0, clock=clk)
        ps.sample()
        clk.advance(100)
        ps.record_job_result(_Result("late"))   # prunes using the advanced clock
        assert ps.recent_samples() == []


# --------------------------------------------------------------------------- #
# Settings panel + shell wiring (headless)
# --------------------------------------------------------------------------- #
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.settings import Settings  # noqa: E402
from serenity.ui import platform_win  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestStatusPanel:
    @pytest.mark.skipif(
        any(find_spec(m) for m in ("fastembed", "sqlite_vec", "psutil", "kokoro", "piper")),
        reason="an optional backend is installed: some status rows read Active, not all Fallback",
    )
    def test_status_reflects_available_flags(self, qapp, tmp_path, monkeypatch):
        # On the headless base install (no voice / llm / semantic / power extras) every
        # backend's `available` flag is False, so every status row reads Fallback - the panel
        # is a faithful mirror of the cheap probes, never a hardcoded list.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.settings_window import SettingsWindow

        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = SettingsWindow(s)
        try:
            rows = dlg._probe_status()
            labels = {label for label, _ok, _detail in rows}
            assert {"Voice (English)", "Voice (German)", "Language model",
                    "Meaning search", "Power (AC)"} <= labels
            # base install: nothing is Active
            assert all(ok is False for _label, ok, _detail in rows)
        finally:
            dlg.deleteLater()

    def test_status_marks_active_when_a_backend_is_available(self, qapp, tmp_path, monkeypatch):
        # Swap in a stub make_engine that returns an "available, real" engine for English so
        # the row flips to Active - proving the panel reads the flag rather than a constant.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui import settings_window as sw

        class _FakeEngine:
            def __init__(self, name, available):
                self.name = name
                self.available = available

        from serenity.core import tts as tts_mod

        def fake_make_engine(settings, lang="en"):
            return _FakeEngine("kokoro", True) if lang == "en" \
                else _FakeEngine(tts_mod.NOOP, True)

        monkeypatch.setattr(tts_mod, "make_engine", fake_make_engine)

        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = sw.SettingsWindow(s)
        try:
            rows = {label: (ok, detail) for label, ok, detail in dlg._probe_status()}
            assert rows["Voice (English)"][0] is True   # the real engine -> Active
            assert rows["Voice (German)"][0] is False    # NoopEngine -> Fallback
        finally:
            dlg.deleteLater()

    def test_status_probe_never_raises(self, qapp, tmp_path, monkeypatch):
        # Even if a probe blows up, the panel must degrade to Fallback, never propagate.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.core import tts as tts_mod
        from serenity.ui.settings_window import SettingsWindow

        def boom(*a, **k):
            raise RuntimeError("backend exploded")

        monkeypatch.setattr(tts_mod, "make_engine", boom)
        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = SettingsWindow(s)
        try:
            rows = dlg._probe_status()
            voice = {label: ok for label, ok, _ in rows}
            assert voice["Voice (English)"] is False
        finally:
            dlg.deleteLater()

    def test_perf_lines_without_a_sampler(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.settings_window import SettingsWindow

        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = SettingsWindow(s)  # no perf -> a plain "sampled while running" line
        try:
            lines = dlg._perf_lines()
            assert lines and any("sampled" in ln.lower() for ln in lines)
        finally:
            dlg.deleteLater()

    def test_perf_lines_summarize_the_window(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.settings_window import SettingsWindow

        # A sampler with real cpu/rss numbers + a recent job result.
        monkeypatch.setattr(PerfSampler, "_probe", staticmethod(lambda: (9.0, 100.0)))
        perf = PerfSampler(clock=_Clock())
        perf.sample()
        perf.record_job_result(_Result("semantic-reindex", value="reindexed 3"))

        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = SettingsWindow(s, perf=perf)
        try:
            blob = " ".join(dlg._perf_lines())
            assert "Samples in the last minute: 1" in blob
            assert "CPU:" in blob and "Memory (RSS):" in blob
            assert "semantic-reindex" in blob and "reindexed 3" in blob
        finally:
            dlg.deleteLater()

    def test_perf_lines_no_samples_yet(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.settings_window import SettingsWindow

        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = SettingsWindow(s, perf=PerfSampler(clock=_Clock()))  # never sampled
        try:
            lines = dlg._perf_lines()
            assert any("no samples" in ln.lower() for ln in lines)
        finally:
            dlg.deleteLater()


class TestShellPerfWiring:
    def test_shell_builds_a_sampler_and_tick_samples(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            assert hasattr(shell, "perf")
            before = len(shell.perf.recent_samples())
            shell._break_tick()   # base install: no job runs, but a sample is taken
            after = len(shell.perf.recent_samples())
            assert after == before + 1
        finally:
            shell.tray.hide()

    def test_open_settings_passes_the_sampler(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.ui import shell as shell_mod
        from serenity.ui.shell import Shell

        captured = {}

        class _FakeDialog:
            def __init__(self, settings, parent=None, perf=None):
                captured["perf"] = perf
                self.applied = _Sig()

            def exec(self):
                return 0

        class _Sig:
            def connect(self, *a, **k):
                pass

        shell = Shell()
        try:
            monkeypatch.setattr(shell_mod, "SettingsWindow", _FakeDialog)
            shell.open_settings()
            assert captured["perf"] is shell.perf
        finally:
            shell.tray.hide()
