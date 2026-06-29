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
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.models import Todo  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.calendar_week_panel import CalendarWeekPanel  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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
        titles = panel._active_titles()
        assert "Open one" in titles
        assert "Done one" not in titles
        assert "Trashed one" not in titles

    def test_refresh_picks_up_a_new_todo(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        panel = CalendarWeekPanel(store)
        assert "Later" not in panel._active_titles()
        store.add(Todo(title="Later", due=_this_week_day(3, 11)))
        panel.refresh()
        assert "Later" in panel._active_titles()

    def test_on_panel_activated_refreshes(self, qapp, tmp_path, monkeypatch):
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        calls: list[int] = []
        monkeypatch.setattr(panel, "refresh", lambda: calls.append(1))
        panel.on_panel_activated()
        assert calls == [1]

    def test_handle_close_is_true(self, qapp, tmp_path):
        panel = CalendarWeekPanel(TodoStore(tmp_path))
        assert panel.handle_close() is True
