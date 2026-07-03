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

    def test_chip_carries_registry_color(self, qapp, tmp_path, monkeypatch):
        # The chip must show the running activity's REGISTRY color, not a constant accent
        # (Coding=#ff8ad0 differs from the default ACCENT #a78bfa, so it discriminates).
        sh = _shell(tmp_path, monkeypatch)
        try:
            sh._on_activity("Coding")
            assert "#ff8ad0" in sh.todos_view.state_chip.btn.styleSheet()
            assert "#ff8ad0" in sh.notes_view.state_chip.btn.styleSheet()
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

    def test_notes_state_chip_filters(self, qapp, tmp_path, monkeypatch):
        # The notes-side state axis must narrow the list (guards skey wiring in NotesView.refresh).
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.note_store.create("w", state_tag="working", context="business")
            sh.note_store.create("c", state_tag="coding", context="business")
            sh._on_activity("Working")                                 # chip on -> state filter
            shown = [sh.notes_view.list_box.itemAt(i).widget().note.title
                     for i in range(sh.notes_view.list_box.count())]
            assert shown == ["w"]                                      # only the working note
            sh.notes_view.state_chip.btn.setChecked(False)             # uncheck -> axis off
            shown = [sh.notes_view.list_box.itemAt(i).widget().note.title
                     for i in range(sh.notes_view.list_box.count())]
            assert set(shown) == {"w", "c"}
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

    def test_cancel_grace_after_flip_removes_stale_card(self, qapp, tmp_path, monkeypatch):
        # criticizer #2: tick a business todo done (grace armed) -> flip to private (R3
        # re-renders the card) -> un-tick. Cancelling must drop the now-foreign card, not
        # leave it rendered until an unrelated refresh.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            t = sh.todo_store.add(Todo(title="biz", context="business"))
            sh._on_activity("Working")
            sh.todos_view._arm_grace(t)               # simulate the tick's grace arm
            sh.set_context("private")                 # R3: card re-rendered in the private list
            assert any(c.todo.id == t.id for c in sh.todos_view._cards)
            sh.todos_view._cancel_grace(t)            # un-tick within the window
            assert not any(c.todo.id == t.id for c in sh.todos_view._cards)
            assert t.id not in sh.todos_view._grace_timers
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

    def test_todo_notice_gated_on_chip_not_context(self, qapp, tmp_path, monkeypatch):
        # R5: the todo notice fires ONLY while the state chip is checked — never during
        # plain browsing where the context axis alone hides an item (guards the skey guard).
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="priv", context="private"))   # hidden by context, chip OFF
            sh.todos_view.refresh()
            assert sh.todos_view.filter_notice.isHidden()              # context-only hiding: silent
        finally:
            sh.tray.hide()

    def test_notes_hidden_hint_counts(self, qapp, tmp_path, monkeypatch):
        # R5 (notes side): a search that matches a private note, hidden by the business
        # context, shows the count-only notice; plain browsing shows nothing.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.note_store.create("quarterly deadline", context="private")
            sh.notes_view.refresh()
            assert sh.notes_view.filter_notice.isHidden()      # plain browse -> no notice
            sh.notes_view.search.setText("quarterly")
            sh.notes_view.refresh()
            assert not sh.notes_view.filter_notice.isHidden()
            assert "1" in sh.notes_view.filter_notice.text()
            # count-only: the hidden note's TITLE must never leak into the notice
            assert "deadline" not in sh.notes_view.filter_notice.text()
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


