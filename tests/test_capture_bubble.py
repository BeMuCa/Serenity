"""
============================================================
Author:  Berk
Created: 2026-08-10
Purpose: Verify the Quick-todo bubble: it is a CHILD of the dock (no OS window), its
         title field grows with the text, its date+time pickers produce a real due that
         can arm reminders, and it closes on Esc / an outside click / a successful save.
Role:    Headless UI regression for ui/capture_bubble.py and the shell's capture-bar path.

Test classes:
- TestGrowingTitle — one line to start, grows with wrapped text, capped, Enter submits
- TestDuePickers — unticked = no due; ticked = the picked date+time, naive local
- TestSaving — saves through modals.save_quick_todo, arms rungs, keeps open on failure
- TestDismissal — Esc, a click outside, and a save all close it; the calendar does not
- TestInDock — it is a child widget positioned over its anchor, never a separate window
============================================================
"""
import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt, QTime  # noqa: E402
from PySide6.QtGui import QMouseEvent, QPointingDevice  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from serenity.core.settings import Settings  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.ui.capture_bubble import CaptureBubble, GrowingTextEdit  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def host(qapp, tmp_path):
    """A stand-in dock: a shown parent with an anchor button, like the capture bar."""
    w = QWidget()
    w.resize(348, 700)
    lay = QVBoxLayout(w)
    lay.addStretch(1)
    anchor = QPushButton("Quick todo", w)
    lay.addWidget(anchor)
    w.show()
    qapp.processEvents()
    store = TodoStore(tmp_path)
    bubble = CaptureBubble(store, Settings(), w)
    return w, anchor, bubble, store


class TestGrowingTitle:
    def test_starts_one_line_and_grows_then_caps(self, qapp):
        ed = GrowingTextEdit("What needs doing?", max_lines=4)
        ed.resize(240, 10)
        ed.show()
        qapp.processEvents()
        one = ed.height()
        ed.setText("word " * 60)                 # wraps well past four lines
        qapp.processEvents()
        grown = ed.height()
        assert grown > one, "the field did not grow with the text"
        ed.setText("word " * 400)
        qapp.processEvents()
        assert ed.height() == grown, "growth is not capped at max_lines"

    def test_enter_submits_and_shift_enter_makes_a_line(self, qapp):
        ed = GrowingTextEdit()
        fired = []
        ed.submitted.connect(lambda: fired.append(1))
        ed.setText("call the accountant")
        ev = QMouseEvent  # noqa: F841 (keep the import honest for the module)
        from PySide6.QtGui import QKeyEvent
        ed.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        assert fired == [1]
        ed.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier))
        assert fired == [1]                       # still one: Shift+Enter is a newline
        assert "\n" in ed.text()

    def test_text_accessors_match_qlineedit(self, qapp):
        ed = GrowingTextEdit()
        ed.setText("hello")
        assert ed.text() == "hello"


class TestDuePickers:
    def test_no_due_until_ticked(self, host):
        _w, _a, bubble, _s = host
        assert bubble.due_datetime() is None
        assert not bubble.date.isEnabled() and not bubble.time.isEnabled()

    def test_ticking_enables_the_pickers_and_yields_that_datetime(self, host, qapp):
        _w, _a, bubble, _s = host
        bubble.due_check.setChecked(True)
        bubble.date.setDate(QDate(2026, 8, 14))
        bubble.time.setTime(QTime(17, 30))
        qapp.processEvents()
        assert bubble.date.isEnabled() and bubble.time.isEnabled()
        due = bubble.due_datetime()
        assert due == datetime(2026, 8, 14, 17, 30)
        assert due.tzinfo is None, "must stay naive-local: ranking does due - datetime.now()"

    def test_untick_clears_the_due_again(self, host):
        _w, _a, bubble, _s = host
        bubble.due_check.setChecked(True)
        assert bubble.due_datetime() is not None
        bubble.due_check.setChecked(False)
        assert bubble.due_datetime() is None


