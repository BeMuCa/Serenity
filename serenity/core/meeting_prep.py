"""
============================================================
Author:  Berk
Created: 2026-08-12
Purpose: Assemble a meeting "Vorbereitung" from the previous occurrence's protocol,
         topically-linked notes and your own open todos.
Role:    Pure core (no Qt, no model) behind the Meeting-Prep feature. The deterministic
         block it renders is written first and is what survives when no LLM is available;
         the queued LLM job only refines the same PrepInput. Spec:
         docs/superpowers/specs/2026-08-12-meeting-prep-design.md

Models:
- Carryover - what the predecessor protocol left open (aufgaben / agenda / beschluesse)
- PrepInput - everything a prep is rendered from (carryover + related notes + own todos)

Functions:
- is_prepped(raw_md) - does this note already carry a prep block
- splice(raw_md, block) - replace between the markers (insert under the H1 when absent)
- extract_carryover(raw_md) - pure section parsing of a predecessor protocol
- find_predecessor(todo, notes, index=None) - (Note|None, source) via series key then topic
- gather(todo, notes, todos, index=None, now=None) - build the PrepInput
- render_prep(prep_input, lang="de", now=None) - the deterministic Markdown block
- llm_prompt(prep_input, lang="de") - the prompt the queued job runs
- series_tag(series_id) - the tag that carries the series key onto a protocol note
- ensure_protocol_note(todo, note_store, template) - the occurrence's protocol note (create+link)
- prep_todo(todo, note_store, todo_store, todos, template, ...) - write the deterministic prep
- apply_refined(note_id, block, note_store) - swap the LLM block in, or refuse when stale
- due_for_auto_prep(todos, now, window_hours=18, is_prepped_fn=None) - pure eligibility
============================================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .models import Note, Todo
from .search import related_notes, semantic_search

PREP_START = "<!-- serenity:prep:start -->"
PREP_END = "<!-- serenity:prep:end -->"

AUTO_PREP_WINDOW_HOURS = 18

# The tag that carries the series key onto a protocol note (that is what makes the chain
# findable from the note side - a Note has no link field).
SERIES_TAG_PREFIX = "serie-"

PROTOCOL_TAGS = ("protokoll", "meeting")

# protocol_template() writes ASCII headings with no trailing colon ("## Beschluesse"), but
# people edit these by hand, so matching accepts the umlaut and a trailing colon too.
_SECTION_ALIASES = {
    "aufgaben": ("aufgaben",),
    "agenda": ("agenda",),
    "beschluesse": ("beschluesse", "beschlüsse"),
}

_DEFER_WORDS = ("vertagt", "verschoben", "deferred", "postponed")

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TICKED_RE = re.compile(r"^\[[xX]\]\s*")
_STRUCK_RE = re.compile(r"^~~.*~~$")


@dataclass
class Carryover:
    """What the predecessor protocol left open. Empty is a valid, common answer."""
    aufgaben: list[str] = field(default_factory=list)
    agenda: list[str] = field(default_factory=list)
    beschluesse: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.aufgaben or self.agenda or self.beschluesse)


@dataclass
class PrepInput:
    """Everything render_prep and llm_prompt need. Source is how the predecessor was found."""
    title: str
    carryover: Carryover = field(default_factory=Carryover)
    predecessor_title: Optional[str] = None
    predecessor_date: Optional[datetime] = None
    source: Optional[str] = None            # "series" | "topic" | None
    related: list[str] = field(default_factory=list)
    own_todos: list[str] = field(default_factory=list)


# --- the block -------------------------------------------------------------------------

def is_prepped(raw_md: str) -> bool:
    """Markers present IS the 'already prepped' fact - there is no separate flag to drift."""
    return PREP_START in (raw_md or "") and PREP_END in (raw_md or "")


def splice(raw_md: str, block: str) -> str:
    """Put `block` between the markers, replacing whatever was there.

    Text OUTSIDE the markers is never read or rewritten - that is what makes regenerating a
    prep safe while you are typing your own notes into the same file. When the note has no
    markers yet the region is inserted directly under the '# ...' heading (or at the top if
    the note has none)."""
    raw = raw_md or ""
    region = f"{PREP_START}\n{block.strip()}\n{PREP_END}"
    start, end = raw.find(PREP_START), raw.find(PREP_END)
    if start != -1 and end != -1 and end > start:
        return raw[:start] + region + raw[end + len(PREP_END):]

    lines = raw.split("\n")
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            head, tail = lines[: i + 1], lines[i + 1:]
            while tail and not tail[0].strip():
                tail.pop(0)
            return "\n".join(head + ["", region, ""] + tail)
    prefix = f"{region}\n"
    return prefix if not raw.strip() else prefix + "\n" + raw


# --- reading a predecessor -------------------------------------------------------------

def _section_lines(raw_md: str, names: tuple[str, ...]) -> list[str]:
    """The bullet entries under the first heading whose text matches one of `names`."""
    out: list[str] = []
    in_section = False
    for line in (raw_md or "").split("\n"):
        heading = _HEADING_RE.match(line)
        if heading:
            label = heading.group(1).strip().rstrip(":").strip().lower()
            if in_section:
                break
            in_section = label in names
            continue
        if not in_section:
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            text = bullet.group(1).strip()
            if text:
                out.append(text)
    return out


def _is_open(entry: str) -> bool:
    """Open unless ticked ('- [x] ...') or struck ('~~...~~'). Plain bullets ARE open -
    the template does not force checkboxes and people write plain bullets."""
    text = entry.strip()
    if _TICKED_RE.match(text):
        return False
    return not _STRUCK_RE.match(text)


def _strip_marks(entry: str) -> str:
    return re.sub(r"^\[[ xX]\]\s*", "", entry.strip()).strip()


def extract_carryover(raw_md: str) -> Carryover:
    """Still-open Aufgaben / Agenda + deferred Beschluesse of a predecessor protocol.

    A malformed or section-less note yields an empty Carryover rather than raising: a
    predecessor we cannot read must degrade to 'nothing to carry over', never to a crash in
    a background break job."""
    if not raw_md:
        return Carryover()
    aufgaben = [_strip_marks(e) for e in _section_lines(raw_md, _SECTION_ALIASES["aufgaben"]) if _is_open(e)]
    agenda = [_strip_marks(e) for e in _section_lines(raw_md, _SECTION_ALIASES["agenda"]) if _is_open(e)]
    # A decision to postpone IS a decision, so defer-word entries count whether open or not.
    beschluesse = [_strip_marks(e) for e in _section_lines(raw_md, _SECTION_ALIASES["beschluesse"])
                   if any(w in e.lower() for w in _DEFER_WORDS)]
    return Carryover(aufgaben=aufgaben, agenda=agenda, beschluesse=beschluesse)


def series_tag(series_id: str) -> str:
    return f"{SERIES_TAG_PREFIX}{series_id}"


def _is_protocol(note: Note) -> bool:
    lowered = {t.lower() for t in note.tags}
    return any(t in lowered for t in PROTOCOL_TAGS)


def _stamp(note: Note) -> datetime:
    return note.created or note.updated or datetime.min


def find_predecessor(todo: Todo, notes: list[Note], index=None) -> tuple[Optional[Note], Optional[str]]:
    """The previous occurrence's protocol note, and HOW it was found ("series"/"topic").

    Series key first (exact), topic search second (fuzzy). A candidate must be STRICTLY
    EARLIER than this occurrence and must not be the occurrence's own note - otherwise two
    eligible occurrences of one series can each pick the other as "previous" (spec N2)."""
    cutoff = todo.due or datetime.now()
    own = set(todo.linked_note_ids)

    def eligible(note: Note) -> bool:
        return (not note.deleted and note.id not in own and _stamp(note) < cutoff)

    if todo.series_id:
        wanted = series_tag(todo.series_id).lower()
        chain = [n for n in notes if eligible(n) and wanted in {t.lower() for t in n.tags}]
        if chain:
            return max(chain, key=_stamp), "series"

    protocols = [n for n in notes if eligible(n) and _is_protocol(n)]
    if not protocols:
        return None, None
    query = " ".join([todo.title] + list(todo.tags)).strip()
    if not query:
        return max(protocols, key=_stamp), "topic"
    ranked = [n for n in semantic_search(protocols, query, index) if n in protocols]
    return (ranked[0] if ranked else max(protocols, key=_stamp)), "topic"


# --- gathering + rendering --------------------------------------------------------------

def _todo_matches(todo: Todo, meeting: Todo) -> bool:
    if todo.id == meeting.id or todo.done or todo.deleted:
        return False
    if meeting.series_id and todo.series_id == meeting.series_id:
        return False
    shared = {t.lower() for t in todo.tags} & {t.lower() for t in meeting.tags}
    return bool(shared) or (bool(meeting.category) and todo.category == meeting.category)


def gather(todo: Todo, notes: list[Note], todos: list[Todo], index=None,
           now: Optional[datetime] = None) -> PrepInput:
    """Build the PrepInput: carry-over + related notes written since the predecessor +
    your own open todos that overlap the meeting."""
    predecessor, source = find_predecessor(todo, notes, index)
    carryover = Carryover()
    since: Optional[datetime] = None
    if predecessor is not None:
        carryover = extract_carryover(predecessor.body)
        since = _stamp(predecessor)

    related: list[str] = []
    if predecessor is not None:
        pool = [n for n in notes if not n.deleted and n.id != predecessor.id]
        fresh = [n for n in pool if since is None or _stamp(n) > since]
        related = [n.title for n in related_notes(predecessor, fresh, index)]
    else:
        query = " ".join([todo.title] + list(todo.tags)).strip()
        pool = [n for n in notes if not n.deleted and n.id not in set(todo.linked_note_ids)]
        if query and pool:
            related = [n.title for n in semantic_search(pool, query, index)[:5]]

    own = [t.title for t in todos if _todo_matches(t, todo)]
    return PrepInput(
        title=todo.title,
        carryover=carryover,
        predecessor_title=predecessor.title if predecessor is not None else None,
        predecessor_date=since,
        source=source,
        related=related,
        own_todos=own,
    )


_LABELS = {
    "de": {
        "heading": "Vorbereitung",
        "from": "Offen aus",
        "none": "Kein frueheres Protokoll gefunden",
        "series": "Serie",
        "topic": "thematisch gefunden",
        "agenda": "Agenda-Uebertrag",
        "beschluesse": "Vertagte Beschluesse",
        "related": "Verwandte Notizen",
        "todos": "Deine offenen Todos",
        "made": "Vorbereitet am",
    },
    "en": {
        "heading": "Preparation",
        "from": "Open from",
        "none": "No earlier protocol found",
        "series": "series",
        "topic": "found by topic",
        "agenda": "Agenda carry-over",
        "beschluesse": "Deferred decisions",
        "related": "Related notes",
        "todos": "Your open todos",
        "made": "Prepared on",
    },
}


def _labels(lang: str) -> dict:
    return _LABELS.get((lang or "de").lower()[:2], _LABELS["de"])


def render_prep(prep_input: PrepInput, lang: str = "de", now: Optional[datetime] = None) -> str:
    """The deterministic block - written first, and what survives with no LLM available.

    House style follows the protocol template (modals.py): single hyphens, no emoji."""
    lb = _labels(lang)
    now = now or datetime.now()
    lines = [f"## {lb['heading']}"]

    if prep_input.predecessor_date is not None:
        stamp = prep_input.predecessor_date.strftime("%Y-%m-%d")
        how = lb["series"] if prep_input.source == "series" else lb["topic"]
        lines.append(f"{lb['from']} {stamp} ({how})")
        for entry in prep_input.carryover.aufgaben:
            lines.append(f"- {entry}")
        if not prep_input.carryover.aufgaben:
            lines.append("- -")
    else:
        lines.append(lb["none"])

    for key, entries in (("agenda", prep_input.carryover.agenda),
                         ("beschluesse", prep_input.carryover.beschluesse),
                         ("related", prep_input.related),
                         ("todos", prep_input.own_todos)):
        if entries:
            lines.append(lb[key])
            lines.extend(f"- {e}" for e in entries)

    lines.append(f"{lb['made']} {now.strftime('%Y-%m-%d')}")
    return "\n".join(lines)


def llm_prompt(prep_input: PrepInput, lang: str = "de") -> str:
    """Ask the model to TIGHTEN the same material - never to invent any."""
    lb = _labels(lang)
    tongue = "Deutsch" if lb is _LABELS["de"] else "English"
    return (
        f"Du bist eine Sekretaerin. Schreibe eine knappe Meeting-Vorbereitung auf {tongue}.\n"
        f"Meeting: {prep_input.title}\n\n"
        "Nutze AUSSCHLIESSLICH die folgenden Fakten. Erfinde nichts, ergaenze nichts.\n"
        "Antworte in Markdown, beginnend mit der Ueberschrift, einfache Bindestriche, keine Emojis.\n\n"
        f"{render_prep(prep_input, lang)}"
    )


# --- orchestration (store I/O, still Qt-free) --------------------------------------------

def ensure_protocol_note(todo: Todo, note_store, template: str):
    """The occurrence's protocol note: its first live linked note, else a fresh one.

    A new note is tagged Protokoll/meeting (so a LATER occurrence can find it by topic) plus
    the series tag when the meeting has one (so it can be found exactly)."""
    for nid in todo.linked_note_ids:
        existing = note_store.get(nid)
        if existing is not None and not existing.deleted:
            return existing, False
    tags = ["Protokoll", "meeting"]
    if todo.series_id:
        tags.append(series_tag(todo.series_id))
    note = note_store.create(todo.title or "Untitled", body=template, tags=tags,
                             state_tag=todo.state_tag, context=todo.context)
    todo.linked_note_ids.append(note.id)
    return note, True


def prep_todo(todo: Todo, note_store, todo_store, todos: list[Todo], template: str,
              lang: str = "de", index=None, now: Optional[datetime] = None):
    """Write the DETERMINISTIC prep into this occurrence's protocol note; return (note, input).

    Step 1 of the two-step in the spec: cheap, model-free, synchronous - the prep exists the
    moment it is asked for. The queued LLM job later refines the SAME PrepInput. The note's
    body is re-read from disk first (spec N1), so a prep never overwrites what you typed
    between two runs."""
    note, created = ensure_protocol_note(todo, note_store, template)
    if created:
        todo_store.update(todo)
    else:
        note_store.reload_note(note.id)
        note = note_store.get(note.id) or note
    prep_input = gather(todo, note_store.all_active(), todos, index, now)
    note.body = splice(note.body, render_prep(prep_input, lang, now))
    note_store.update(note)
    return note, prep_input


def apply_refined(note_id: str, block: str, note_store) -> bool:
    """Swap a queued job's refined block in. Returns False when the result is stale.

    Applied ONLY if the note still exists and still carries both markers - a note deleted,
    or a block you removed, means the result no longer describes anything on screen."""
    note = note_store.get(note_id)
    if note is None or note.deleted:
        return False
    note_store.reload_note(note_id)
    note = note_store.get(note_id)
    if note is None or note.deleted or not is_prepped(note.body):
        return False
    note.body = splice(note.body, block)
    note_store.update(note)
    return True


# --- auto-prep eligibility ---------------------------------------------------------------

def due_for_auto_prep(todos: list[Todo], now: datetime, window_hours: int = AUTO_PREP_WINDOW_HOURS,
                      is_prepped_fn=None) -> list[Todo]:
    """Armed meetings due within the window that are not prepped yet (evening before +
    morning of). `is_prepped_fn(todo) -> bool` is injected so this stays pure - the caller
    owns note I/O."""
    horizon = now + timedelta(hours=window_hours)
    out: list[Todo] = []
    for t in todos:
        if not t.prep_auto or t.done or t.deleted or t.due is None:
            continue
        if not (now <= t.due <= horizon):
            continue
        if is_prepped_fn is not None and is_prepped_fn(t):
            continue
        out.append(t)
    return out
