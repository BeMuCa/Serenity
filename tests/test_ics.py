import re
from datetime import datetime
from serenity.core import ics
from serenity.core.models import Todo

def test_escape_unescape_roundtrip():
    s = 'Meet; plan A, B \\ done\nline2'
    esc = ics._escape_text(s)
    assert ";" not in esc.replace("\\;", "") and "\\n" in esc
    assert ics._unescape_text(esc) == s.replace("\r", "")

def test_fold_respects_75_octets_and_unfolds_clean():
    line = "SUMMARY:" + "x" * 200
    folded = ics._fold(line)
    assert all(len(seg.encode()) <= 75 for seg in folded.split("\r\n"))
    assert ics._unfold(folded) == line

def test_fold_never_splits_a_multibyte_char():
    line = "SUMMARY:" + "ü" * 60          # 2 bytes each
    folded = ics._fold(line)
    for seg in folded.split("\r\n "):
        seg.encode("utf-8")               # must not raise / be valid utf-8
    assert ics._unfold(folded) == line

def test_export_timed_event_is_floating_local_no_Z():
    t = Todo(title="Standup", due=datetime(2026, 6, 30, 17, 0), id="aaa")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    assert "BEGIN:VCALENDAR" in out and "END:VCALENDAR" in out
    assert "DTSTART:20260630T170000" in out          # floating, NO trailing Z
    assert "DTSTART:20260630T170000Z" not in out
    assert "UID:aaa" in out and "SUMMARY:Standup" in out

def test_export_all_day_uses_value_date():
    t = Todo(title="Holiday", due=datetime(2026, 6, 30, 0, 0), id="bbb")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    assert "DTSTART;VALUE=DATE:20260630" in out
    assert "DTEND;VALUE=DATE:20260701" in out

def test_export_uid_prefers_ics_uid_and_escapes_summary():
    t = Todo(title="a; b, c", due=datetime(2026, 6, 30, 8, 0), id="local1", ics_uid="src@x")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    assert "UID:src@x" in out
    assert "SUMMARY:a\\; b\\, c" in out

def test_export_dtstamp_is_utc_Z():
    t = Todo(title="x", due=datetime(2026, 6, 30, 8, 0), id="c")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    assert re.search(r"DTSTAMP:\d{8}T\d{6}Z", out)
