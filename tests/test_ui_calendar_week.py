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
