"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Deterministic keyword/date/entity parser for captured text (DE/EN).
Role:    Phase-1 stand-in for the Phase-2 LLM capture router. Turns a typed or
         (later) transcribed utterance into a structured capture: intent, title,
         date, tags, category, person, recurring. No network, no model. The voice
         grammar lives in 3_Build_Decisions.md.

Functions:
- parse_capture(text, now=None) -> Capture - full parse with confidence + missing slots
- parse_natural_date(text, now=None) -> datetime | None - NL date via dateparser
- _detect_intent(text) -> (intent, matched_keyword, remainder)
- _extract_entities(text) -> (tags, category, person, remainder)
- _detect_recurring(text) -> str | None

Models:
- Capture - dataclass holding the parsed result
============================================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import dateparser

# --- intent keywords (leading, optional). Order matters: longest/most-specific first. ---
# Each entry: (canonical intent, [keywords...]). reminder => todo + reminder flag.
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("meeting", ["termin", "meeting"]),
    ("reminder", ["erinnerung", "reminder", "erinnere mich", "remind me"]),
    ("todo", ["todo", "aufgabe", "erledige", "to-do", "task"]),
    ("note_idea", ["idee", "idea"]),
    ("note", ["notiz", "note", "merk dir", "merke dir"]),
    ("ask", ["frage", "was", "wann", "wie", "warum", "wieso", "ask"]),
]

# date/recurring grammar
_RECURRING_PATTERNS: list[tuple[str, str]] = [
    (r"jeden werktag|every weekday|jeden wochentag", "every weekday"),
    (r"jeden tag|t(ae|ä)glich|every day|daily", "daily"),
    (r"jede woche|w(oe|ö)chentlich|every week|weekly", "weekly"),
    (r"jeden monat|monatlich|every month|monthly", "monthly"),
    (r"jeden (montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)", "weekly-day"),
    (r"every (monday|tuesday|wednesday|thursday|friday|saturday|sunday)", "weekly-day"),
]

# the 8 starter category tags (decisions doc 4c)
BASIC_TAGS = ["Work", "Personal", "Meeting", "Idea", "Errand", "Finance", "Health", "Urgent"]

_TAG_RE = re.compile(r"#([\wäöüÄÖÜß-]+)", re.UNICODE)
_CAT_RE = re.compile(r"@([\wäöüÄÖÜß-]+)", re.UNICODE)
_PERSON_RE = re.compile(r"\b(?:mit|with)\s+([A-ZÄÖÜ][\wäöüÄÖÜß-]+)", re.UNICODE)


@dataclass
class Capture:
    """Structured result of parsing a capture utterance."""

    raw: str
    intent: str = "note"           # todo | note | note_idea | meeting | reminder | ask
    title: str = ""
    date: Optional[datetime] = None
    has_time: bool = False         # True if a clock time was given (not just a day)
    tags: list[str] = field(default_factory=list)
    category: Optional[str] = None
    person: Optional[str] = None
    recurring: Optional[str] = None
    reminder: bool = False
    reminder_offset: Optional[int] = None  # minutes, pre-snap; extracted from lead phrase
    confidence: float = 0.0
    missing: list[str] = field(default_factory=list)  # required slots not filled

    @property
    def kind(self) -> str:
        """Coarse destination: 'todo' or 'note' (meeting/reminder are todos)."""
        if self.intent in ("todo", "meeting", "reminder"):
            return "todo"
        return "note"


