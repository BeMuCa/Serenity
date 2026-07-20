"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Verify the mascot busy bracket sets "thinking" on all mascots while the queue
         is busy and reverts to the pre-bracket pose on drain (folds 11.8/11.10).
Role:    Headless test of Shell._on_queue_busy via a fake self (no full Shell boot).

Test classes:
- TestRevertTarget — the pure pose-target decision
- TestBusyBracket — set-thinking-on-all + revert transitions
============================================================
"""
from types import SimpleNamespace

import serenity.ui.shell as shell_mod
from serenity.ui.shell import Shell, revert_pose_target


class _FakeMascot:
    def __init__(self, state="idle"):
        self.current_state = state
    def set_state(self, s, silent=False):
        self.current_state = s


def _fake_self(mascots, context="business"):
    return SimpleNamespace(
        mascot=mascots[0],
        _mascots=lambda: mascots,
        settings=SimpleNamespace(context=lambda: context),
        activity_store=SimpleNamespace(running=lambda: None),
        _busy_active=False, _pre_busy_state=None, _deferred_reaction=None,
    )


class TestRevertTarget:
    def test_prefers_deferred_then_prebusy_then_default(self):
        assert revert_pose_target("success", "working", "business") == "success"
        assert revert_pose_target(None, "working", "business") == "working"
        assert revert_pose_target(None, None, "private") == "chilling"   # CONTEXT_DEFAULT_POSE


class TestBusyBracket:
    def test_busy_sets_thinking_on_all_mascots(self):
        dock, mini = _FakeMascot("working"), _FakeMascot("working")
        fs = _fake_self([dock, mini])
        Shell._on_queue_busy(fs, True)
        assert dock.current_state == "thinking" and mini.current_state == "thinking"
        assert fs._busy_active is True and fs._pre_busy_state == "working"

    def test_drain_reverts_to_pre_busy_pose(self):
        dock = _FakeMascot("working")
        fs = _fake_self([dock])
        Shell._on_queue_busy(fs, True)     # captures "working", sets thinking
        Shell._on_queue_busy(fs, False)    # drain
        assert dock.current_state == "working"
        assert fs._busy_active is False

    def test_drain_without_prebusy_falls_to_context_default(self):
        dock = _FakeMascot("")             # nothing meaningful captured
        fs = _fake_self([dock], context="private")
        fs._busy_active = True; fs._pre_busy_state = None
        Shell._on_queue_busy(fs, False)
        assert dock.current_state == "chilling"


class TestReactionMediator:
    def test_reaction_while_busy_is_deferred_then_replayed(self):
        dock = _FakeMascot("idle")
        fs = _fake_self([dock])
        Shell._on_queue_busy(fs, True)          # thinking, busy
        Shell._react(fs, "success")             # a todo completes mid-job
        assert dock.current_state == "thinking"  # reaction did NOT stomp the busy pose
        assert fs._deferred_reaction == "success"
        Shell._on_queue_busy(fs, False)         # drain
        assert dock.current_state == "success"  # replayed

    def test_reaction_while_idle_applies_immediately(self):
        dock = _FakeMascot("idle")
        fs = _fake_self([dock])
        Shell._react(fs, "working")
        assert dock.current_state == "working"
        assert fs._deferred_reaction is None
