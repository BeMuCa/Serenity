"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the focus-session (Pomodoro) state machine.
Role:    Guards core.pomodoro: deterministic focus<->break cycling driven by an injected
         clock, the long break every 4th focus, pause/resume, and remaining-seconds math
         (spec sec 7 "start a 25-min focus").

Test classes:
- TestStartAndRemaining - start enters focus, remaining counts down, idle is 0
- TestTickTransitions - focus -> break -> focus, long break every 4th, no early advance
- TestPauseResume - freezes/resumes the countdown; paused never advances
- TestStop - returns to idle and resets
============================================================
"""

from datetime import datetime, timedelta

from serenity.core.pomodoro import Phase, Pomodoro

T0 = datetime(2026, 6, 19, 9, 0, 0)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


class TestStartAndRemaining:
    def test_idle_before_start(self):
        p = Pomodoro()
        assert p.phase == Phase.IDLE
        assert p.remaining_seconds(T0) == 0
        assert p.running is False

    def test_start_enters_focus_with_full_25_min(self):
        p = Pomodoro()
        p.start(T0)
        assert p.phase == Phase.FOCUS
        assert p.remaining_seconds(T0) == 25 * 60
        assert p.running is True

    def test_remaining_counts_down(self):
        p = Pomodoro()
        p.start(T0)
        assert p.remaining_seconds(at(10)) == 15 * 60

    def test_remaining_never_negative(self):
        p = Pomodoro()
        p.start(T0)
        assert p.remaining_seconds(at(40)) == 0


class TestTickTransitions:
    def test_no_advance_mid_focus(self):
        p = Pomodoro()
        p.start(T0)
        assert p.tick(at(10)) is None
        assert p.phase == Phase.FOCUS

    def test_focus_elapses_to_break(self):
        p = Pomodoro()
        p.start(T0)
        new = p.tick(at(25))
        assert new == Phase.BREAK
        assert p.phase == Phase.BREAK
        assert p.completed_focus == 1
        assert p.remaining_seconds(at(25)) == 5 * 60

    def test_break_returns_to_focus(self):
        p = Pomodoro()
        p.start(T0)
        p.tick(at(25))            # -> break (5 min)
        new = p.tick(at(30))      # break elapsed -> focus
        assert new == Phase.FOCUS
        assert p.phase == Phase.FOCUS

    def test_long_break_every_fourth_focus(self):
        p = Pomodoro()
        p.start(T0)
        now = T0
        phases = []
        # drive four full focus phases; collect the break that follows each
        for _ in range(4):
            now = now + timedelta(minutes=p.remaining_seconds(now) / 60)
            after_focus = p.tick(now)        # focus -> break/long_break
            phases.append(after_focus)
            now = now + timedelta(minutes=p.remaining_seconds(now) / 60)
            p.tick(now)                       # break -> focus
        # 1st, 2nd, 3rd focus -> short break; 4th focus -> long break
        assert phases == [Phase.BREAK, Phase.BREAK, Phase.BREAK, Phase.LONG_BREAK]

    def test_idle_tick_is_noop(self):
        p = Pomodoro()
        assert p.tick(T0) is None
        assert p.phase == Phase.IDLE


class TestPauseResume:
    def test_pause_freezes_remaining(self):
        p = Pomodoro()
        p.start(T0)
        p.pause(at(10))                       # 15 min left
        assert p.paused is True
        # time keeps passing, but a paused timer holds its remaining
        assert p.remaining_seconds(at(20)) == 15 * 60

    def test_paused_never_advances(self):
        p = Pomodoro()
        p.start(T0)
        p.pause(at(10))
        assert p.tick(at(60)) is None
        assert p.phase == Phase.FOCUS

    def test_resume_continues_from_remaining(self):
        p = Pomodoro()
        p.start(T0)
        p.pause(at(10))                       # 15 min left
        p.resume(at(30))                      # resume at a later wall time
        assert p.paused is False
        assert p.remaining_seconds(at(30)) == 15 * 60
        # now it elapses 15 min after resume
        assert p.tick(at(45)) == Phase.BREAK


class TestStop:
    def test_stop_resets_to_idle(self):
        p = Pomodoro()
        p.start(T0)
        p.tick(at(25))                        # a focus completed
        p.stop()
        assert p.phase == Phase.IDLE
        assert p.completed_focus == 0
        assert p.remaining_seconds(at(25)) == 0
        assert p.running is False