class TestCrossSurfaceContext:
    """R13: every other todo-showing surface applies the context axis (state axis never)."""

    def _todos(self):
        from datetime import datetime
        due = datetime(2026, 7, 3, 10, 0)
        return [Todo(title="biz", due=due, context="business"),
                Todo(title="priv", due=due, context="private"),
                Todo(title="old", due=due)]

    def test_calendar_grid_filters_context(self, qapp, tmp_path, monkeypatch):
        from serenity.core.todo_store import TodoStore
        from serenity.core.settings import Settings
        from serenity.ui import calendar_view as mod
        store = TodoStore(tmp_path)
        for t in self._todos():
            store.add(t)
        s = Settings(); s.current_context = "business"; s._path = tmp_path / "s.json"
        seen = {}
        real = mod.collect_events

        def rec(todos, **k):
            seen["t"] = [x.title for x in todos]
            return real(todos, **k)

        monkeypatch.setattr(mod, "collect_events", rec)
        v = mod.CalendarView(store, settings=s)
        v._grid_model()
        assert "priv" not in seen["t"] and {"biz", "old"} <= set(seen["t"])

    def test_week_panel_filters_grid_and_list(self, qapp, tmp_path, monkeypatch):
        from serenity.core.todo_store import TodoStore
        from serenity.core.settings import Settings
        from serenity.ui import calendar_week_panel as mod
        store = TodoStore(tmp_path)
        for t in self._todos():
            store.add(t)
        s = Settings(); s.current_context = "business"; s._path = tmp_path / "s.json"
        seen = {}
        real = mod.collect_events

        def rec(todos, **k):
            seen["grid"] = [x.title for x in todos]
            return real(todos, **k)

        monkeypatch.setattr(mod, "collect_events", rec)
        panel = mod.CalendarWeekPanel(store, s)
        listed = []
        from PySide6.QtWidgets import QFrame
        panel._list_row = lambda t: (listed.append(t.title), QFrame())[1]
        panel.refresh()
        assert "priv" not in seen["grid"]
        assert "priv" not in listed and "biz" in listed

    def test_graph_filters_context(self, qapp, tmp_path, monkeypatch):
        from serenity.core.todo_store import TodoStore
        from serenity.core.settings import Settings
        from serenity.ui import graph_view as mod
        store = TodoStore(tmp_path)
        a = store.add(Todo(title="biz", context="business"))
        store.add(Todo(title="priv", context="private", depends_on=[a.id]))
        s = Settings(); s.current_context = "business"; s._path = tmp_path / "s.json"
        seen = {}
        real = mod.build_graph

        def rec(todos):
            seen["t"] = [x.title for x in todos]
            return real(todos)

        monkeypatch.setattr(mod, "build_graph", rec)
        v = mod.GraphView(store, settings=s)
        v.refresh()
        assert seen["t"] == ["biz"]

    def test_mini_pick_respects_context(self, qapp, tmp_path):
        from serenity.core.todo_store import TodoStore
        from serenity.core.settings import Settings
        from serenity.ui.mini_window import MiniWindow
        store = TodoStore(tmp_path)
        store.add(Todo(title="secret-private", context="private"))
        s = Settings(); s.current_context = "business"; s._path = tmp_path / "s.json"
        s.vault_path = str(tmp_path)
        mini = MiniWindow(store, s)
        assert "secret-private" not in mini.todo_label.text()

    def test_slot_dialog_gets_stamp(self, qapp, tmp_path, monkeypatch):
        from datetime import date
        from serenity.core.todo_store import TodoStore
        from serenity.core.settings import Settings
        from serenity.ui import calendar_week_panel as mod
        got = {}

        class _FakeDlg:
            def __init__(self, store, settings, default_due=None, parent=None, stamp=None):
                got["stamp"] = stamp
                class _Sig:
                    def connect(self, *a): pass
                self.added = _Sig()
            def exec(self): pass

        monkeypatch.setattr(mod, "QuickTodoDialog", _FakeDlg)
        s = Settings(); s._path = tmp_path / "s.json"
        marker = lambda: ("working", "business")
        panel = mod.CalendarWeekPanel(TodoStore(tmp_path), s, stamp=marker)
        panel._handle_slot_click(date(2026, 7, 3), 9)
        assert got["stamp"] is marker            # R11: the slot dialog stamps like every funnel

    def test_sync_context_fans_out_to_surfaces(self, qapp, tmp_path, monkeypatch):
        # The VISIBLE tab re-renders on a flip; hidden tabs self-heal on entry
        # (switch_tab already refreshes them); the mini window always refreshes.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            calls = []
            monkeypatch.setattr(sh.calendar_view, "refresh", lambda: calls.append("cal"))
            mini = sh._ensure_mini()
            monkeypatch.setattr(mini, "refresh_todo", lambda: calls.append("mini"))
            sh.set_context("private")
            assert "mini" in calls and "cal" not in calls      # todos tab is current
            sh.switch_tab("calendar")
            calls.clear()
            sh.set_context("business")
            assert "cal" in calls                              # visible tab re-renders
        finally:
            sh.tray.hide()

    def test_flip_refreshes_open_week_popout(self, qapp, tmp_path, monkeypatch):
        # R13: an open calendar week pop-out is a separate window; a flip must refresh it.
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh._open_calendar_expanded()
            calls = []
            monkeypatch.setattr(sh._expanded._content, "refresh", lambda: calls.append("popout"))
            sh.set_context("private")
            assert "popout" in calls
        finally:
            sh.tray.hide()


