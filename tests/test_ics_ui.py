"""
============================================================
Author:  Berk
Created: 2026-06-30
Purpose: Tests for CalendarView ICS export button + handler.
Role:    UI-layer headless tests; monkeypatches QFileDialog and QMessageBox
         so no real dialogs open during CI.

Test classes:
- test_export_writes_file — happy path: file written, contains VCALENDAR
- test_export_empty_set_warns_and_writes_nothing — guard: no dialog if no exportable todos
- test_export_forces_ics_suffix — suffix guard: .ics appended when missing
============================================================
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from datetime import datetime
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from serenity.core.todo_store import TodoStore
from serenity.core.models import Todo
from serenity.ui.calendar_view import CalendarView

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def _store(tmp_path, todos):
    s = TodoStore(tmp_path)
    for t in todos:
        s.add(t)
    return s

def test_export_writes_file(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [Todo(title="A", due=datetime(2026,6,30,17,0))])
    v = CalendarView(s)
    out = tmp_path / "cal.ics"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    v._export_ics()
    assert out.exists() and "BEGIN:VCALENDAR" in out.read_text()

def test_export_empty_set_warns_and_writes_nothing(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [Todo(title="no-due")])          # active but no due date
    v = CalendarView(s)
    called = {"save": False}
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: called.__setitem__("save", True) or ("", ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    v._export_ics()
    assert called["save"] is False                        # returned before the dialog

def test_export_forces_ics_suffix(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [Todo(title="A", due=datetime(2026,6,30,17,0))])
    v = CalendarView(s)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path/"noext"), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    v._export_ics()
    assert (tmp_path / "noext.ics").exists()


# ---------------------------------------------------------------------------
# ImportPreviewDialog tests
# ---------------------------------------------------------------------------
from serenity.ui.ics_import_dialog import ImportPreviewDialog
from serenity.core import ics

def _ev(uid, title="t", cat=None, recur=False):
    from datetime import datetime
    return ics.ParsedEvent(uid=uid, title=title, when=datetime(2026,6,30,17,0),
                           all_day=False, category=cat, had_rrule=recur)

def test_preview_shows_counts(app):
    plan = ics.ImportPlan(to_create=[_ev("a"), _ev("b")],
                          to_update=[(Todo(id="x", title="old"), _ev("x", title="new"))],
                          skipped=[("z", "no UID — cannot dedup")])
    dlg = ImportPreviewDialog(plan)
    txt = dlg.summary_text()
    assert "2 new" in txt and "1 update" in txt and "1 skipped" in txt

def test_preview_caps_rows(app):
    plan = ics.ImportPlan(to_create=[_ev(str(i)) for i in range(50)], to_update=[], skipped=[])
    dlg = ImportPreviewDialog(plan)
    assert dlg.rendered_create_rows() <= 20      # cap
