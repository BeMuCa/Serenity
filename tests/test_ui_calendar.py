"""
============================================================
Author:  Berk
Created: 2026-06-25
Purpose: Headless smoke tests for the Calendar tab view (ui.calendar_view).
Role:    Under QT_QPA_PLATFORM=offscreen, assert CalendarView builds + refresh() renders for
         empty and populated stores, and that day-click / month-toggle / nav / show-done do
         not raise. Pure layout logic is covered by tests/test_calview.py.

Test classes:
- TestCalendarView - builds, renders week grid + event list, day filter, controls
============================================================
"""
import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.models import Todo  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.calendar_view import CalendarView  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class TestCalendarView:
    def test_builds_empty(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        view.refresh()  # must not raise on an empty store

    def test_renders_with_a_dated_todo(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Dentist", due=datetime.now().replace(hour=14, minute=0)))
        view = CalendarView(store)
        view.refresh()  # must not raise; the event is in this week

    def test_day_click_filters_without_raising(self, qapp, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="Dentist", due=datetime.now().replace(hour=14, minute=0)))
        view = CalendarView(store)
        view._on_day_clicked(datetime.now().date())  # select a day -> filter
        view._on_day_clicked(datetime.now().date())  # click again -> clear filter


class TestCalendarControls:
    def test_month_toggle_then_back_to_week(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        view._toggle_mode()
        assert view._mode == "month"
        view._toggle_mode()
        assert view._mode == "week"

    def test_prev_next_today_week(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        start = view._anchor
        view._go_next()
        assert (view._anchor - start).days == 7
        view._go_prev()
        assert view._anchor == start
        view._go_next()
        view._go_today()
        assert view._anchor == datetime.now().date()

    def test_prev_next_month(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        view._toggle_mode()  # month
        m0 = view._anchor.month
        view._go_next()
        assert view._anchor.month == (m0 % 12) + 1

    def test_show_done_toggle_changes_state(self, qapp, tmp_path):
        view = CalendarView(TodoStore(tmp_path))
        assert view._show_done is False
        view._toggle_done(True)
        assert view._show_done is True
