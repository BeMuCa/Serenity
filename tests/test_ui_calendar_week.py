"""
============================================================
Author:  Berk
Created: 2026-06-29
Purpose: Headless smoke tests for the expanded Calendar week pop-out (ui.calendar_week_panel).
Role:    Under QT_QPA_PLATFORM=offscreen, assert CalendarWeekPanel builds + refresh() renders
         the day x hour grid + all-day strip + active-todo list, that week nav shifts the anchor,
         that an event click emits open_todo(id), and that the lifecycle/refresh seams
         (on_panel_activated -> refresh, handle_close -> True) behave. Pure layout (build_timegrid)
         is covered by tests/test_calview.py.

Test classes:
- TestCalendarWeekPanel - builds, renders grid/strip/list, nav, click-through, refresh, lifecycle
============================================================
"""
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from serenity.core.models import Todo  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.calendar_week_panel import CalendarWeekPanel  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _rendered_active_titles(panel) -> list:
    """Titles actually rendered into the panel's right-hand list (reads the QFrame#card rows),
    so the test verifies the panel renders the active todos, not just that the store has them."""
    out = []
    for i in range(panel._list.count()):
        w = panel._list.itemAt(i).widget()
        if w is not None and w.objectName() == "card":
            lbl = w.findChild(QLabel)
            if lbl is not None:
                out.append(lbl.text())
    return out


def _this_week_day(weekday: int, hour: int):
    """A datetime on the given weekday (Mon=0) of the current week, at the given hour."""
    today = datetime.now()
    monday = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday + timedelta(days=weekday, hours=hour)


