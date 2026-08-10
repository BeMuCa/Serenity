import re
from datetime import datetime, timedelta, timezone
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
    segs = folded.split("\r\n ")
    assert all(len(seg.encode("utf-8")) <= 75 for seg in segs)  # octet-limit per segment
    assert b"".join(seg.encode("utf-8") for seg in segs) == line.encode("utf-8")  # no bytes lost
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

def test_export_dtstamp_is_correct_utc_value():
    # tz-aware now (UTC+2) so the test is host-TZ-independent
    t = Todo(title="x", due=datetime(2026, 6, 30, 8, 0), id="c")
    now = datetime(2026, 6, 30, 9, 0, tzinfo=timezone(timedelta(hours=2)))
    out = ics.todos_to_ics([t], now)
    assert "DTSTAMP:20260630T070000Z" in out      # 09:00 UTC+2 -> 07:00 UTC
    assert "DTSTAMP:20260630T090000Z" not in out  # must NOT emit wall-clock time

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
    assert pc.events == []
    assert len(pc.skipped) == 1
    lbl, why = pc.skipped[0]
    assert lbl == "Cut"                             # SUMMARY-derived label, not "(event #N)"
    assert "unterminated" in why.lower()            # pins the trailing-event skip reason

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


# ---------------------------------------------------------------------------
# Regression tests for criticizer pass
# ---------------------------------------------------------------------------

# Finding 2 [P2]: OverflowError on extreme-year DTSTART must not crash parse_ics
def test_parse_ics_overflow_year_dtstart_z_skipped_not_raised():
    """DTSTART:99991231T235959Z causes OverflowError in astimezone; must be skipped."""
    txt = _wrap(
        "BEGIN:VEVENT\r\n"
        "UID:far-future-z\r\n"
        "DTSTART:99991231T235959Z\r\n"
        "SUMMARY:FarFuture\r\n"
        "END:VEVENT\r\n"
    )
    pc = ics.parse_ics(txt)          # must NOT raise
    assert pc.events == []
    assert any("FarFuture" in lbl or "far" in lbl.lower() or "FarFuture" in why
               for lbl, why in pc.skipped)


def test_parse_ics_overflow_year_dtstart_tzid_skipped_not_raised():
    """DTSTART;TZID=America/New_York:99991231T235959 — TZID variant, same guard."""
    txt = _wrap(
        "BEGIN:VEVENT\r\n"
        "UID:far-future-tzid\r\n"
        "DTSTART;TZID=America/New_York:99991231T235959\r\n"
        "SUMMARY:FarFutureTZID\r\n"
        "END:VEVENT\r\n"
    )
    pc = ics.parse_ics(txt)          # must NOT raise
    assert pc.events == []
    assert pc.skipped                # event must appear in skipped


# Finding 3 [P2]: microsecond fixpoint — no spurious to_update on round-trip
def test_reconcile_microsecond_due_fixpoint():
    """A todo with microseconds on .due must round-trip through export+parse with zero updates."""
    due = datetime(2026, 6, 30, 17, 0, 45, 123456)
    t = Todo(id="micro1", title="Dentist", due=due)
    now = datetime(2026, 6, 30, 9, 0)
    exported = ics.todos_to_ics([t], now)
    parsed = ics.parse_ics(exported)
    plan = ics.reconcile(parsed, [t])
    assert plan.to_update == [], f"spurious update: {plan.to_update}"


# Finding 4 [P3]: ≤1 plan entry per existing todo (duplicate target via id + ics_uid)
def test_reconcile_duplicate_target_only_one_update():
    """One todo matched by two events (via id and ics_uid) must yield exactly one to_update."""
    t = Todo(id="A", ics_uid="B", title="orig", due=datetime(2026, 6, 30, 17, 0))
    ev_a = ics.ParsedEvent(uid="A", title="updated-A", when=datetime(2026, 7, 1, 9, 0),
                           all_day=False, category=None, had_rrule=False)
    ev_b = ics.ParsedEvent(uid="B", title="updated-B", when=datetime(2026, 7, 1, 10, 0),
                           all_day=False, category=None, had_rrule=False)
    plan = ics.reconcile(ics.ParsedCalendar(events=[ev_a, ev_b], skipped=[], is_calendar=True), [t])
    assert len(plan.to_update) == 1, f"expected 1 to_update, got {len(plan.to_update)}"
    # second event must be in skipped (already-claimed target)
    assert any("already" in why.lower() for _, why in plan.skipped)


# ---------------------------------------------------------------------------
# Test-agent pass — new/strengthened tests
# ---------------------------------------------------------------------------

# Test 7 [new]: UTF-16 LE and BE BOM decoding both branches
def test_decode_handles_utf16_le_and_be_bom():
    src = "BEGIN:VCALENDAR"
    le = src.encode("utf-16")                      # platform-native with BOM (typically LE: \xff\xfe)
    assert ics.decode_ics_bytes(le) == src          # full equality pins BOM-stripping
    be = b"\xfe\xff" + src.encode("utf-16-be")
    assert ics.decode_ics_bytes(be) == src


# Test 8 [new]: ValueError from unparseable DTSTART produces skipped entry with reason
def test_parse_ics_unparseable_dtstart_skipped_with_reason():
    txt = _wrap("BEGIN:VEVENT\r\nUID:bad-date\r\nDTSTART:NOTADATE\r\nSUMMARY:Garbled\r\nEND:VEVENT\r\n")
    pc = ics.parse_ics(txt)            # must NOT raise
    assert pc.events == []
    assert any("unparseable" in why.lower() for _, why in pc.skipped)
    assert any(lbl == "Garbled" and "unparseable" in why.lower() for lbl, why in pc.skipped)


