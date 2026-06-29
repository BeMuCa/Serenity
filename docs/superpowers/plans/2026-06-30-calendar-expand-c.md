# Calendar-expand slice (c) — ICS round-trip — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Round-trip Serenity todos through `.ics` — export active-with-due todos, import external `.ics` into todos with UID-based dedup — entirely hand-rolled, no new dependencies.

**Architecture:** All format + reconcile logic in a new pure `serenity/core/ics.py` (Qt-free, headless-tested): `todos_to_ics`, `parse_ics`, `reconcile`, plus escape/fold/datetime/decode helpers. The UI (`ui/calendar_view.py` two toolbar buttons + a new `ui/ics_import_dialog.py` preview) only drives `QFileDialog`/`QMessageBox`, calls the pure functions, and applies the plan to `TodoStore` transactionally. A new optional `Todo.ics_uid` field anchors cross-device identity.

**Tech Stack:** Python 3.12, PySide6, stdlib `zoneinfo`/`datetime`. Tests with pytest, `QT_QPA_PLATFORM=offscreen`.

## Global Constraints

- **No new dependencies.** stdlib only (`zoneinfo`, `datetime`, `re`, `os`, `pathlib`).
- **`Todo.due` is a naive datetime in LOCAL wall-clock time** — never attach/convert to UTC for storage. Timed export = floating (no `Z`, no `TZID`); import normalizes any foreign `Z`/`TZID` to naive **local**.
- **All `core/` code is Qt-free** and passes headless with NO extras installed.
- Run the suite with `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (plain `python` is not on PATH).
- Every new `.py` file starts with the project header-comment block (Author: Berk, Created: 2026-06-30, Purpose, Role, Functions/Classes).
- The full suite must stay green at every task's final step (was 936 passed / 5 skipped before this slice).
- RFC 5545: TEXT-escape `\ ; ,` + newline; fold content lines to ≤75 octets (UTF-8 bytes), continuation = `CRLF` + single space.

---

### Task 1: `Todo.ics_uid` field

**Files:**
- Modify: `serenity/core/models.py:61-142` (Todo dataclass + to_dict + from_dict)
- Test: `tests/test_models.py` (append; create if absent)

**Interfaces:**
- Produces: `Todo.ics_uid: Optional[str] = None`; serialized as `"ics_uid"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from serenity.core.models import Todo

def test_ics_uid_roundtrips_and_defaults_none():
    assert Todo().ics_uid is None
    t = Todo(title="x", ics_uid="abc@serenity")
    assert Todo.from_dict(t.to_dict()).ics_uid == "abc@serenity"

def test_ics_uid_missing_in_old_doc_loads_none():
    d = Todo(title="legacy").to_dict()
    d.pop("ics_uid", None)            # simulate a pre-field todos.json
    assert Todo.from_dict(d).ics_uid is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_models.py -q`
Expected: FAIL (`TypeError: ... unexpected keyword argument 'ics_uid'`).

- [ ] **Step 3: Implement**

In `serenity/core/models.py`, add the field after `updated` (line 80):
```python
    ics_uid: Optional[str] = None        # source UID for ICS round-trip dedup (cross-device)
```
In `to_dict` (after the `"updated"` entry):
```python
            "ics_uid": self.ics_uid,
