"""
============================================================
Author:  Berk
Created: 2026-07-03
Purpose: UI tests for the Phase C two-axis filtering (context + state chip).
Role:    Under QT_QPA_PLATFORM=offscreen, assert the state chip's lifecycle
         (boot restore, auto-select, manual uncheck, idle/unmappable, context
         flip) and the list post-filters + grace/hint safety nets (R1-R5, R7, R15).

Test classes:
- TestStateChipLifecycle - the spec §7 chip behavior table, row by row
- TestListFilters - context/state post-filters, grace survival, hidden hints
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from serenity.core.models import Note, Todo


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _shell(tmp_path, monkeypatch, context="business"):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from serenity.ui import platform_win
    from serenity.core import paths
    monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
    monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
    from serenity.ui.shell import Shell
    sh = Shell()
    sh.settings.current_context = context
    return sh


def _chip_state(view):
    """(hidden, checked) of a view's state chip."""
    return view.state_chip.isHidden(), view.state_chip.btn.isChecked()


class TestStateChipLifecycle:
    def test_chip_hidden_when_idle(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch)
        try:
            assert _chip_state(sh.todos_view) == (True, False)
            assert _chip_state(sh.notes_view) == (True, False)
            sh._on_activity("Working")
            assert _chip_state(sh.todos_view) == (False, True)    # auto-selected
            sh._on_activity("Idle")
            assert _chip_state(sh.todos_view) == (True, False)    # hidden again, filter off
        finally:
            sh.tray.hide()

    def test_chip_boot_restore(self, qapp, tmp_path, monkeypatch):
        # R1: a span persisted in activity.json drives the chip at construction,
        # without any activity_changed emission.
        from serenity.core.activity_store import ActivityStore
        ActivityStore(tmp_path / "vault").start("Working")
        sh = _shell(tmp_path, monkeypatch)
        try:
            assert _chip_state(sh.todos_view) == (False, True)
            assert _chip_state(sh.notes_view) == (False, True)
            assert "Working" in sh.todos_view.state_chip.btn.text()
        finally:
            sh.tray.hide()

    def test_chip_auto_recheck_on_switch(self, qapp, tmp_path, monkeypatch):
        # R4: manual uncheck lasts only for the current span.
        sh = _shell(tmp_path, monkeypatch)
        try:
            sh._on_activity("Working")
            sh.todos_view.state_chip.btn.setChecked(False)        # manual uncheck
            sh.todos_view.refresh()
            assert _chip_state(sh.todos_view) == (False, False)   # sticks within the span
            sh._on_activity("Coding")
            assert _chip_state(sh.todos_view) == (False, True)    # re-checked + relabeled
            assert "Coding" in sh.todos_view.state_chip.btn.text()
        finally:
            sh.tray.hide()

    def test_manual_uncheck_is_per_view(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch)
        try:
            sh._on_activity("Working")
            sh.todos_view.state_chip.btn.setChecked(False)
            assert _chip_state(sh.notes_view) == (False, True)    # the other view unaffected
        finally:
            sh.tray.hide()

    def test_chip_unmappable_hidden(self, qapp, tmp_path, monkeypatch):
        # R2: a running span whose label left the registry = same as idle.
        sh = _shell(tmp_path, monkeypatch)
        try:
            sh.activity_store.start("NoSuchLabel")
            sh._sync_state_chips()
            assert _chip_state(sh.todos_view) == (True, False)
        finally:
            sh.tray.hide()

    def test_flip_cross_context_unchecks(self, qapp, tmp_path, monkeypatch):
        # R7 (conflict resolution): chip stays VISIBLE (the span truth) but UNCHECKED.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Working")                            # business-only activity
            sh.set_context("private")
            assert _chip_state(sh.todos_view) == (False, False)
            assert _chip_state(sh.notes_view) == (False, False)
            # R15: the span itself is never stopped by a flip; stamps use the new context
            assert sh.activity_store.running() is not None
            assert sh.stamp() == ("working", "private")           # legal cross-context pair
        finally:
            sh.tray.hide()

    def test_flip_matching_context_preserves_chip(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh._on_activity("Working")
            sh.todos_view.state_chip.btn.setChecked(False)        # manual uncheck...
            sh.set_context("private")
            sh.set_context("business")                            # ...survives a flip round-trip
            assert _chip_state(sh.todos_view) == (False, False)
        finally:
            sh.tray.hide()


class TestListFilters:
    def test_context_filter_hides_lists(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="biz", context="business"))
            sh.todo_store.add(Todo(title="priv", context="private"))
            sh.todo_store.add(Todo(title="old"))                   # unstamped -> both
            sh.todos_view.refresh()
            titles = [c.todo.title for c in sh.todos_view._cards]
            assert "biz" in titles and "old" in titles and "priv" not in titles
            sh.note_store.create("biznote", context="business")
            sh.note_store.create("privnote", context="private")
            sh.notes_view.refresh()
            shown = [sh.notes_view.list_box.itemAt(i).widget().note.title
                     for i in range(sh.notes_view.list_box.count())]
            assert "biznote" in shown and "privnote" not in shown
        finally:
            sh.tray.hide()

    def test_state_chip_filters_todos(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="w", state_tag="working", context="business"))
            sh.todo_store.add(Todo(title="c", state_tag="coding", context="business"))
            sh.todo_store.add(Todo(title="n", context="business"))     # no state
            sh._on_activity("Working")                                 # chip on -> filter
            titles = [c.todo.title for c in sh.todos_view._cards]
            assert titles == ["w"]
            sh.todos_view.state_chip.btn.setChecked(False)             # uncheck -> axis off
            titles = [c.todo.title for c in sh.todos_view._cards]
            assert set(titles) == {"w", "c", "n"}
        finally:
            sh.tray.hide()

    def test_grace_pending_survives_filter(self, qapp, tmp_path, monkeypatch):
        # R3: a todo in its done-grace window renders even when the filter would hide it.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            t = sh.todo_store.add(Todo(title="p", context="private"))  # hidden in business
            from PySide6.QtCore import QTimer
            timer = QTimer(sh.todos_view)
            timer.setSingleShot(True)
            sh.todos_view._grace_timers[t.id] = timer
            sh.todos_view.refresh()
            titles = [c.todo.title for c in sh.todos_view._cards]
            assert "p" in titles                                       # undo stays reachable
        finally:
            sh.tray.hide()

    def test_hidden_hint_counts(self, qapp, tmp_path, monkeypatch):
        # R5: count-only notice when the chip hides active todos; none in plain browsing.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="w", state_tag="working", context="business"))
            sh.todo_store.add(Todo(title="c", state_tag="coding", context="business"))
            sh.todos_view.refresh()
            assert sh.todos_view.filter_notice.isHidden()              # no chip -> no notice
            sh._on_activity("Working")
            assert not sh.todos_view.filter_notice.isHidden()
            assert "1" in sh.todos_view.filter_notice.text()
        finally:
            sh.tray.hide()

    def test_completed_bubble_suppressed_cross_context(self, qapp, tmp_path, monkeypatch):
        # R3: completing a hidden (other-context) todo never narrates its title.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            said = []
            monkeypatch.setattr(sh.mascot, "says", lambda *a, **k: said.append(a))
            sh._on_todo_completed(Todo(title="secret", context="private"))
            assert said == []
            sh._on_todo_completed(Todo(title="open", context="business"))
            assert len(said) == 1
        finally:
            sh.tray.hide()
