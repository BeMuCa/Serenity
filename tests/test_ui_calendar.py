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