```
In `from_dict` (after the `updated=` entry):
```python
            ics_uid=d.get("ics_uid"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_models.py -q` → PASS

- [ ] **Step 5: Run the full suite, then commit**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → all green
```bash
git add serenity/core/models.py tests/test_models.py
git commit -m "feat(models): add Todo.ics_uid for ICS round-trip dedup"
```

---

### Task 2: `core/ics.py` — TEXT escape/unescape + line fold/unfold

**Files:**
- Create: `serenity/core/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Produces: `_escape_text(str)->str`, `_unescape_text(str)->str`, `_fold(str)->str`, `_unfold(str)->str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics.py
from serenity.core import ics

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
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ics.py -q`
Expected: FAIL (`ModuleNotFoundError` / `AttributeError`).

- [ ] **Step 3: Implement**

Create `serenity/core/ics.py` with the header block, then:
```python
import re

def _escape_text(value: str) -> str:
    return (value.replace("\\", "\\\\")
                 .replace(";", "\\;")
                 .replace(",", "\\,")
                 .replace("\r\n", "\n").replace("\r", "").replace("\n", "\\n"))

def _unescape_text(value: str) -> str:
    out, i = [], 0
    repl = {"n": "\n", "N": "\n", ";": ";", ",": ",", "\\": "\\"}
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            out.append(repl.get(value[i + 1], value[i + 1])); i += 2
        else:
            out.append(c); i += 1
    return "".join(out)

def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    segs, start, limit = [], 0, 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        while end < len(raw) and (raw[end] & 0xC0) == 0x80:   # don't split a utf-8 char
            end -= 1
        segs.append(raw[start:end].decode("utf-8"))
        start, limit = end, 74                                # continuation lines lead with a space
    return "\r\n ".join(segs)

def _unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add serenity/core/ics.py tests/test_ics.py
git commit -m "feat(ics): RFC-5545 TEXT escape + 75-octet line folding helpers"
```

---

### Task 3: `core/ics.py` — `todos_to_ics`

**Files:**
- Modify: `serenity/core/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Consumes: `_escape_text`, `_fold` (Task 2); `calview._has_time`; `Todo`.
- Produces: `todos_to_ics(todos: list[Todo], now: datetime) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics.py (append)
from datetime import datetime
from serenity.core.models import Todo

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
```

- [ ] **Step 2: Run to verify it fails** → FAIL (`AttributeError: todos_to_ics`).

- [ ] **Step 3: Implement**

Add to `serenity/core/ics.py`:
```python
from datetime import datetime, timedelta, timezone
from .calview import _has_time

def todos_to_ics(todos, now):
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Serenity//Calendar//EN"]
    for t in todos:
        all_day = not _has_time(t.due)
        lines.append("BEGIN:VEVENT")
        lines.append(_fold(f"UID:{t.ics_uid or t.id}"))
        lines.append(f"DTSTAMP:{stamp}")
        if all_day:
            lines.append(f"DTSTART;VALUE=DATE:{t.due.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(t.due + timedelta(days=1)).strftime('%Y%m%d')}")
        else:
            lines.append(f"DTSTART:{t.due.strftime('%Y%m%dT%H%M%S')}")
            lines.append(f"DTEND:{(t.due + timedelta(hours=1)).strftime('%Y%m%dT%H%M%S')}")
        lines.append(_fold(f"SUMMARY:{_escape_text(t.title)}"))
        if t.category:
            lines.append(_fold(f"CATEGORIES:{_escape_text(t.category)}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Run full suite + commit**

```bash
git add serenity/core/ics.py tests/test_ics.py
git commit -m "feat(ics): todos_to_ics export (floating-local timed, VALUE=DATE all-day, UTC DTSTAMP)"
```

---

### Task 4: `core/ics.py` — `_parse_dt` (wire → naive local)

**Files:**
- Modify: `serenity/core/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Produces: `_parse_dt(value: str, params: dict) -> tuple[datetime, bool]` (returns naive-local datetime + all_day). Raises `ValueError`/`KeyError`/`ZoneInfoNotFoundError` on bad input.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics.py (append)
from datetime import datetime, timezone

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
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement**

Add to `serenity/core/ics.py`:
```python
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def _parse_dt(value, params):
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        return datetime.strptime(value, "%Y%m%d"), True
    if value.endswith("Z"):
        dt = datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None), False
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        aware = naive.replace(tzinfo=ZoneInfo(tzid))      # raises ZoneInfoNotFoundError on bad zone
        return aware.astimezone().replace(tzinfo=None), False
    return naive, False                                    # floating -> verbatim local
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add serenity/core/ics.py tests/test_ics.py
git commit -m "feat(ics): _parse_dt normalizes wire datetimes to naive-local"
```

---

### Task 5: `core/ics.py` — `parse_ics` + `decode_ics_bytes`

**Files:**
- Modify: `serenity/core/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Consumes: `_unfold`, `_unescape_text` (Task 2), `_parse_dt` (Task 4).
- Produces:
  - `ParsedEvent(uid: str|None, title: str, when: datetime, all_day: bool, category: str|None, had_rrule: bool)` (dataclass)
  - `ParsedCalendar(events: list[ParsedEvent], skipped: list[tuple[str,str]], is_calendar: bool)` (dataclass)
  - `parse_ics(text: str) -> ParsedCalendar`
  - `decode_ics_bytes(raw: bytes) -> str` (raises `ValueError` on undecodable)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics.py (append)
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
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement**

Add to `serenity/core/ics.py`:
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ParsedEvent:
    uid: Optional[str]
    title: str
    when: datetime
    all_day: bool
    category: Optional[str]
    had_rrule: bool

@dataclass
class ParsedCalendar:
    events: list
    skipped: list
    is_calendar: bool

def decode_ics_bytes(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")           # Outlook UTF-16
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return raw.decode("utf-8")                # UnicodeDecodeError (a ValueError) on binary

def _parse_prop(line):
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value

def _build_event(cur, idx):
    label = _unescape_text(cur["SUMMARY"][1]) if "SUMMARY" in cur else f"(event #{idx})"
    if "DTSTART" not in cur:
        return None, label, "no start date"
    params, value = cur["DTSTART"]
    try:
        when, all_day = _parse_dt(value, params)
    except (ValueError, KeyError, ZoneInfoNotFoundError):
        return None, label, "unparseable date/timezone"
    ev = ParsedEvent(
        uid=cur["UID"][1].strip() if "UID" in cur else None,
        title=_unescape_text(cur["SUMMARY"][1]) if "SUMMARY" in cur else "",
        when=when, all_day=all_day,
        category=_unescape_text(cur["CATEGORIES"][1]) if "CATEGORIES" in cur else None,
        had_rrule="RRULE" in cur,
    )
    return ev, label, None

def parse_ics(text: str) -> ParsedCalendar:
    lines = _unfold(text).replace("\r\n", "\n").split("\n")
    up = [ln.strip().upper() for ln in lines]
    is_calendar = "BEGIN:VCALENDAR" in up and "END:VCALENDAR" in up
    events, skipped, in_event, cur, idx = [], [], False, {}, 0
    for ln in lines:
        s = ln.strip()
        u = s.upper()
        if u == "BEGIN:VEVENT":
            in_event, cur, idx = True, {}, idx + 1
        elif u == "END:VEVENT":
            if in_event:
                ev, label, reason = _build_event(cur, idx)
                if ev:
                    events.append(ev)
                    if ev.had_rrule:
                        skipped.append((label, "recurring event — only the first occurrence imported"))
                else:
                    skipped.append((label, reason))
            in_event = False
        elif in_event:
            prop = _parse_prop(s)
            if prop:
                cur[prop[0]] = (prop[1], prop[2])
    if in_event:                                   # unterminated trailing event
        label = _unescape_text(cur["SUMMARY"][1]) if "SUMMARY" in cur else f"(event #{idx})"
        skipped.append((label, "unterminated event (truncated file)"))
    return ParsedCalendar(events=events, skipped=skipped, is_calendar=is_calendar)
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Run full suite + commit**

```bash
git add serenity/core/ics.py tests/test_ics.py
git commit -m "feat(ics): defensive parse_ics + decode_ics_bytes (envelope/skip/RRULE/BOM)"
```

---

### Task 6: `core/ics.py` — `reconcile`

**Files:**
- Modify: `serenity/core/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Consumes: `ParsedCalendar`/`ParsedEvent` (Task 5), `Todo` + `ics_uid` (Task 1).
- Produces: `ImportPlan(to_create: list[ParsedEvent], to_update: list[tuple[Todo, ParsedEvent]], skipped: list[tuple[str,str]])`; `reconcile(parsed, existing_todos) -> ImportPlan`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics.py (append)
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
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement**

Add to `serenity/core/ics.py`:
```python
@dataclass
class ImportPlan:
    to_create: list
    to_update: list
    skipped: list

def _differs(todo, ev) -> bool:
    return (todo.due != ev.when
            or todo.title != ev.title
            or (todo.category or None) != (ev.category or None))

def reconcile(parsed, existing_todos) -> ImportPlan:
    skipped = list(parsed.skipped)
    index = {}
    for t in existing_todos:
        if t.done or t.deleted:
            continue                       # active-only match scope
        index[t.id] = t
        if t.ics_uid:
            index[t.ics_uid] = t
    to_create, to_update, seen = [], [], set()
    for ev in parsed.events:
        if not ev.uid:
            skipped.append((ev.title or "(event)", "no UID — cannot dedup")); continue
        if ev.uid in seen:
            skipped.append((ev.title or "(event)", "duplicate UID in file")); continue
        seen.add(ev.uid)
        match = index.get(ev.uid)
        if match is None:
            to_create.append(ev)
        elif _differs(match, ev):
            to_update.append((match, ev))
        # equal-on-all -> drop (no-op)
    return ImportPlan(to_create=to_create, to_update=to_update, skipped=skipped)
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Run full suite + commit**

```bash
git add serenity/core/ics.py tests/test_ics.py
git commit -m "feat(ics): reconcile (UID dedup, active-only match, fixpoint)"
```

---

### Task 7: Export button + handler (`ui/calendar_view.py`)

**Files:**
- Modify: `serenity/ui/calendar_view.py` (imports; header buttons line 69-86; new `_export_ics`)
- Test: `tests/test_ics_ui.py`

**Interfaces:**
- Consumes: `core.ics.todos_to_ics`, `core.paths.atomic_write_text`.
- Produces: `CalendarView._export_ics(self)`; an `export_btn` in the header.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics_ui.py
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
```

- [ ] **Step 2: Run to verify it fails** → FAIL (`AttributeError: _export_ics`).

- [ ] **Step 3: Implement**

In `serenity/ui/calendar_view.py`: extend the imports —
```python
from pathlib import Path
from PySide6.QtWidgets import (..., QFileDialog, QMessageBox)   # add these two
from ..core.ics import todos_to_ics
from ..core.paths import atomic_write_text
```
In the header block (after `self.expand_btn = ...`, before the `for b in (...)` loop), add:
```python
        self.export_btn = QPushButton("⤓ ICS")
        self.import_btn = QPushButton("⤒ ICS")
```
Add them to the `for b in (...)` objectName loop and `header.addWidget(...)` (place before `expand_btn`). Wire:
```python
        self.export_btn.clicked.connect(self._export_ics)
        self.import_btn.clicked.connect(self._import_ics)   # handler arrives in Task 9
```
Add the method:
```python
    def _export_ics(self):
        exportable = [t for t in self.todo_store.all()
                      if t.due is not None and not t.done and not t.deleted]
        if not exportable:
            QMessageBox.information(self, "Export calendar",
                                    "No active todos with a due date to export.")
            return
        default = f"serenity-calendar-{datetime.now().strftime('%Y-%m-%d')}.ics"
        path, _ = QFileDialog.getSaveFileName(self, "Export calendar", default,
                                              "iCalendar (*.ics)")
        if not path:
            return
        if not path.lower().endswith(".ics"):
            path += ".ics"
        text = todos_to_ics(exportable, datetime.now())
        try:
            atomic_write_text(Path(path), text)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed",
                                f"Could not write the calendar file:\n{exc}")
            return
        QMessageBox.information(self, "Export calendar",
                                f"Exported {len(exportable)} event(s).")
```
> Note: `self.import_btn` is wired now but `_import_ics` lands in Task 9. To keep the suite green between tasks, also add a temporary stub `def _import_ics(self): pass` in THIS task; Task 9 replaces its body.

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Run full suite + commit**

```bash
git add serenity/ui/calendar_view.py tests/test_ics_ui.py
git commit -m "feat(ui): Calendar-tab ICS export button + handler (guards, suffix, OSError)"
```

---

### Task 8: Import preview dialog (`ui/ics_import_dialog.py`)

**Files:**
- Create: `serenity/ui/ics_import_dialog.py`
- Test: `tests/test_ics_ui.py`

**Interfaces:**
- Consumes: `core.ics.ImportPlan`.
- Produces: `ImportPreviewDialog(plan, parent=None)` (QDialog); `.exec()` returns `QDialog.Accepted`/`Rejected`. Renders counts, capped rows, per-update field diff, recurring warning.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics_ui.py (append)
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
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement**

Create `serenity/ui/ics_import_dialog.py` with the header block, then:
```python
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

_ROW_CAP = 20

class ImportPreviewDialog(QDialog):
    """Preview an ICS ImportPlan; nothing is applied until the user clicks Import."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import calendar")
        self._plan = plan
        self._create_rows = min(len(plan.to_create), _ROW_CAP)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(self.summary_text()))
        body = QWidget(); col = QVBoxLayout(body)
        for ev in plan.to_create[:_ROW_CAP]:
            col.addWidget(QLabel(f"+ {ev.title or '(untitled)'}"))
        if len(plan.to_create) > _ROW_CAP:
            col.addWidget(QLabel(f"…and {len(plan.to_create) - _ROW_CAP} more"))
        for todo, ev in plan.to_update[:_ROW_CAP]:
            diff = self._diff(todo, ev)
            warn = "  ⟳ recurrence kept" if getattr(todo, "recurring", None) else ""
            col.addWidget(QLabel(f"~ {ev.title or '(untitled)'} ({diff}){warn}"))
        for label, why in plan.skipped[:_ROW_CAP]:
            col.addWidget(QLabel(f"– {label}: {why}"))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(body)
        root.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Import")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def summary_text(self) -> str:
        p = self._plan
        parts = [f"{len(p.to_create)} new", f"{len(p.to_update)} update(s)",
                 f"{len(p.skipped)} skipped"]
        return " · ".join(parts)

    def rendered_create_rows(self) -> int:
        return self._create_rows

    @staticmethod
    def _diff(todo, ev) -> str:
        out = []
        if todo.due != ev.when:
            out.append(f"due {todo.due:%Y-%m-%d %H:%M} → {ev.when:%Y-%m-%d %H:%M}")
        if todo.title != ev.title:
            out.append(f"title → {ev.title!r}")
        if (todo.category or None) != (ev.category or None):
            out.append(f"category → {ev.category!r}")
        return "; ".join(out) or "no change"
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add serenity/ui/ics_import_dialog.py tests/test_ics_ui.py
git commit -m "feat(ui): ICS import preview dialog (counts, capped rows, field diff)"
```

---

### Task 9: Import handler + shell refresh wiring

**Files:**
- Modify: `serenity/ui/calendar_view.py` (replace the `_import_ics` stub; add `_apply_import`, `_apply_fields`; `wrote = Signal()`)
- Modify: `serenity/ui/shell.py:323` (connect `calendar_view.wrote`) and `:434-438` (`_on_calendar_wrote` pop-out refresh)
- Test: `tests/test_ics_ui.py`

**Interfaces:**
- Consumes: `core.ics.parse_ics`, `reconcile`, `decode_ics_bytes`; `ImportPreviewDialog` (Task 8); `TodoStore.all/add/update/save/reload`.
- Produces: `CalendarView.wrote` signal; `_import_ics`, `_apply_import(plan)`, `_apply_fields(todo, ev)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics_ui.py (append)
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
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement**

In `serenity/ui/calendar_view.py`: add near the imports —
```python
from ..core.ics import todos_to_ics, parse_ics, reconcile, decode_ics_bytes
from ..core.models import Todo
from .ics_import_dialog import ImportPreviewDialog
from PySide6.QtWidgets import QDialog

ICS_MAX_BYTES = 5 * 1024 * 1024
```
Add the signal beside the existing ones (after line 42):
```python
    wrote = Signal()   # a confirmed import landed -> shell fans a cross-surface refresh
```
Replace the Task-7 `_import_ics` stub with:
```python
    def _import_ics(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import calendar", "",
                                              "iCalendar (*.ics)")
        if not path:
            return
        p = Path(path)
        try:
            if p.stat().st_size > ICS_MAX_BYTES:
                QMessageBox.warning(self, "Import calendar",
                                    "That file is too large to import (over 5 MB).")
                return
            with open(p, "rb") as f:
                raw = f.read(ICS_MAX_BYTES + 1)
        except OSError as exc:
            QMessageBox.warning(self, "Import calendar", f"Could not read the file:\n{exc}")
            return
        if len(raw) > ICS_MAX_BYTES:
            QMessageBox.warning(self, "Import calendar",
                                "That file is too large to import (over 5 MB).")
            return
        try:
            text = decode_ics_bytes(raw)
        except ValueError:
            QMessageBox.warning(self, "Import calendar",
                                "That file is not readable text / a valid .ics file.")
            return
        parsed = parse_ics(text)
        if not parsed.is_calendar:
            QMessageBox.warning(self, "Import calendar",
                                "That doesn't look like a calendar (.ics) file.")
            return
        plan = reconcile(parsed, self.todo_store.all())
        if not plan.to_create and not plan.to_update:
            msg = "No importable events found."
            if plan.skipped:
                msg += "\n\nSkipped:\n" + "\n".join(
                    f"• {lbl}: {why}" for lbl, why in plan.skipped[:20])
            QMessageBox.information(self, "Import calendar", msg)
            return
        if ImportPreviewDialog(plan, self).exec() != QDialog.Accepted:
            return
        self._apply_import(plan)

    def _apply_import(self, plan):
        store = self.todo_store
        live = {t.id: t for t in store.all()}
        by_uid = {t.ics_uid: t for t in store.all() if t.ics_uid}
        for ev in plan.to_create:
            target = live.get(ev.uid) or by_uid.get(ev.uid)   # re-resolve a now-existing UID
            if target is not None:
                self._apply_fields(target, ev); store.update(target, persist=False)
            else:
                store.add(Todo(title=ev.title, due=ev.when, category=ev.category,
                               ics_uid=ev.uid), persist=False)
        for todo, ev in plan.to_update:
            cur = live.get(todo.id)
            if cur is None:                                    # purged while the modal was open
                continue
            self._apply_fields(cur, ev); store.update(cur, persist=False)
        try:
            store.save()
        except OSError as exc:
            store.reload()                                     # drop the in-memory changes
            QMessageBox.warning(self, "Import failed", f"Could not save:\n{exc}")
            return
        self.wrote.emit()

    @staticmethod
    def _apply_fields(todo, ev):
        todo.due = ev.when
        todo.title = ev.title
        todo.category = ev.category
```
In `serenity/ui/shell.py` after line 323 (`self.calendar_view = CalendarView(self.todo_store)`):
```python
        self.calendar_view.wrote.connect(self._on_calendar_wrote)
```
Extend `_on_calendar_wrote` (line 434) to also refresh an open expanded calendar pop-out:
```python
    def _on_calendar_wrote(self):
        self.calendar_view.refresh()
        self.todos_view.refresh()
        panel = getattr(self, "_expanded", None)
        inner = getattr(panel, "inner", None)
        if isinstance(inner, CalendarWeekPanel):
            inner.refresh()
```
> Confirm `ExpandedPanel`'s hosted-widget attribute name (it is `inner` per `_make_calendar_panel`/`ExpandedPanel.__init__`; if different, use the real one). Ensure `CalendarWeekPanel` is imported in shell.py (it already is — see line 555).

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Run full suite + commit**

```bash
git add serenity/ui/calendar_view.py serenity/ui/shell.py tests/test_ics_ui.py
git commit -m "feat(ui): ICS import handler (size cap, decode, preview, transactional apply) + refresh wiring"
```

---

## Self-Review

**Spec coverage:**
- §3 datetime model → Tasks 3 (export floating/VALUE=DATE/DTSTAMP-UTC), 4 (import normalize to local).
- §4 module API → Tasks 3/5/6 (`todos_to_ics`/`parse_ics`/`reconcile` + dataclasses).
- §5 export (predicate+empty guard, cancel, suffix, OSError) → Task 7.
- §6 import (size cap, decode/BOM, read OSError, defensive parse, RRULE, reconcile rules) → Tasks 5, 6, 9.
- §7 apply (transactional single-save, re-resolve, field-scope) → Task 9 (`_apply_import`/`_apply_fields`).
- §8 preview (counts, diff, zero-importable, row cap) → Tasks 8 + 9.
- §9 model field → Task 1.
- P1 EXP-5 escaping/fold → Task 2; P1 datetime → Tasks 3/4.

**Open verification items (confirm during execution, not blockers):**
- `ExpandedPanel`'s hosted-widget attribute name (Task 9) — verify it's `inner`.
- The export/import button glyphs `⤓ ICS`/`⤒ ICS` are placeholders for layout; adjust to fit the toolbar width if cramped.
- Re-entry guard: the modal `exec()` already serializes a single import; if a stronger guard is wanted, disable `import_btn` around `_apply_import`. Left minimal per YAGNI.

**Placeholder scan:** none — every step has runnable code/commands.

**Type consistency:** `ParsedEvent`/`ParsedCalendar`/`ImportPlan` field names match across Tasks 5/6/8/9; `_apply_fields` mutates only `{due,title,category}` matching `_differs`.
