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
============================================================
"""

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