class TestAISurfacesContext:
    """R16: AI surfaces rank over context-filtered CANDIDATES; the semantic index
    always sees the FULL active corpus (its prune(keep_ids=...) would otherwise drop
    the other context's embeddings on every flip)."""

    def _view(self, tmp_path, context="business", semantic=None):
        from serenity.core.note_store import NoteStore
        from serenity.core.settings import Settings
        from serenity.ui.notes_view import NotesView
        store = NoteStore(tmp_path / "vault")
        s = Settings(); s.current_context = context; s._path = tmp_path / "s.json"
        return store, NotesView(store, semantic, settings=s)

    def _cards(self, view):
        return [view.list_box.itemAt(i).widget() for i in range(view.list_box.count())]

    def test_filtered_active_narrows_to_context(self, qapp, tmp_path):
        store, view = self._view(tmp_path)
        store.create("biz", context="business")
        store.create("priv", context="private")
        store.create("old")
        view.refresh()
        titles = [n.title for n in view._filtered_active()]
        assert "priv" not in titles and {"biz", "old"} <= set(titles)

    def test_related_chips_exclude_other_context(self, qapp, tmp_path):
        from PySide6.QtWidgets import QPushButton
        store, view = self._view(tmp_path)
        target = store.create("target", body="alpha beta gamma shared", context="business")
        store.create("bizrel", body="alpha beta gamma shared more", context="business")
        store.create("privrel", body="alpha beta gamma shared secret", context="private")
        view.refresh()
        card = next(c for c in self._cards(view) if c.note.id == target.id)
        card._ensure_related()
        chips = [b.text() for b in card.related_wrap.findChildren(QPushButton)]
        assert any("bizrel" in c for c in chips)
        assert not any("privrel" in c for c in chips)

    def test_related_indexes_full_corpus(self, qapp, tmp_path):
        class _Rec:
            available = True
            def __init__(self): self.indexed = []
            def index(self, notes): self.indexed = [n.title for n in notes]
            def population(self): return len(self.indexed)
            def related(self, note, top_k=5): return []
        rec = _Rec()
        store, view = self._view(tmp_path, semantic=rec)
        store.create("biz", body="x", context="business")
        store.create("priv", body="y", context="private")
        view.refresh()
        self._cards(view)[0]._ensure_related()
        assert "priv" in rec.indexed          # full corpus indexed (prune-safety)

    def test_ask_retrieves_over_candidates(self, qapp, tmp_path):
        from PySide6.QtWidgets import QPushButton
        from serenity.ui.ask_dialog import AskDialog
        store, view = self._view(tmp_path)
        store.create("bizfact", body="the quarterly report deadline is friday", context="business")
        store.create("privfact", body="the quarterly report deadline is friday too", context="private")
        dlg = AskDialog(semantic=None, llm=None,
                        notes_provider=store.all_active,
                        candidates_provider=view._filtered_active)
        dlg.question.setText("quarterly report deadline friday")
        dlg._ask()
        chips = [b.text() for b in dlg.findChildren(QPushButton)]
        assert any("bizfact" in c for c in chips)
        assert not any("privfact" in c for c in chips)

    def test_open_ask_passes_filtered_candidates(self, qapp, tmp_path, monkeypatch):
        store, view = self._view(tmp_path)
        store.create("priv", context="private")
        got = {}

        class _FakeAsk:
            def __init__(self, semantic=None, llm=None, notes_provider=None,
                         candidates_provider=None, parent=None):
                got["full"] = [n.title for n in notes_provider()]
                got["cand"] = [n.title for n in candidates_provider()]
            def exec(self): pass

        monkeypatch.setattr("serenity.ui.ask_dialog.AskDialog", _FakeAsk)
        view._open_ask()
        assert "priv" in got["full"] and "priv" not in got["cand"]

    def test_open_duplicates_scans_filtered_candidates(self, qapp, tmp_path, monkeypatch):
        store, view = self._view(tmp_path)
        store.create("priv", context="private")
        got = {}

        class _Sig:
            def connect(self, *a): pass

        class _FakeDup:
            def __init__(self, store, semantic=None, notes_provider=None, parent=None):
                got["cand"] = [n.title for n in notes_provider()]
                self.merged = _Sig()
            def exec(self): pass

        monkeypatch.setattr("serenity.ui.duplicates_dialog.DuplicatesDialog", _FakeDup)
        view._open_duplicates()
        assert "priv" not in got["cand"]


