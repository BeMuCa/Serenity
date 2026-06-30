import re
from datetime import datetime, timezone
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

def test_parse_floating_is_verbatim_local():
    dt, all_day = ics._parse_dt("20260630T170000", {})
    assert dt == datetime(2026, 6, 30, 17, 0) and all_day is False and dt.tzinfo is None

def test_parse_value_date_is_midnight_allday():
    dt, all_day = ics._parse_dt("20260630", {"VALUE": "DATE"})
    assert dt == datetime(2026, 6, 30, 0, 0) and all_day is True

def test_parse_utc_Z_converts_to_local_naive():
    # 15:00Z -> local wall clock for the test machine
    expected = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    dt, all_day = ics._parse_dt("20260630T150000Z", {})
    assert dt == expected and dt.tzinfo is None and all_day is False

def test_parse_bad_tzid_raises():
    import pytest
    with pytest.raises(Exception):
        ics._parse_dt("20260630T150000", {"TZID": "Mars/Phobos"})


def _wrap(*vevents):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(vevents) + "END:VCALENDAR\r\n"

def test_parse_basic_event():
    txt = _wrap("BEGIN:VEVENT\r\nUID:u1\r\nDTSTART:20260630T170000\r\nSUMMARY:Hi\r\nEND:VEVENT\r\n")
    pc = ics.parse_ics(txt)
    assert pc.is_calendar and len(pc.events) == 1
    e = pc.events[0]
    assert (e.uid, e.title, e.when, e.all_day) == ("u1", "Hi", datetime(2026, 6, 30, 17, 0), False)

def test_parse_missing_vcalendar_sets_is_calendar_false():
    pc = ics.parse_ics("just some text\r\nnot a calendar")
    assert pc.is_calendar is False and pc.events == []

def test_parse_malformed_event_skipped_with_reason():
    txt = _wrap("BEGIN:VEVENT\r\nUID:u2\r\nSUMMARY:NoDate\r\nEND:VEVENT\r\n")  # no DTSTART
    pc = ics.parse_ics(txt)
    assert pc.events == [] and pc.skipped and pc.skipped[0][0] == "NoDate"

def test_parse_unterminated_event_skipped():
    txt = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u3\r\nDTSTART:20260630T170000\r\nSUMMARY:Cut"
    pc = ics.parse_ics(txt)
    assert pc.events == [] and pc.skipped

def test_parse_rrule_imports_first_and_notes_skip():
    txt = _wrap("BEGIN:VEVENT\r\nUID:u4\r\nDTSTART:20260630T170000\r\nRRULE:FREQ=WEEKLY\r\nSUMMARY:Weekly\r\nEND:VEVENT\r\n")
    pc = ics.parse_ics(txt)
    assert len(pc.events) == 1 and pc.events[0].had_rrule
    assert any("recurring" in why for _, why in pc.skipped)

def test_decode_strips_utf8_bom_and_rejects_binary():
    import pytest
    assert ics.decode_ics_bytes(b"\xef\xbb\xbfBEGIN:VCALENDAR").startswith("BEGIN")
    with pytest.raises(ValueError):
        ics.decode_ics_bytes(b"\xff\x00\x01\x02\x80\x81")


def _pc(events, skipped=None):
    return ics.ParsedCalendar(events=events, skipped=skipped or [], is_calendar=True)

def _ev(uid, title="t", when=None, cat=None):
    return ics.ParsedEvent(uid=uid, title=title, when=when or datetime(2026,6,30,17,0),
                           all_day=False, category=cat, had_rrule=False)

def test_reconcile_new_vs_update_by_uid_or_ics_uid():
    existing = [Todo(id="local1", ics_uid="src@x", title="old", due=datetime(2026,6,1,9,0))]
    plan = ics.reconcile(_pc([_ev("src@x", title="new", when=datetime(2026,6,2,9,0)),
                              _ev("brand-new")]), existing)
    assert len(plan.to_update) == 1 and plan.to_update[0][0].id == "local1"
    assert len(plan.to_create) == 1 and plan.to_create[0].uid == "brand-new"

def test_reconcile_noop_when_nothing_changed():
    existing = [Todo(id="a", title="same", due=datetime(2026,6,30,17,0), category=None)]
    plan = ics.reconcile(_pc([_ev("a", title="same")]), existing)
    assert plan.to_update == [] and plan.to_create == []

def test_reconcile_skips_no_uid_and_dup_uid():
    plan = ics.reconcile(_pc([_ev(None), _ev("dup"), _ev("dup")]), [])
    reasons = [why for _, why in plan.skipped]
    assert any("no UID" in r for r in reasons) and any("duplicate UID" in r for r in reasons)
    assert len(plan.to_create) == 1

def test_reconcile_match_index_is_active_only():
    existing = [Todo(id="gone", title="x", due=datetime(2026,6,1,9,0), deleted=True)]
    plan = ics.reconcile(_pc([_ev("gone", title="resurrect")]), existing)
    assert plan.to_update == [] and len(plan.to_create) == 1   # never mutate trash

def test_reconcile_cross_device_fixpoint():
    a = Todo(id="A1", title="Plan", due=datetime(2026,6,30,17,0))
    # export A -> import to empty B
    planB = ics.reconcile(_pc([_ev("A1", title="Plan")]), [])
    assert len(planB.to_create) == 1
    b = Todo(id="B9", ics_uid="A1", title="Plan", due=datetime(2026,6,30,17,0))
    # export B (UID=ics_uid=A1) -> re-import to A: no-op fixpoint
    planA = ics.reconcile(_pc([_ev("A1", title="Plan")]), [a])
    assert planA.to_update == [] and planA.to_create == []
