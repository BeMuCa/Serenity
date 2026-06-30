"""
============================================================
Author:  Berk
Created: 2026-06-30
Purpose: RFC-5545 text escape/unescape and line folding helpers.
Role:    Low-level ICS/iCalendar format primitives used by export
         and import tasks to safely encode property values and fold
         lines to 75-octet limit per RFC-5545.

Functions:
- _escape_text(value) — escape semicolon, comma, backslash, newline
- _unescape_text(value) — unescape escaped sequences
- _fold(line) — fold to 75-octet segments, preserving UTF-8 char boundaries
- _unfold(text) — unfold CRLF+space continuations
- todos_to_ics(todos, now) — export todos to RFC-5545 VCALENDAR string
============================================================
"""

import re
from datetime import datetime, timedelta, timezone
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