# Test 9 [new]: stray END:VEVENT without a matching BEGIN is silently ignored
def test_parse_stray_end_vevent_no_begin_ignored():
    txt = "BEGIN:VCALENDAR\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    pc = ics.parse_ics(txt)
    assert pc.events == []
    assert pc.skipped == []     # no spurious 'no start date' skip entry
    assert pc.is_calendar is True


# Test 10 [new]: CATEGORIES round-trips through export and parse
def test_categories_export_import_roundtrip():
    t = Todo(title="Sync", due=datetime(2026, 6, 30, 17, 0), id="c1", category="meeting")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    assert "CATEGORIES:meeting" in out
    pc = ics.parse_ics(out)
    assert pc.events and pc.events[0].category == "meeting"


# Test 11 [new]: special-character title round-trips through export and parse
def test_special_char_title_export_parse_roundtrip():
    t = Todo(title="a; b, c \\ d", due=datetime(2026, 6, 30, 8, 0), id="x1")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    pc = ics.parse_ics(out)
    assert pc.events and pc.events[0].title == t.title


# Test 20 [new]: category-only change triggers to_update
def test_reconcile_category_only_change_updates():
    existing = [Todo(id="a", title="t", due=datetime(2026, 6, 30, 17, 0), category="Work")]
    plan = ics.reconcile(_pc([_ev("a", cat="Home")]), existing)
    assert len(plan.to_update) == 1
    assert plan.to_update[0][0].id == "a"
    assert plan.to_create == []


# Test 20b [new]: empty string vs None category is treated as equal (no spurious update)
def test_reconcile_empty_vs_none_category_is_noop():
    existing = [Todo(id="b", title="t", due=datetime(2026, 6, 30, 17, 0), category="")]
    plan = ics.reconcile(_pc([_ev("b", cat=None)]), existing)
    assert plan.to_update == []


# Test 21 [new]: title-only change triggers to_update
def test_reconcile_title_only_change_updates():
    existing = [Todo(id="a", title="old", due=datetime(2026, 6, 30, 17, 0), category=None)]
    plan = ics.reconcile(_pc([_ev("a", title="new", when=datetime(2026, 6, 30, 17, 0), cat=None)]),
                         existing)
    assert len(plan.to_update) == 1
    assert plan.to_update[0][0].id == "a"
    assert plan.to_update[0][1].title == "new"
    assert plan.to_create == []


# Test 22 [new]: done todos are excluded from the match index
def test_reconcile_match_index_excludes_done():
    existing = [Todo(id="d", title="x", due=datetime(2026, 6, 1, 9, 0), done=True)]
    plan = ics.reconcile(_pc([_ev("d", title="resurrect", when=datetime(2026, 6, 2, 9, 0))]),
                         existing)
    assert plan.to_update == []
    assert len(plan.to_create) == 1     # treated as brand-new, never re-opens a done todo


# Test 23 [new]: timed event DTEND is one hour later, floating (no Z)
def test_export_timed_event_dtend_is_one_hour():
    t = Todo(title="Standup", due=datetime(2026, 6, 30, 17, 0), id="aaa")
    out = ics.todos_to_ics([t], datetime(2026, 6, 30, 9, 0))
    assert "DTEND:20260630T180000" in out
    assert "DTEND:20260630T180000Z" not in out    # must be floating, not UTC


# Test 24 [new]: bare date without VALUE=DATE param is treated as all-day
def test_parse_bare_date_no_value_param_is_allday():
    dt, all_day = ics._parse_dt("20260630", {})
    assert dt == datetime(2026, 6, 30, 0, 0)
    assert all_day is True
    assert dt.tzinfo is None


# Test 25 [strengthen — new separate test]: lone CR is dropped by _escape_text
def test_escape_text_strips_lone_cr():
    assert ics._escape_text("a\rb") == "ab"           # bare \r dropped


# Test 26 [new]: uppercase \N is treated as newline in _unescape_text
def test_unescape_uppercase_N_is_newline():
    assert ics._unescape_text("a\\Nb") == "a\nb"
    assert ics._unescape_text("line1\\Nline2\\nline3") == "line1\nline2\nline3"


# Test 27 [new]: no-op match still claims the target, preventing a second event from updating it
def test_reconcile_noop_match_still_claims_target():
    t = Todo(id="A", ics_uid="B", title="orig", due=datetime(2026, 6, 30, 17, 0))
    ev_a = ics.ParsedEvent(uid="A", title="orig", when=datetime(2026, 6, 30, 17, 0),
                           all_day=False, category=None, had_rrule=False)   # equal — no-op
    ev_b = ics.ParsedEvent(uid="B", title="changed", when=datetime(2026, 7, 1, 9, 0),
                           all_day=False, category=None, had_rrule=False)   # differs, same todo
    plan = ics.reconcile(ics.ParsedCalendar(events=[ev_a, ev_b], skipped=[], is_calendar=True), [t])
    assert plan.to_update == []
    assert any("already" in why.lower() for _, why in plan.skipped)


# Test 28 [new]: lowercase property names are normalised (RFC 5545 case-insensitive)
def test_parse_lowercase_property_names():
    txt = _wrap("BEGIN:VEVENT\r\nuid:low\r\ndtstart:20260630T170000\r\nsummary:Lo\r\nEND:VEVENT\r\n")
    pc = ics.parse_ics(txt)
    assert pc.is_calendar and len(pc.events) == 1
    e = pc.events[0]
    assert e.uid == "low" and e.title == "Lo"
    assert e.when == datetime(2026, 6, 30, 17, 0) and e.all_day is False
