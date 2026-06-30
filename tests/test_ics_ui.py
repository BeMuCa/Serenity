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


# ---------------------------------------------------------------------------
# Regression tests for criticizer pass
# ---------------------------------------------------------------------------

# Finding 1 [P2]: _apply_import must NOT mutate done/deleted todos
def test_apply_import_does_not_mutate_deleted_todo(app, tmp_path):
    """A to_create event whose UID matches a deleted todo must create a NEW todo, not mutate trash."""
    deleted = Todo(id="gone", ics_uid="gone", title="OldTitle",
                   due=datetime(2026, 6, 1, 9, 0), deleted=True)
    done = Todo(id="done1", ics_uid="done1", title="DoneTitle",
                due=datetime(2026, 6, 1, 10, 0), done=True)
    s = _store(tmp_path, [deleted, done])
    v = CalendarView(s)

    # Manually build a plan that says "create" for the UIDs matching deleted/done
    ev_deleted = icscore.ParsedEvent(uid="gone", title="Resurrected",
                                     when=datetime(2026, 7, 1, 9, 0),
                                     all_day=False, category=None, had_rrule=False)
    ev_done = icscore.ParsedEvent(uid="done1", title="AlsoResurrected",
                                  when=datetime(2026, 7, 1, 10, 0),
                                  all_day=False, category=None, had_rrule=False)
    plan = icscore.ImportPlan(to_create=[ev_deleted, ev_done], to_update=[], skipped=[])
    v._apply_import(plan)

    all_todos = s.all()
    # The original deleted/done todos must be unchanged
    orig_deleted = next(t for t in all_todos if t.id == "gone")
    assert orig_deleted.title == "OldTitle", "deleted todo title was mutated"
    assert orig_deleted.deleted is True, "deleted todo no longer marked deleted"

    orig_done = next(t for t in all_todos if t.id == "done1")
    assert orig_done.title == "DoneTitle", "done todo title was mutated"
    assert orig_done.done is True, "done todo no longer marked done"

    # Two NEW active todos must exist
    new_todos = [t for t in all_todos if not t.deleted and not t.done]
    assert len(new_todos) == 2, f"expected 2 new active todos, got {len(new_todos)}"
    new_titles = {t.title for t in new_todos}
    assert "Resurrected" in new_titles
    assert "AlsoResurrected" in new_titles


# Finding 5 [P3]: QLabel rows for file-sourced strings must use PlainText format
def test_preview_row_labels_use_plain_text(app):
    """Row QLabels must have Qt.PlainText text format to prevent markup injection."""
    from PySide6.QtCore import Qt
    plan = icscore.ImportPlan(
        to_create=[_ev("a", title="<b>bold</b>")],
        to_update=[(Todo(id="x", title="old", due=datetime(2026, 6, 30, 17, 0)),
                    _ev("x", title="<a href='evil'>click</a>"))],
        skipped=[("<script>alert(1)</script>", "some reason")],
    )
    dlg = ImportPreviewDialog(plan)
    # Walk children to find all QLabels in the body scroll area
    from PySide6.QtWidgets import QLabel as _QLabel
    labels = dlg.findChildren(_QLabel)
    # Filter to only the row labels that contain file-sourced prefixes
    row_labels = [lbl for lbl in labels
                  if lbl.text().startswith(("+", "~", "–"))]
    assert row_labels, "no row labels found in dialog"
    for lbl in row_labels:
        assert lbl.textFormat() == Qt.PlainText, (
            f"Label '{lbl.text()[:40]}' has textFormat {lbl.textFormat()}, expected Qt.PlainText"
        )


# Finding 6 [P3]: "…and N more" must appear for to_update and skipped sections too
def test_preview_overflow_line_for_update_and_skipped(app):
    """Both to_update and skipped sections must show '…and N more' when > _ROW_CAP items."""
    from serenity.ui.ics_import_dialog import _ROW_CAP
    from PySide6.QtWidgets import QLabel as _QLabel

    big_update = [(Todo(id=str(i), title=f"old{i}", due=datetime(2026, 6, 30, 17, 0)),
                   _ev(str(i), title=f"new{i}")) for i in range(_ROW_CAP + 5)]
    big_skip = [(f"skip{i}", f"reason{i}") for i in range(_ROW_CAP + 3)]

    plan = icscore.ImportPlan(to_create=[], to_update=big_update, skipped=big_skip)
    dlg = ImportPreviewDialog(plan)

    label_texts = [lbl.text() for lbl in dlg.findChildren(_QLabel)]
    overflow_labels = [t for t in label_texts if t.startswith("…and")]
    assert len(overflow_labels) >= 2, (
        f"expected at least 2 '…and N more' labels, got: {overflow_labels}"
    )
    assert any("5 more" in t for t in overflow_labels), "to_update overflow label missing"
    assert any("3 more" in t for t in overflow_labels), "skipped overflow label missing"