class TestCalendarWeekPanel:
    def test_builds_empty(self, qapp, tmp_path):
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        panel.refresh()  # must not raise on an empty store

    def test_timed_event_lands_in_day_hour_cell(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Standup", due=_this_week_day(0, 9)))
        panel = CalendarWeekPanel(store)
        grid = panel._grid
        day = _this_week_day(0, 9).date()
        assert (day, 9) in grid.cells
        assert [e.title for e in grid.cells[(day, 9)]] == ["Standup"]

    def test_all_day_event_lands_in_strip(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        midnight = _this_week_day(1, 0)  # 00:00 -> all-day
        store.add(Todo(title="Birthday", due=midnight))
        panel = CalendarWeekPanel(store)
        assert [e.title for e in panel._grid.all_day[midnight.date()]] == ["Birthday"]

    def test_week_nav_shifts_anchor(self, qapp, tmp_path):
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        start = panel._anchor
        panel._go_next()
        assert (panel._anchor - start).days == 7
        panel._go_prev()
        assert panel._anchor == start
        panel._go_next()
        panel._go_today()
        assert panel._anchor == datetime.now().date()

    def test_event_click_emits_open_todo_with_id(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        todo = store.add(Todo(title="Dentist", due=_this_week_day(2, 14)))
        panel = CalendarWeekPanel(store)
        seen: list[str] = []
        panel.open_todo.connect(seen.append)
        block = panel._event_block(panel._grid.cells[(_this_week_day(2, 14).date(), 14)][0])
        block.click()
        assert seen == [todo.id]

    def test_right_list_shows_active_omits_done_and_trashed(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Open one", due=_this_week_day(0, 9)))
        done = store.add(Todo(title="Done one", due=_this_week_day(0, 10)))
        trashed = store.add(Todo(title="Trashed one"))
        store.complete(done.id)
        store.soft_delete(trashed.id)
        panel = CalendarWeekPanel(store)
        titles = _rendered_active_titles(panel)
        assert "Open one" in titles
        assert "Done one" not in titles
        assert "Trashed one" not in titles

    def test_refresh_picks_up_a_new_todo(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store)
        assert "Later" not in _rendered_active_titles(panel)
        store.add(Todo(title="Later", due=_this_week_day(3, 11)))
        panel.refresh()
        assert "Later" in _rendered_active_titles(panel)

    def test_on_panel_activated_refreshes(self, qapp, tmp_path, monkeypatch):
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        calls: list[int] = []
        monkeypatch.setattr(panel, "refresh", lambda: calls.append(1))
        panel.on_panel_activated()
        assert calls == [1]

    def test_handle_close_is_true(self, qapp, tmp_path):
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        assert panel.handle_close() is True

    def test_event_renders_into_correct_grid_cell(self, qapp, tmp_path):
        # discriminating: the block is placed in the (hour+1, day_col) cell widget, not the strip
        store = TodoStore(tmp_path)
        store.add(Todo(title="Standup", due=_this_week_day(0, 9)))      # Mon 09:00
        panel = CalendarWeekPanel(store)
        day = _this_week_day(0, 9).date()
        col = panel._grid.days.index(day) + 1
        cell = panel._gridlay.itemAtPosition(9 + 1, col).widget()       # row = hour + 1
        blocks = cell.findChildren(QPushButton)
        assert any(b.text().startswith("09:00") and "Standup" in b.text() for b in blocks)
        ad = panel._allday.itemAtPosition(0, col).widget()             # not in the all-day strip
        assert not any("Standup" in b.text() for b in ad.findChildren(QPushButton))

    def test_all_day_event_renders_into_strip_not_grid(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Birthday", due=_this_week_day(1, 0)))     # Tue 00:00 -> all-day
        panel = CalendarWeekPanel(store)
        day = _this_week_day(1, 0).date()
        col = panel._grid.days.index(day) + 1
        ad = panel._allday.itemAtPosition(0, col).widget()
        assert any("Birthday" in b.text() for b in ad.findChildren(QPushButton))
        cell = panel._gridlay.itemAtPosition(0 + 1, col).widget()       # the 00:00 hour cell
        assert not any("Birthday" in b.text() for b in cell.findChildren(QPushButton))

    def test_first_show_scrolls_to_working_hours_once(self, qapp, tmp_path, monkeypatch):
        # spec §6: viewport scrolls to ~08:00 on first show, and the latch survives a re-show (P3-4)
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        calls: list[int] = []
        monkeypatch.setattr(panel, "_scroll_to_working_hours", lambda: calls.append(1))
        assert panel._scrolled is False
        panel.show()
        qapp.processEvents()
        assert panel._scrolled is True and calls == [1]
        panel.hide()
        panel.show()
        qapp.processEvents()
        assert calls == [1]                                            # never re-scrolls
        panel.close()

    def test_scroll_targets_working_hours_offset(self, qapp, tmp_path):
        from serenity.ui.calendar_week_panel import _ROW_H, _SCROLL_HOUR
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        panel._scroll.setFixedHeight(120)
        panel._grid_host.setFixedHeight(24 * _ROW_H + 400)             # range >> target, no clamp
        panel.show()
        qapp.processEvents()
        panel._scroll_to_working_hours()                               # after range settled
        assert panel._scroll.verticalScrollBar().value() == _SCROLL_HOUR * _ROW_H
        panel.close()


# --------------------------------------------------------------------------------------------
# slice (b): drag-to-reschedule write path. Drops are driven by calling the drop-target cell's
# dropEvent directly with a fake event carrying mimeData().text() (the only contract dropEvent
# reads), so the tests need no real OS drag loop under offscreen.
# --------------------------------------------------------------------------------------------

class _FakeMime:
    def __init__(self, text: str):
        self._t = text

    def text(self) -> str:
        return self._t

    def hasText(self) -> bool:
        return bool(self._t)


class _FakeDropEvent:
    """Carries mimeData().text(); records acceptProposedAction() so the test sees the cell
    accepted the drop (the stale/no-op path accepts WITHOUT writing)."""

    def __init__(self, text: str):
        self._mime = _FakeMime(text)
        self.accepted = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True


def _hour_cell_widget(panel, day, hour):
    col = panel._grid.days.index(day) + 1
    return panel._gridlay.itemAtPosition(hour + 1, col).widget()


def _allday_cell_widget(panel, day):
    col = panel._grid.days.index(day) + 1
    return panel._allday.itemAtPosition(0, col).widget()


class TestCalendarWeekPanelDrop:
    def test_drop_on_hour_cell_reschedules_keeps_minute(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="Move me", due=_this_week_day(0, 14).replace(minute=30)))
        panel = CalendarWeekPanel(store)
        target_day = _this_week_day(2, 0).date()          # Wed
        cell = _hour_cell_widget(panel, target_day, 9)
        ev = _FakeDropEvent(t.id)
        cell.dropEvent(ev)
        got = store.get(t.id).due
        assert (got.year, got.month, got.day) == (target_day.year, target_day.month, target_day.day)
        assert got.hour == 9 and got.minute == 30        # H5: hour set, minute kept
        assert got.second == 0 and got.microsecond == 0   # H5: sec/micro zeroed
        assert ev.accepted is True

    def test_drop_no_time_todo_lands_on_hour_minute_zero(self, qapp, tmp_path):
        # H5: a no-time todo (due=None) dropped on hour H -> D@H:00, exercising the `t.due or
        # midnight` fallback (a mutant dropping the fallback would AttributeError on None.replace).
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="No time", due=None))
        panel = CalendarWeekPanel(store)
        target_day = _this_week_day(2, 0).date()
        cell = _hour_cell_widget(panel, target_day, 9)
        cell.dropEvent(_FakeDropEvent(t.id))
        got = store.get(t.id).due
        assert (got.year, got.month, got.day) == (target_day.year, target_day.month, target_day.day)
        assert got.hour == 9 and got.minute == 0 and got.second == 0 and got.microsecond == 0

    def test_drop_emits_wrote(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="Move me", due=_this_week_day(0, 14)))
        panel = CalendarWeekPanel(store)
        seen: list[int] = []
        panel.wrote.connect(lambda: seen.append(1))
        cell = _hour_cell_widget(panel, _this_week_day(1, 0).date(), 10)
        cell.dropEvent(_FakeDropEvent(t.id))
        assert seen == [1]

    def test_drop_on_allday_strip_sets_exact_midnight(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        # a timed todo whose due carries seconds: the all-day drop must land EXACT midnight (H5),
        # not .replace(hour=0,minute=0) which would leak the inherited seconds -> read as timed.
        t = store.add(Todo(title="Make all-day", due=_this_week_day(0, 14).replace(second=45)))
        panel = CalendarWeekPanel(store)
        target_day = _this_week_day(3, 0).date()          # Thu
        cell = _allday_cell_widget(panel, target_day)
        cell.dropEvent(_FakeDropEvent(t.id))
        got = store.get(t.id).due
        assert got == datetime(target_day.year, target_day.month, target_day.day)
        # and it renders into the strip, not the off-screen 00:00 hour cell
        panel.refresh()
        ad = _allday_cell_widget(panel, target_day)
        assert any("Make all-day" in b.text() for b in ad.findChildren(QPushButton))

    def test_drop_of_done_id_does_not_write_and_refreshes(self, qapp, tmp_path, monkeypatch):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="Finished", due=_this_week_day(0, 9)))
        original_due = t.due
        store.complete(t.id)                               # done todo stays in _todos
        panel = CalendarWeekPanel(store)
        # grab a target cell on the live grid BEFORE monkeypatching refresh
        cell = _hour_cell_widget(panel, _this_week_day(2, 0).date(), 11)
        calls: list[int] = []
        wrote: list[int] = []
        monkeypatch.setattr(panel, "refresh", lambda: calls.append(1))
        panel.wrote.connect(lambda: wrote.append(1))
        ev = _FakeDropEvent(t.id)
        cell.dropEvent(ev)
        assert store.get(t.id).due == original_due         # H1: no write onto a done todo
        assert calls == [1]                                # grid self-heals
        assert wrote == []                                 # no wrote on the no-op path
        assert ev.accepted is True

    def test_drop_of_deleted_id_does_not_write(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="Trashed", due=_this_week_day(0, 9)))
        original_due = t.due
        store.soft_delete(t.id)
        panel = CalendarWeekPanel(store)
        cell = _hour_cell_widget(panel, _this_week_day(2, 0).date(), 11)
        ev = _FakeDropEvent(t.id)
        cell.dropEvent(ev)
        assert store.get(t.id).due == original_due         # H1: no write onto a deleted todo
        assert ev.accepted is True

    def test_drop_of_unknown_id_self_heals_no_write(self, qapp, tmp_path, monkeypatch):
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store)
        cell = _hour_cell_widget(panel, _this_week_day(2, 0).date(), 11)
        calls: list[int] = []
        wrote: list[int] = []
        monkeypatch.setattr(panel, "refresh", lambda: calls.append(1))
        panel.wrote.connect(lambda: wrote.append(1))
        ev = _FakeDropEvent("no-such-id")
        cell.dropEvent(ev)                                 # H1: t is None -> accept, refresh, no write
        assert ev.accepted is True
        assert calls == [1]                                # grid self-heals
        assert wrote == []                                 # no wrote on the no-op path
        assert len(store.all()) == 0                       # nothing created

    def test_hour_cell_accepts_drag_enter_with_text(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store)
        cell = _hour_cell_widget(panel, _this_week_day(0, 0).date(), 9)
        assert cell.acceptDrops() is True
        ev = _FakeDropEvent("anything")
        cell.dragEnterEvent(ev)
        assert ev.accepted is True

    def test_right_list_row_is_drag_source_not_drop_target(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, Qt as _Qt
        import serenity.ui.calendar_week_panel as mod
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="Draggable", due=_this_week_day(0, 9)))
        panel = CalendarWeekPanel(store)
        row = panel._list_row(t)
        assert row.acceptDrops() is False                  # H6: never a drop target
        dragged: list[str] = []
        monkeypatch.setattr(mod, "_start_id_drag", lambda w, tid: dragged.append(tid))
        press = QMouseEvent(QEvent.MouseButtonPress, QPoint(2, 2), _Qt.LeftButton,
                            _Qt.LeftButton, _Qt.NoModifier)
        row.mousePressEvent(press)                          # H6: a left-press starts an id drag
        assert dragged == [t.id]

    def test_event_block_click_still_emits_open_todo(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        todo = store.add(Todo(title="Dentist", due=_this_week_day(2, 14)))
        panel = CalendarWeekPanel(store)
        seen: list[str] = []
        panel.open_todo.connect(seen.append)
        block = panel._event_block(panel._grid.cells[(_this_week_day(2, 14).date(), 14)][0])
        block.click()                                      # plain click (no drag) -> deep-link
        assert seen == [todo.id]

    def test_drop_ringing_todo_silences_the_active_ring(self, qapp, tmp_path):
        # R-12: when a ringing todo (reminder_active set) is dropped on a new slot, the stale ring
        # must clear (reminder_active and reminder_nudge_at -> None), but reminder_fired stays
        # untouched so the lower armed rungs re-fire on the recomputed schedule.
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="Ringing", due=_this_week_day(0, 9), reminder_offsets=[60]))
        # Simulate a ringing state: reminder_active=60, reminder_nudge_at set
        t.reminder_active = 60
        t.reminder_nudge_at = datetime.now() + timedelta(minutes=5)
        store.update(t)
        panel = CalendarWeekPanel(store)
        target_day = _this_week_day(2, 0).date()          # Wed
        target_hour = 14
        cell = _hour_cell_widget(panel, target_day, target_hour)
        ev = _FakeDropEvent(t.id)
        cell.dropEvent(ev)
        got = store.get(t.id)
        # reminder_active and reminder_nudge_at should be cleared
        assert got.reminder_active is None
        assert got.reminder_nudge_at is None
        # due should be updated to the new slot
        assert (got.due.year, got.due.month, got.due.day) == (target_day.year, target_day.month, target_day.day)
        assert got.due.hour == target_hour
        # reminder_offsets and reminder_fired should be unchanged
        assert got.reminder_offsets == [60]
        assert got.reminder_fired == []
        assert ev.accepted is True

    def test_event_block_past_threshold_starts_drag_not_click(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, Qt as _Qt
        from PySide6.QtWidgets import QApplication
        store = TodoStore(tmp_path)
        todo = store.add(Todo(title="Dentist", due=_this_week_day(2, 14)))
        panel = CalendarWeekPanel(store)
        block = panel._event_block(panel._grid.cells[(_this_week_day(2, 14).date(), 14)][0])
        started: list[str] = []
        monkeypatch.setattr(block, "_start_drag", lambda: started.append(todo.id))
        # press, then move past the threshold -> _dragging set, drag started
        press = QMouseEvent(QEvent.MouseButtonPress, QPoint(2, 2), _Qt.LeftButton,
                            _Qt.LeftButton, _Qt.NoModifier)
        block.mousePressEvent(press)
        far = QApplication.startDragDistance() + 5
        move = QMouseEvent(QEvent.MouseMove, QPoint(2 + far, 2 + far), _Qt.LeftButton,
                           _Qt.LeftButton, _Qt.NoModifier)
        block.mouseMoveEvent(move)
        assert started == [todo.id]
        assert block._dragging is True


# --------------------------------------------------------------------------------------------
# slice (b) Task 3: create-on-slot. QuickTodoDialog is monkeypatched so no modal exec runs; the
# fake captures the default_due kwarg (the only contract the slot-click path must satisfy) and
# exposes an `added` signal the panel connects to _on_created. H8 (out-of-week create re-anchors)
# is driven directly through _on_created with a Todo whose due is in another week.
# --------------------------------------------------------------------------------------------

class _FakeDialog:
    """Stand-in for QuickTodoDialog: records ctor args, exposes an `added` signal, never exec()s."""

    instances: list = []

    def __init__(self, todo_store, settings, parent=None, default_due=None, stamp=None):
        from PySide6.QtCore import QObject, Signal

        class _Emitter(QObject):
            added = Signal(object)

        self.todo_store = todo_store
        self.settings = settings
        self.stamp = stamp
        self.parent = parent
        self.default_due = default_due
        self._emitter = _Emitter()
        self.added = self._emitter.added
        self.exec_called = False
        _FakeDialog.instances.append(self)

    def exec(self):
        self.exec_called = True       # the panel may call exec(); the fake never blocks


class _FakeSettings:
    """Stand-in for Settings: the panel reads .context() (Phase C) and forwards the
    object to QuickTodoDialog; business = the neutral no-filter default here."""

    def context(self):
        return "business"


class TestCalendarWeekPanelCreate:
    def test_settings_ctor_param_optional_default_none(self, qapp, tmp_path):
        # slice-(a) construction (no settings) stays valid; create path is inert when None
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        assert panel._settings is None

    def test_empty_hour_cell_click_opens_dialog_with_slot_default_due(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.calendar_week_panel as mod
        _FakeDialog.instances.clear()
        monkeypatch.setattr(mod, "QuickTodoDialog", _FakeDialog)
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store, settings=_FakeSettings())
        day = _this_week_day(2, 0).date()                  # Wed, empty cell
        panel._handle_slot_click(day, 9)
        assert len(_FakeDialog.instances) == 1
        dlg = _FakeDialog.instances[0]
        assert dlg.default_due == datetime(day.year, day.month, day.day, 9)
        assert dlg.todo_store is store

    def test_empty_allday_cell_click_opens_dialog_with_midnight_default_due(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.calendar_week_panel as mod
        _FakeDialog.instances.clear()
        monkeypatch.setattr(mod, "QuickTodoDialog", _FakeDialog)
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store, settings=_FakeSettings())
        day = _this_week_day(3, 0).date()                  # Thu all-day strip
        panel._handle_slot_click(day, None)
        dlg = _FakeDialog.instances[0]
        assert dlg.default_due == datetime(day.year, day.month, day.day)   # exact midnight, no hour

    def test_create_path_inert_when_settings_none(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.calendar_week_panel as mod
        _FakeDialog.instances.clear()
        monkeypatch.setattr(mod, "QuickTodoDialog", _FakeDialog)
        panel = CalendarWeekPanel(TodoStore(tmp_path))   # settings None
        panel._handle_slot_click(_this_week_day(0, 0).date(), 9)
        assert _FakeDialog.instances == []               # no dialog opened, no crash

    def test_dialog_added_wired_to_on_created(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.calendar_week_panel as mod
        _FakeDialog.instances.clear()
        monkeypatch.setattr(mod, "QuickTodoDialog", _FakeDialog)
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store, settings=_FakeSettings())
        created: list = []
        monkeypatch.setattr(panel, "_on_created", created.append)
        panel._handle_slot_click(_this_week_day(0, 0).date(), 9)
        t = Todo(title="From dialog", due=_this_week_day(0, 9))
        _FakeDialog.instances[0].added.emit(t)
        assert created == [t]

    def test_on_created_in_week_renders_and_emits_wrote(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store, settings=_FakeSettings())
        anchor_before = panel._anchor
        wrote: list[int] = []
        panel.wrote.connect(lambda: wrote.append(1))
        t = store.add(Todo(title="New here", due=_this_week_day(4, 13)))   # Fri, in shown week
        panel._on_created(t)
        assert panel._anchor == anchor_before              # in-week: anchor unchanged
        assert wrote == [1]
        # the new event renders in its (day, hour) cell
        assert [e.title for e in panel._grid.cells[(_this_week_day(4, 13).date(), 13)]] == ["New here"]

    def test_on_created_out_of_week_moves_anchor_and_renders(self, qapp, tmp_path):
        from serenity.core.calview import _week_start
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store, settings=_FakeSettings())
        far_due = _this_week_day(0, 10) + timedelta(days=21)   # three weeks out
        t = store.add(Todo(title="Far away", due=far_due))
        wrote: list[int] = []
        panel.wrote.connect(lambda: wrote.append(1))
        panel._on_created(t)                                   # H8: re-anchor to the todo's week
        assert _week_start(panel._anchor) == _week_start(far_due.date())
        assert [e.title for e in panel._grid.cells[(far_due.date(), 10)]] == ["Far away"]
        assert wrote == [1]
