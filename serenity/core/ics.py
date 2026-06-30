"""
============================================================
Author:  Berk
Created: 2026-06-30
Purpose: RFC-5545 text escape/unescape, line folding, export, and import helpers.
Role:    Low-level ICS/iCalendar format primitives used by export
         and import tasks to safely encode property values, fold
         lines to 75-octet limit per RFC-5545, and defensively
         parse incoming .ics files into structured dataclasses.

Classes:
- ParsedEvent — dataclass for a single imported VEVENT
- ParsedCalendar — dataclass wrapping events + skipped list + is_calendar flag
- ImportPlan — dataclass wrapping reconcile results (to_create, to_update, skipped)

Functions:
- _escape_text(value) — escape semicolon, comma, backslash, newline
- _unescape_text(value) — unescape escaped sequences
- _fold(line) — fold to 75-octet segments, preserving UTF-8 char boundaries
- _unfold(text) — unfold CRLF+space continuations
- todos_to_ics(todos, now) — export todos to RFC-5545 VCALENDAR string
- decode_ics_bytes(raw) — decode raw bytes to str (UTF-16 BOM / UTF-8 BOM / UTF-8)
- _parse_prop(line) — split a property line into (name, params, value)
- _build_event(cur, idx) — build ParsedEvent from raw property dict; returns (ev, label, reason)
- parse_ics(text) — defensively parse an ICS text into ParsedCalendar; never raises
- _differs(todo, ev) — check if todo and parsed event differ on due/title/category
- reconcile(parsed, existing_todos) — classify parsed events into create/update/skip plan
============================================================
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .calview import _has_time


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


@dataclass
class ImportPlan:
    to_create: list
    to_update: list
    skipped: list


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