class TestTrashContextSuffix:
    def test_rows_show_context_suffix(self, qapp, tmp_path):
        # R14: Trash stays UNFILTERED (everything reachable) but names each item's context.
        from PySide6.QtWidgets import QLabel
        from serenity.core.note_store import NoteStore
        from serenity.core.todo_store import TodoStore
        from serenity.ui.trash_view import TrashView
        ts, ns = TodoStore(tmp_path), NoteStore(tmp_path)
        t = ts.add(Todo(title="t1", context="private")); ts.complete(t.id)
        n = ns.create("n1", context="business"); ns.soft_delete(n.id)
        n2 = ns.create("n2"); ns.soft_delete(n2.id)     # unstamped -> no suffix
        view = TrashView(ts, ns)
        metas = [l.text() for l in view.findChildren(QLabel)]
        assert "todo - done - private" in metas
        assert "note - deleted - business" in metas
        assert "note - deleted" in metas


class TestUrgencyPeek:
    """Urgency-peek: urgent todos surface through the two-axis filter (spec R-A..R-F)."""

    def _titles_in_view(self, view):
        from PySide6.QtWidgets import QLabel
        return " ".join(l.text() for l in view.findChildren(QLabel))

    def test_cross_context_urgent_renders_blurred_placeholder(self, qapp, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="secret clinic call", context="private",
                                   due=datetime.now() + timedelta(hours=1)))
            sh.todos_view.refresh()
            assert len(sh.todos_view._peek_widgets) == 1               # exactly one placeholder
            assert [c for c in sh.todos_view._cards] == []             # no full card
            joined = self._titles_in_view(sh.todos_view)
            assert "secret clinic call" not in joined                  # privacy: title absent
            assert "🔒 Private item" in joined
        finally:
            sh.tray.hide()

    def test_same_context_offstate_urgent_full_card_on_top(self, qapp, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="calm", state_tag="working", context="business"))
            sh.todo_store.add(Todo(title="hot", state_tag="coding", context="business",
                                   due=datetime.now() + timedelta(hours=1)))
            sh.todo_store.add(Todo(title="cold", state_tag="coding", context="business"))
            sh._on_activity("Working")                                 # chip on
            titles = [c.todo.title for c in sh.todos_view._cards]
            assert titles == ["hot", "calm"]                           # urgent peek ranked on top
            assert not sh.todos_view.filter_notice.isHidden()
            assert "1" in sh.todos_view.filter_notice.text()           # only 'cold' counted hidden
        finally:
            sh.tray.hide()

    def test_grace_beats_peek_one_full_card(self, qapp, tmp_path, monkeypatch):
        # R-C: grace-pending bypasses classification - one full card, undo reachable,
        # not counted hidden; after cancel it becomes the blurred placeholder.
        from datetime import datetime, timedelta
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            t = sh.todo_store.add(Todo(title="priv urgent", context="private",
                                       due=datetime.now() + timedelta(hours=1)))
            sh.todos_view._arm_grace(t)
            sh.todos_view.refresh()
            assert [c.todo.id for c in sh.todos_view._cards] == [t.id]  # exactly one full card
            assert sh.todos_view._peek_widgets == []                    # never also a placeholder
            sh.todos_view._cancel_grace(t)
            assert all(c.todo.id != t.id for c in sh.todos_view._cards)
            assert len(sh.todos_view._peek_widgets) == 1                # now blurred instead
        finally:
            sh.tray.hide()

    def test_tick_serves_placeholder_when_only_urgent_item(self, qapp, tmp_path, monkeypatch):
        # R-B: the 1s tick stays active for a lone blurred item and updates its label.
        from datetime import datetime, timedelta
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="s", context="private",
                                   due=datetime.now() + timedelta(hours=1)))
            sh.todos_view.refresh()
            assert sh.todos_view._tick_timer.isActive()
            w = sh.todos_view._peek_widgets[0]
            w.tick(datetime.now() + timedelta(minutes=45))
            assert "in 15 min" in w.label.text()
        finally:
            sh.tray.hide()

    def test_boundary_timer_arms_for_earliest_hidden_crossing(self, qapp, tmp_path, monkeypatch):
        # R-A: a hidden due-dated todo arms the single-shot re-classification timer.
        from datetime import datetime, timedelta
        from serenity.core.ranking import WARN_HOURS
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="later", context="private",
                                   due=datetime.now() + timedelta(hours=WARN_HOURS, minutes=10)))
            sh.todos_view.refresh()
            bt = sh.todos_view._boundary_timer
            assert bt.isActive()
            assert 0 < bt.remainingTime() <= 10 * 60 * 1000 + 2000     # ~10min to the boundary
            calls = []
            monkeypatch.setattr(sh.todos_view, "refresh", lambda: calls.append(True))
            bt.timeout.emit()
            assert calls == [True]                                     # firing re-classifies
        finally:
            sh.tray.hide()

    def test_boundary_timer_disarmed_without_hidden_due(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="visible", context="business"))
            sh.todos_view.refresh()
            assert not sh.todos_view._boundary_timer.isActive()
        finally:
            sh.tray.hide()

    def test_placeholder_confirm_flips_context_and_reveals(self, qapp, tmp_path, monkeypatch):
        from datetime import datetime, timedelta
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            sh.todo_store.add(Todo(title="secret", context="private",
                                   due=datetime.now() + timedelta(hours=1)))
            sh.todos_view.refresh()
            w = sh.todos_view._peek_widgets[0]
            w.mousePressEvent(None)                                    # arm
            assert sh.settings.context() == "business"                 # single click never flips
            monkeypatch.setattr(w, "_confirm_gate_open", lambda: True)
            w.mousePressEvent(None)                                    # deliberate confirm
            assert sh.settings.context() == "private"
            assert "secret" in [c.todo.title for c in sh.todos_view._cards]   # revealed
        finally:
            sh.tray.hide()

    def test_resume_refreshes_todos(self, qapp, tmp_path, monkeypatch):
        sh = _shell(tmp_path, monkeypatch, "business")
        try:
            calls = []
            monkeypatch.setattr(sh.todos_view, "refresh", lambda: calls.append(True))
            sh._last_resume = 0.0
            sh._on_resume()
            assert calls == [True]
        finally:
            sh.tray.hide()


