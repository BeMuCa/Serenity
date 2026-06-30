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


# ---------------------------------------------------------------------------
# _import_ics handler tests (Task 9)
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QDialog
from serenity.ui import ics_import_dialog
from serenity.core import ics as icscore


def _write_ics(tmp_path, body):
    p = tmp_path / "in.ics"
    p.write_text("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + body + "END:VCALENDAR\r\n")
    return p


def test_import_creates_todos_and_emits_wrote(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [])
    v = CalendarView(s)
    fired = {"n": 0}; v.wrote.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
    p = _write_ics(tmp_path, "BEGIN:VEVENT\r\nUID:u1\r\nDTSTART:20260630T170000\r\nSUMMARY:Imported\r\nEND:VEVENT\r\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    monkeypatch.setattr(ics_import_dialog.ImportPreviewDialog, "exec", lambda self: QDialog.Accepted)
    v._import_ics()
    titles = [t.title for t in s.all()]
    assert "Imported" in titles and fired["n"] == 1
    assert s.all()[[t.title for t in s.all()].index("Imported")].ics_uid == "u1"


def test_import_cancel_writes_nothing(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [])
    v = CalendarView(s)
    p = _write_ics(tmp_path, "BEGIN:VEVENT\r\nUID:u1\r\nDTSTART:20260630T170000\r\nSUMMARY:X\r\nEND:VEVENT\r\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    monkeypatch.setattr(ics_import_dialog.ImportPreviewDialog, "exec", lambda self: QDialog.Rejected)
    v._import_ics()
    assert s.all() == []


def test_import_zero_importable_shows_info_not_dialog(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [])
    v = CalendarView(s)
    p = _write_ics(tmp_path, "BEGIN:VEVENT\r\nDTSTART:20260630T170000\r\nSUMMARY:NoUID\r\nEND:VEVENT\r\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    seen = {"info": False, "dlg": False}
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.__setitem__("info", True))
    monkeypatch.setattr(ics_import_dialog.ImportPreviewDialog, "exec",
                        lambda self: seen.__setitem__("dlg", True) or QDialog.Rejected)
    v._import_ics()
    assert seen["info"] is True and seen["dlg"] is False


def test_import_oversize_rejected_before_read(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [])
    v = CalendarView(s)
    p = _write_ics(tmp_path, "")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    monkeypatch.setattr("serenity.ui.calendar_view.ICS_MAX_BYTES", 1)
    warned = {"w": False}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.__setitem__("w", True))
    v._import_ics()
    assert warned["w"] is True


def test_import_save_failure_rolls_back(app, tmp_path, monkeypatch):
    s = _store(tmp_path, [])
    v = CalendarView(s)
    p = _write_ics(tmp_path, "BEGIN:VEVENT\r\nUID:u1\r\nDTSTART:20260630T170000\r\nSUMMARY:X\r\nEND:VEVENT\r\n")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(p), ""))
    monkeypatch.setattr(ics_import_dialog.ImportPreviewDialog, "exec", lambda self: QDialog.Accepted)
    def boom(): raise OSError("disk full")
    monkeypatch.setattr(s, "save", boom)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    v._import_ics()
    assert [t.title for t in s.all()] == []          # rolled back (reload dropped in-mem create)