def parse_natural_date(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a natural-language date/time. German + English, future-biased."""
    if not text or not text.strip():
        return None
    settings = {
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": False,
    }
    if now is not None:
        settings["RELATIVE_BASE"] = now
    return dateparser.parse(text, languages=["de", "en"], settings=settings)


def _strip_leading(text: str, phrase: str) -> str:
    """Remove a leading keyword phrase (case-insensitive) plus a trailing :/- separator."""
    pat = re.compile(r"^\s*" + re.escape(phrase) + r"\b[:\-\s]*", re.IGNORECASE)
    return pat.sub("", text, count=1)


def _detect_intent(text: str) -> tuple[str, Optional[str], str]:
    """Return (intent, matched_keyword, text_without_leading_keyword)."""
    lowered = text.lstrip()
    low = lowered.lower()
    for intent, keywords in _INTENT_KEYWORDS:
        for kw in keywords:
            # leading keyword, as a word boundary
            if low.startswith(kw) and (len(low) == len(kw) or not low[len(kw)].isalnum()):
                return intent, kw, _strip_leading(lowered, kw)
    return "note", None, text


def _detect_recurring(text: str) -> Optional[str]:
    low = text.lower()
    for pattern, label in _RECURRING_PATTERNS:
        if re.search(pattern, low):
            return label
    return None


def _extract_entities(text: str) -> tuple[list[str], Optional[str], Optional[str], str]:
    """Pull #tags, @category, mit/with Person. Return (tags, category, person, remainder)."""
    tags = [m.group(1) for m in _TAG_RE.finditer(text)]
    cat_match = _CAT_RE.search(text)
    category = cat_match.group(1) if cat_match else None
    person_match = _PERSON_RE.search(text)
    person = person_match.group(1) if person_match else None

    remainder = _TAG_RE.sub("", text)
    remainder = _CAT_RE.sub("", remainder)
    if person_match:
        remainder = remainder.replace(person_match.group(0), "")
    remainder = re.sub(r"\s{2,}", " ", remainder).strip(" ,;-")
    return tags, category, person, remainder


# tokens that signal a date so we can trim them out of the title
_DATE_TRIM_RE = re.compile(
    r"\b("
    r"heute|morgen|uebermorgen|übermorgen|gestern|"
    r"today|tomorrow|tonight|yesterday|"
    r"naechste woche|nächste woche|next week|"
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"in \d+\s*(min(uten)?|stunden?|tagen?|hours?|days?|minutes?)|"
    r"(um\s+)?\d{1,2}([:.]\d{2})?\s*uhr|"
    r"\d{1,2}[:.]\d{2}\s*(uhr|am|pm)?|"
    r"\d{1,2}\.\d{1,2}(\.\d{2,4})?|"
    r"\d{1,2}\s*(am|pm)"
    r")\b",
    re.IGNORECASE,
)

# reminder offset phrase: duration + unit + lead word (case-insensitive)
# units (longest variants first): minuten/minutes/minute/min, stunden/stunde/hours/hour/std/h,
#   tagen/tage/tag/days/day/d, wochen/woche/weeks/week/w
# lead words (longest-first): vorher/davor/before/in advance/vor
#   (fr[ue]her also matches the ASCII typos "fruher"/"freher" — NOT the umlaut "früher" or "frueher")
_REMINDER_OFFSET_RE = re.compile(
    r"(\d+)\s*"
    r"(minuten|minutes|minute|min|"
    r"stunden|stunde|hours|hour|std|h|"
    r"tagen|tage|tag|days|day|d|"
    r"wochen|woche|weeks|week|w)\s+"
    r"(vorher|davor|fr[ue]her|before|in\s+advance|vor)\b",
    re.IGNORECASE,
)

_TIME_RE = re.compile(
    r"(\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s*(uhr|am|pm)\b|um \d{1,2}\s*uhr)",
    re.IGNORECASE,
)

# German "<H> Uhr" / "<H>:<M> Uhr" / "um <H> Uhr" is a time, but dateparser only
# resolves it when normalized to "<H>:<M>". Rewrite it before parsing so the clock
# time actually lands on the resolved date (decisions doc 6.5 example 1).
_UHR_RE = re.compile(r"\b(?:um\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*uhr\b", re.IGNORECASE)


def _normalize_uhr(phrase: str) -> str:
    return _UHR_RE.sub(
        lambda m: f"{int(m.group(1)):02d}:{m.group(2) or '00'}", phrase
    )


def _extract_reminder_offset(text: str) -> tuple[Optional[int], str]:
    """Extract reminder offset phrase from text and return (minutes, remainder).

    Finds the first match of: <number> <unit> <lead-word>, converts unit to minutes,
    strips the phrase from text, and returns (minutes, text_without_phrase). If no match,
    returns (None, text)."""
    match = _REMINDER_OFFSET_RE.search(text)
    if not match:
        return None, text

    number = int(match.group(1))
    unit_str = match.group(2).lower()
    remainder = text[:match.start()] + text[match.end():]
    remainder = re.sub(r"\s{2,}", " ", remainder).strip()

    # Convert unit to minutes
    if unit_str in ("min", "minute", "minuten", "minutes"):
        minutes = number * 1
    elif unit_str in ("h", "hour", "hours", "std", "stunde", "stunden"):
        minutes = number * 60
    elif unit_str in ("d", "day", "days", "tag", "tage", "tagen"):
        minutes = number * 1440
    elif unit_str in ("w", "week", "weeks", "woche", "wochen"):
        minutes = number * 10080
    else:
        return None, text

    return minutes, remainder


def _clean_title(text: str) -> str:
    out = _DATE_TRIM_RE.sub("", text)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;:-")
    return out


def parse_capture(text: str, now: Optional[datetime] = None) -> Capture:
    """Parse a capture utterance into a structured Capture.

    Confidence is a deterministic heuristic in [0,1]; < 0.55 or a missing required
    slot signals the UI to ask via slot-filling (decisions doc 4b)."""
    raw = (text or "").strip()
    cap = Capture(raw=raw)
    if not raw:
        cap.missing = ["title"]
        return cap

    intent, matched_kw, rest = _detect_intent(raw)
    cap.intent = intent
    if intent == "reminder":
        cap.reminder = True

    tags, category, person, rest = _extract_entities(rest)
    cap.tags = tags
    cap.category = category
    cap.person = person

    cap.recurring = _detect_recurring(rest)

    # Extract reminder offset (lead phrase: "1 day before" etc.) and strip from rest
    # before cleaning the title, so offset tokens don't leak into the title.
    reminder_offset, rest = _extract_reminder_offset(rest)
    cap.reminder_offset = reminder_offset

    # Parse the date from just the date-bearing tokens (verbs in `rest` confuse
    # dateparser), so "call dentist tomorrow 9:00" yields the date for "tomorrow 9:00".
    date_phrase = " ".join(m.group(0) for m in _DATE_TRIM_RE.finditer(rest)).strip()
    if date_phrase:
        parsed_date = parse_natural_date(_normalize_uhr(date_phrase), now=now)
        if parsed_date is not None:
            cap.date = parsed_date
            cap.has_time = bool(_TIME_RE.search(date_phrase))

    cap.title = _clean_title(rest)

    # --- confidence heuristic ---
    score = 0.4
    if matched_kw:
        score += 0.25
    if cap.title:
        score += 0.2
    if cap.date is not None:
        score += 0.1
    if tags or category or person:
        score += 0.05
    cap.confidence = round(min(score, 1.0), 2)

    # --- required-slot check (drives conversational slot-filling) ---
    missing: list[str] = []
    if not cap.title:
        missing.append("title")
    if cap.kind == "todo" and cap.intent in ("meeting", "reminder") and cap.date is None:
        missing.append("date")
    cap.missing = missing

    return cap
