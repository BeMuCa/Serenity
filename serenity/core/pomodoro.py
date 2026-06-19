"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The focus-session (Pomodoro) state machine - pure, time-driven.
Role:    Backs "start a 25-min focus" (spec sec 7 voice command) and the focus timer on
         the mascot stage. A focus session ties to the active activity/todo and counts
         down; when it elapses Serenity suggests a break, then the next focus. All time
         math is driven by an injected `now`, so it is fully deterministic and unit-tested
         headless - no Qt, no real clock. The UI just renders phase + remaining seconds
         and calls tick(now) on its 1s timer.

Functions:
- (none free-standing; the machine is the Pomodoro class)

Classes:
- Phase - IDLE | FOCUS | BREAK | LONG_BREAK (the four session phases)
- Pomodoro - start/pause/resume/stop + tick(now); auto-advances focus<->break, long
             break every 4th completed focus
============================================================
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

FOCUS_MINUTES = 25
BREAK_MINUTES = 5
LONG_BREAK_MINUTES = 15
CYCLES_BEFORE_LONG_BREAK = 4


class Phase(str, Enum):
    IDLE = "idle"
    FOCUS = "focus"
    BREAK = "break"
    LONG_BREAK = "long_break"


class Pomodoro:
    """A focus-session timer that auto-cycles focus -> break -> focus.

    Deterministic: every transition is decided from a caller-supplied `now`. A focus
    phase lasts FOCUS_MINUTES; on the 4th completed focus the following break is a long
    break. tick(now) advances the phase when the current one elapses and returns the new
    phase if it changed (so the UI can react / Serenity can comment), else None."""

    def __init__(self, focus_minutes: int = FOCUS_MINUTES,
                 break_minutes: int = BREAK_MINUTES,
                 long_break_minutes: int = LONG_BREAK_MINUTES,
                 cycles_before_long_break: int = CYCLES_BEFORE_LONG_BREAK) -> None:
        self.focus_minutes = focus_minutes
        self.break_minutes = break_minutes
        self.long_break_minutes = long_break_minutes
        self.cycles_before_long_break = cycles_before_long_break
        self.phase = Phase.IDLE
        self.completed_focus = 0          # focus phases finished this run
        self._ends_at: Optional[datetime] = None
        self._paused_remaining: Optional[int] = None   # seconds left while paused

    # --- duration of a phase (instance overrides the module defaults) ---
    def _duration(self, phase: Phase) -> int:
        return {
            Phase.FOCUS: self.focus_minutes,
            Phase.BREAK: self.break_minutes,
            Phase.LONG_BREAK: self.long_break_minutes,
        }.get(phase, 0)

    @property
    def running(self) -> bool:
        return self.phase != Phase.IDLE and self._paused_remaining is None and self._ends_at is not None

    @property
    def paused(self) -> bool:
        return self._paused_remaining is not None

    def _begin(self, phase: Phase, now: datetime) -> None:
        self.phase = phase
        self._paused_remaining = None
        self._ends_at = now + timedelta(minutes=self._duration(phase))

    def start(self, now: datetime) -> None:
        """Start a fresh focus session (resets the cycle count)."""
        self.completed_focus = 0
        self._begin(Phase.FOCUS, now)

    def remaining_seconds(self, now: datetime) -> int:
        """Whole seconds left in the current phase (0 when idle / elapsed)."""
        if self._paused_remaining is not None:
            return self._paused_remaining
        if self._ends_at is None:
            return 0
        return max(0, int((self._ends_at - now).total_seconds()))

    def pause(self, now: datetime) -> None:
        """Freeze the countdown, remembering the seconds left."""
        if self.phase == Phase.IDLE or self._paused_remaining is not None:
            return
        self._paused_remaining = self.remaining_seconds(now)
        self._ends_at = None

    def resume(self, now: datetime) -> None:
        """Resume a paused countdown from where it stopped."""
        if self._paused_remaining is None:
            return
        self._ends_at = now + timedelta(seconds=self._paused_remaining)
        self._paused_remaining = None

    def stop(self) -> None:
        """End the session entirely (back to idle)."""
        self.phase = Phase.IDLE
        self._ends_at = None
        self._paused_remaining = None
        self.completed_focus = 0

    def _next_phase(self) -> Phase:
        """The phase that follows the one that just elapsed."""
        if self.phase == Phase.FOCUS:
            # a focus just completed -> long break every Nth, else a short break
            if self.completed_focus % self.cycles_before_long_break == 0:
                return Phase.LONG_BREAK
            return Phase.BREAK
        # any break -> back to focus
        return Phase.FOCUS

    def tick(self, now: datetime) -> Optional[Phase]:
        """Advance to the next phase if the current one has elapsed.

        Returns the new phase when a transition happened, else None. Paused / idle
        timers never advance."""
        if not self.running:
            return None
        if self.remaining_seconds(now) > 0:
            return None
        if self.phase == Phase.FOCUS:
            self.completed_focus += 1
        nxt = self._next_phase()
        self._begin(nxt, now)
        return nxt