class TestMiniPeek:
    """R-H: the always-on-top mini card must not claim 'All clear' while an urgent
    cross-context todo exists - it shows the title-free blurred line instead."""

    def _mini(self, tmp_path, context="business"):
        from serenity.core.settings import Settings
        from serenity.core.todo_store import TodoStore
        from serenity.ui.mini_window import MiniWindow
        store = TodoStore(tmp_path)
        s = Settings(); s.current_context = context
        s.vault_path = str(tmp_path); s._path = tmp_path / "s.json"
        return store, s

    def test_peek_line_replaces_all_clear(self, qapp, tmp_path):
        from datetime import datetime, timedelta
        from serenity.ui.mini_window import MiniWindow
        store, s = self._mini(tmp_path)
        store.add(Todo(title="secret call", context="private",
                       due=datetime.now() + timedelta(hours=1)))
        mini = MiniWindow(store, s)
        assert not mini.peek_label.isHidden()
        assert "🔒 Private item" in mini.peek_label.text()
        assert "secret call" not in mini.peek_label.text()
        assert "All clear" not in mini.todo_label.text()          # no lie on the surface
        mini.hide()

    def test_peek_line_under_a_pick(self, qapp, tmp_path):
        from datetime import datetime, timedelta
        from serenity.ui.mini_window import MiniWindow
        store, s = self._mini(tmp_path)
        store.add(Todo(title="biz task", context="business"))
        store.add(Todo(title="secret", context="private",
                       due=datetime.now() + timedelta(hours=1)))
        mini = MiniWindow(store, s)
        assert mini.todo_label.text() == "biz task"               # the pick stays
        assert not mini.peek_label.isHidden()                     # line beneath it
        mini.hide()

    def test_no_peek_line_without_urgent_cross_context(self, qapp, tmp_path):
        from serenity.ui.mini_window import MiniWindow
        store, s = self._mini(tmp_path)
        store.add(Todo(title="calm private", context="private"))  # cross-context, NOT urgent
        mini = MiniWindow(store, s)
        assert mini.peek_label.isHidden()
        assert "All clear" in mini.todo_label.text()
        mini.hide()

    def test_done_or_deleted_never_peek(self, qapp, tmp_path):
        from datetime import datetime, timedelta
        from serenity.ui.mini_window import MiniWindow
        store, s = self._mini(tmp_path)
        t = store.add(Todo(title="gone", context="private",
                           due=datetime.now() - timedelta(minutes=5)))   # overdue but...
        store.complete(t.id)                                             # ...done
        mini = MiniWindow(store, s)
        assert mini.peek_label.isHidden()
        mini.hide()

    def test_click_emits_context_toggle(self, qapp, tmp_path):
        from datetime import datetime, timedelta
        from serenity.ui.mini_window import MiniWindow
        store, s = self._mini(tmp_path)
        store.add(Todo(title="secret", context="private",
                       due=datetime.now() + timedelta(hours=1)))
        mini = MiniWindow(store, s)
        fired = []
        mini.context_toggle_requested.connect(lambda: fired.append(True))
        mini.peek_label.mousePressEvent(None)
        assert fired == [True]
        mini.hide()