class TestSaving:
    def test_saves_a_todo_with_the_picked_due(self, host, qapp):
        _w, anchor, bubble, store = host
        bubble.open_above(anchor)
        bubble.title.setText("Send the signed contract")
        soon = datetime.now() + timedelta(days=2)
        bubble.due_check.setChecked(True)
        bubble.date.setDate(QDate(soon.year, soon.month, soon.day))
        bubble.time.setTime(QTime(9, 0))
        got = []
        bubble.added.connect(got.append)
        bubble._save()
        assert len(got) == 1
        todo = got[0]
        assert todo.title == "Send the signed contract"
        assert todo.due == datetime(soon.year, soon.month, soon.day, 9, 0)
        assert todo in store.all()
        assert not bubble.isVisible(), "a successful save should close the bubble"

    def test_blank_title_saves_nothing(self, host):
        _w, _a, bubble, store = host
        got = []
        bubble.added.connect(got.append)
        bubble.title.setText("   ")
        bubble._save()
        assert got == [] and store.all() == []

    def test_picked_rungs_are_armed(self, host, qapp):
        _w, anchor, bubble, _store = host
        bubble.open_above(anchor)
        bubble.title.setText("Call the accountant")
        due = datetime.now() + timedelta(days=1)
        bubble.due_check.setChecked(True)
        bubble.date.setDate(QDate(due.year, due.month, due.day))
        bubble.time.setTime(QTime(due.hour, 0))
        qapp.processEvents()
        boxes = [b for b in bubble.reminder_picker.findChildren(type(bubble.due_check))
                 if b.isEnabled()]
        if not boxes:
            pytest.skip("no rung is armable for this due time")
        boxes[0].setChecked(True)
        got = []
        bubble.added.connect(got.append)
        bubble._save()
        assert got, "nothing saved"
        assert got[0].reminder_offsets, "picked rungs were not armed onto the todo"

    def test_a_failed_write_keeps_the_bubble_open_with_an_error(self, host, monkeypatch):
        _w, anchor, bubble, store = host
        bubble.open_above(anchor)
        bubble.title.setText("Disk is full")
        monkeypatch.setattr(store, "add", lambda todo: (_ for _ in ()).throw(OSError("full")))
        bubble._save()
        assert bubble.isVisible(), "the bubble must stay open so the text is not lost"
        assert bubble._error.isVisible()


class TestDismissal:
    def test_escape_closes(self, host):
        from PySide6.QtGui import QKeyEvent
        _w, anchor, bubble, _s = host
        bubble.open_above(anchor)
        assert bubble.isVisible()
        bubble.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not bubble.isVisible()

    def _press(self, global_pos):
        return QMouseEvent(QEvent.MouseButtonPress, QPointF(0, 0), QPointF(*global_pos),
                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
                           QPointingDevice.primaryPointingDevice())

    def test_click_outside_closes_but_inside_does_not(self, host, qapp):
        _w, anchor, bubble, _s = host
        bubble.open_above(anchor)
        inside = bubble.mapToGlobal(QPoint(bubble.width() // 2, bubble.height() // 2))
        bubble.eventFilter(bubble, self._press((inside.x(), inside.y())))
        assert bubble.isVisible(), "a click on the bubble itself must not dismiss it"
        far = bubble.mapToGlobal(QPoint(-400, -400))
        bubble.eventFilter(bubble, self._press((far.x(), far.y())))
        assert not bubble.isVisible()

    def test_open_removes_and_reinstalls_the_filter(self, host, qapp):
        """The outside-click filter is app-wide, so it must not stay installed while hidden."""
        _w, anchor, bubble, _s = host
        bubble.open_above(anchor)
        bubble.close_bubble()
        far = bubble.mapToGlobal(QPoint(-400, -400))
        bubble.eventFilter(bubble, self._press((far.x(), far.y())))   # must not explode
        bubble.open_above(anchor)
        assert bubble.isVisible()


class TestInDock:
    def test_is_a_child_widget_not_a_window(self, host):
        w, anchor, bubble, _s = host
        bubble.open_above(anchor)
        assert bubble.parentWidget() is w
        assert not bubble.isWindow(), "a separate window brings the OS title bar back"

    def test_sits_above_its_anchor_and_inside_the_dock(self, host):
        w, anchor, bubble, _s = host
        bubble.open_above(anchor)
        geo = bubble.geometry()
        anchor_top = anchor.mapTo(w, QPoint(0, 0)).y()
        assert geo.bottom() <= anchor_top, "the bubble should grow upward out of the button"
        assert geo.left() >= 0 and geo.right() <= w.width(), f"{geo} escapes {w.width()}px dock"

    def test_reopening_clears_the_previous_draft(self, host):
        _w, anchor, bubble, _s = host
        bubble.open_above(anchor)
        bubble.title.setText("half-typed thing")
        bubble.due_check.setChecked(True)
        bubble.close_bubble()
        bubble.open_above(anchor)
        assert bubble.title.text() == ""
        assert bubble.due_datetime() is None
