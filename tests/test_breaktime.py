"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the break-time deep-work framework (queue + scheduler + gating).
Role:    Guards core.breaktime: jobs run ONLY when break + AC + idle hold and are skipped
         otherwise; the model TIER swap gates heavy (big-model) jobs behind AC + the longer
         heavy-idle threshold; the queue runs in registration order; re-registering an id
         de-dups in place; a job's exception is isolated; and the optional AC-power probe
         degrades to the conservative "not on AC" safe default when psutil is absent. Pure
         and deterministic - an injected clock + stub BreakState, no Qt, no real psutil.

Test classes:
- TestRegistration - id-dedup (in-place replace), order, unregister
- TestEligibilityGates - break gate, light-idle gate, heavy AC + heavy-idle (tier swap)
- TestTickRuns - tick runs only eligible jobs in order; skips otherwise; records value
- TestJobIsolation - a job that raises is recorded ok=False, siblings still run
- TestPowerGuardDegrade - BreakState.ac_ok safe default + detect_on_ac() graceful degrade
- TestDetectOnAcWithStubPsutil - detect_on_ac()'s present-psutil degrade matrix + True/False
  (a fake psutil injected into sys.modules, so no real psutil is needed)
============================================================
"""

import builtins
import sys
import types
from collections import namedtuple
from datetime import datetime, timedelta

import pytest

from serenity.core.breaktime import (
    HEAVY_IDLE_SECONDS,
    LIGHT_IDLE_SECONDS,
    BreakJob,
    BreakScheduler,
    BreakState,
    JobResult,
    Tier,
    detect_on_ac,
)

T0 = datetime(2026, 6, 20, 12, 0, 0)


def make_job(job_id, tier=Tier.LIGHT, sink=None, value=None, boom=False):
    """A BreakJob whose callable appends its id to `sink` (so we see run order) and either
    returns `value` or raises if `boom`."""

    def run():
        if sink is not None:
            sink.append(job_id)
        if boom:
            raise RuntimeError(f"{job_id} failed")
        return value

    return BreakJob(id=job_id, name=job_id.title(), tier=tier, run=run)


# A state where everything heavy is allowed (break + on AC + well past the heavy-idle gate).
def state_all_ok():
    return BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=True)


class TestRegistration:
    def test_jobs_kept_in_registration_order(self):
        s = BreakScheduler()
        s.register(make_job("a"))
        s.register(make_job("b"))
        s.register(make_job("c"))
        assert [j.id for j in s.jobs()] == ["a", "b", "c"]

    def test_reregistering_same_id_replaces_in_place_no_duplicate(self):
        s = BreakScheduler()
        s.register(make_job("a", value=1))
        s.register(make_job("b"))
        # Re-register "a" with a new tier/value; it must REPLACE, keeping position 0.
        s.register(make_job("a", tier=Tier.HEAVY, value=99))
        ids = [j.id for j in s.jobs()]
        assert ids == ["a", "b"]                 # no duplicate "a"
        a = s.jobs()[0]
        assert a.id == "a" and a.tier == Tier.HEAVY    # replaced, position preserved

    def test_unregister_removes_and_reindexes(self):
        s = BreakScheduler()
        s.register(make_job("a"))
        s.register(make_job("b"))
        s.register(make_job("c"))
        assert s.unregister("b") is True
        assert [j.id for j in s.jobs()] == ["a", "c"]
        # Removing "b" must not corrupt dedup of the survivors.
        s.register(make_job("a", value=7))
        assert [j.id for j in s.jobs()] == ["a", "c"]
        assert s.unregister("missing") is False


class TestEligibilityGates:
    def test_nothing_eligible_off_a_break(self):
        s = BreakScheduler()
        light = make_job("light", Tier.LIGHT)
        heavy = make_job("heavy", Tier.HEAVY)
        s.register(light)
        s.register(heavy)
        # Plenty of idle + AC, but NOT on a break -> nothing eligible.
        off = BreakState(on_break=False, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=True)
        assert s.is_eligible(light, off) is False
        assert s.is_eligible(heavy, off) is False
        assert s.eligible_jobs(off) == []

    def test_light_needs_light_idle_threshold(self):
        s = BreakScheduler()
        light = make_job("light", Tier.LIGHT)
        s.register(light)
        # On a break but not idle long enough for even light work.
        too_short = BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS - 1, on_ac=True)
        assert s.is_eligible(light, too_short) is False
        just_enough = BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS, on_ac=True)
        assert s.is_eligible(light, just_enough) is True

    def test_light_runs_on_battery(self):
        # Light (model-free) work does NOT require AC - only the break + light-idle gate.
        s = BreakScheduler()
        light = make_job("light", Tier.LIGHT)
        s.register(light)
        on_battery = BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS, on_ac=False)
        assert s.is_eligible(light, on_battery) is True

    def test_heavy_needs_ac_power(self):
        s = BreakScheduler()
        heavy = make_job("heavy", Tier.HEAVY)
        s.register(heavy)
        # Long idle + on a break, but on battery -> heavy (big-model) work is gated off.
        on_battery = BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=False)
        assert s.is_eligible(heavy, on_battery) is False
        on_ac = BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=True)
        assert s.is_eligible(heavy, on_ac) is True

    def test_heavy_tier_swap_needs_longer_idle_than_light(self):
        # The tier swap: at an idle that lets LIGHT run, HEAVY is still gated until the
        # longer heavy-idle threshold - even on AC.
        s = BreakScheduler()
        light = make_job("light", Tier.LIGHT)
        heavy = make_job("heavy", Tier.HEAVY)
        s.register(light)
        s.register(heavy)
        mid = BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS, on_ac=True)
        assert s.is_eligible(light, mid) is True
        assert s.is_eligible(heavy, mid) is False        # not idle long enough for heavy yet
        # Cross the heavy threshold -> heavy swaps in.
        deep = BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS, on_ac=True)
        assert s.is_eligible(heavy, deep) is True

    def test_heavy_unknown_power_is_not_eligible(self):
        # Unknown AC (None) is treated as NOT on AC -> heavy skipped (safe default).
        s = BreakScheduler()
        heavy = make_job("heavy", Tier.HEAVY)
        s.register(heavy)
        unknown = BreakState(on_break=True, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=None)
        assert s.is_eligible(heavy, unknown) is False


class TestTickRuns:
    def test_tick_runs_only_eligible_jobs_in_order(self):
        sink = []
        s = BreakScheduler()
        s.register(make_job("a", Tier.LIGHT, sink=sink))
        s.register(make_job("b", Tier.HEAVY, sink=sink))
        s.register(make_job("c", Tier.LIGHT, sink=sink))
        results = s.tick(T0, state_all_ok())
        # All three eligible (break + AC + deep idle); ran in registration order a, b, c.
        assert sink == ["a", "b", "c"]
        assert [r.job_id for r in results] == ["a", "b", "c"]
        assert all(r.ok for r in results)

    def test_tick_skips_ineligible_and_records_value(self):
        sink = []
        s = BreakScheduler()
        s.register(make_job("light", Tier.LIGHT, sink=sink, value="L"))
        s.register(make_job("heavy", Tier.HEAVY, sink=sink, value="H"))
        # Light-idle window only -> light runs, heavy is skipped (tier swap not reached).
        st = BreakState(on_break=True, idle_seconds=LIGHT_IDLE_SECONDS, on_ac=True)
        results = s.tick(T0, st)
        assert sink == ["light"]
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, JobResult)
        assert r.job_id == "light" and r.ok is True and r.value == "L"

    def test_tick_off_break_runs_nothing(self):
        sink = []
        s = BreakScheduler()
        s.register(make_job("a", Tier.LIGHT, sink=sink))
        off = BreakState(on_break=False, idle_seconds=HEAVY_IDLE_SECONDS + 10, on_ac=True)
        assert s.tick(T0, off) == []
        assert sink == []

    def test_tick_records_last_tick(self):
        s = BreakScheduler()
        assert s.last_tick is None
        s.tick(T0, BreakState())
        assert s.last_tick == T0
        later = T0 + timedelta(minutes=5)
        s.tick(later, BreakState())
        assert s.last_tick == later

    def test_custom_thresholds_are_honoured(self):
        sink = []
        s = BreakScheduler(light_idle_seconds=10, heavy_idle_seconds=20)
        s.register(make_job("light", Tier.LIGHT, sink=sink))
        s.register(make_job("heavy", Tier.HEAVY, sink=sink))
        st = BreakState(on_break=True, idle_seconds=15, on_ac=True)
        s.tick(T0, st)
        assert sink == ["light"]              # 15 >= 10 (light) but < 20 (heavy)


class TestJobIsolation:
    def test_failing_job_is_recorded_and_siblings_still_run(self):
        sink = []
        s = BreakScheduler()
        s.register(make_job("a", Tier.LIGHT, sink=sink))
        s.register(make_job("boom", Tier.LIGHT, sink=sink, boom=True))
        s.register(make_job("c", Tier.LIGHT, sink=sink))
        results = s.tick(T0, state_all_ok())
        # All three were attempted in order despite the middle one raising.
        assert sink == ["a", "boom", "c"]
        by_id = {r.job_id: r for r in results}
        assert by_id["a"].ok is True
        assert by_id["c"].ok is True
        assert by_id["boom"].ok is False
        assert "boom failed" in (by_id["boom"].error or "")
        assert by_id["boom"].value is None


class TestPowerGuardDegrade:
    def test_break_state_ac_ok_safe_default(self):
        assert BreakState(on_ac=True).ac_ok is True
        assert BreakState(on_ac=False).ac_ok is False
        # Unknown (the default) is the conservative "not on AC".
        assert BreakState().ac_ok is False
        assert BreakState(on_ac=None).ac_ok is False

    def test_detect_on_ac_degrades_to_none_without_psutil(self, monkeypatch):
        # Simulate psutil being absent: detect_on_ac must NOT raise and must return None
        # (unknown), which the scheduler treats as not-on-AC (the documented safe default).
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "psutil" or name.startswith("psutil."):
                raise ImportError("no psutil")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert detect_on_ac() is None

    def test_detect_on_ac_returns_a_tri_state(self):
        # Whatever the host reports, the contract is True / False / None - never a raise.
        result = detect_on_ac()
        assert result in (True, False, None)


# A psutil-like battery record: only `power_plugged` is read by detect_on_ac().
FakeBattery = namedtuple("FakeBattery", ["power_plugged"])


def _install_fake_psutil(monkeypatch, sensors_battery):
    """Inject a stub `psutil` module (with the given sensors_battery callable) into
    sys.modules so detect_on_ac()'s lazy `import psutil` resolves to it. monkeypatch.setitem
    restores sys.modules afterwards, so the real (absent) state is left untouched."""
    stub = types.ModuleType("psutil")
    stub.sensors_battery = sensors_battery
    monkeypatch.setitem(sys.modules, "psutil", stub)
    return stub


class TestDetectOnAcWithStubPsutil:
    """Cover detect_on_ac()'s branches that only run when psutil IS importable - exercised
    with a fake psutil so no real dependency is installed (the absent case is already covered
    by TestPowerGuardDegrade.test_detect_on_ac_degrades_to_none_without_psutil)."""

    def test_sensors_battery_raising_returns_none(self, monkeypatch):
        def boom():
            raise RuntimeError("sensor blew up")

        _install_fake_psutil(monkeypatch, boom)
        assert detect_on_ac() is None

    def test_sensors_battery_none_returns_none(self, monkeypatch):
        # No battery sensor (sensors_battery() -> None) - stay conservative, return unknown.
        _install_fake_psutil(monkeypatch, lambda: None)
        assert detect_on_ac() is None

    def test_power_plugged_none_returns_none(self, monkeypatch):
        # A battery record whose power_plugged is None (platform can't tell) -> unknown.
        _install_fake_psutil(monkeypatch, lambda: FakeBattery(power_plugged=None))
        assert detect_on_ac() is None

    def test_power_plugged_true_returns_true(self, monkeypatch):
        _install_fake_psutil(monkeypatch, lambda: FakeBattery(power_plugged=True))
        assert detect_on_ac() is True

    def test_power_plugged_false_returns_false(self, monkeypatch):
        _install_fake_psutil(monkeypatch, lambda: FakeBattery(power_plugged=False))
        assert detect_on_ac() is False
