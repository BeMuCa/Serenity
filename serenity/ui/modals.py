"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Quick-capture modals (Quick Note / Quick Todo) + the mic intent cheatsheet.
Role:    The bottom bar opens these. Quick Note writes a markdown note; Quick Todo
         parses natural-language dates into a todo. The cheatsheet overlay lists the
         intent-keyword + date grammar (decisions doc 4a) shown when the mic opens.

Classes:
- QuickNoteDialog - title + body -> NoteStore.create
- QuickTodoDialog - title + "when" -> parsed Todo
- CheatsheetDialog - intent/date/entity grammar reference
============================================================
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core.models import Todo
from ..core.parser import parse_capture
from .theme import COLORS


def protocol_template(now: datetime | None = None) -> str:
    """A one-click meeting-protocol skeleton: dated heading + the usual sections.

    House style: single hyphens only, no emoji. Used by the Quick Note protocol button."""
    now = now or datetime.now()
    date = now.strftime("%Y-%m-%d")
    return (
        f"# Protokoll - {date}\n\n"
        "## Teilnehmer\n- \n\n"
        "## Agenda\n- \n\n"
        "## Notizen\n- \n\n"
        "## Beschluesse\n- \n\n"
        "## Aufgaben\n- \n"
    )


def parse_tags(text: str) -> list[str]:
    """Split a tag input into a clean list (comma / whitespace separated, '#' stripped)."""
    raw = text.replace(",", " ").split()
    out: list[str] = []
    seen = set()
    for t in raw:
        t = t.lstrip("#").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


class QuickNoteDialog(QDialog):
    saved = Signal(object)                 # emits the created Note

    def __init__(self, note_store, settings, parent=None):
        super().__init__(parent)
        self.note_store = note_store
        self.settings = settings
        self.setWindowTitle("Quick note")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        head = QLabel("Quick note")
        head.setStyleSheet("font-size:14px; font-weight:600;")
        sub = QLabel("Saved to your vault as markdown")
        sub.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(head)
        lay.addWidget(sub)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (optional)")
        lay.addWidget(self.title)
        # tag input - writes to the note front-matter (and grows the tag arsenal)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Tags (comma separated) - e.g. Protokoll, meeting")
        lay.addWidget(self.tags)
        # quick chips for a couple of starter tags + the protocol template
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for tag in ("Protokoll", "meeting"):
            b = QPushButton(f"#{tag}")
            b.setObjectName("ghost")
            b.clicked.connect(lambda _=False, t=tag: self._add_tag(t))
            chips.addWidget(b)
        proto = QPushButton("Protocol template")
        proto.setObjectName("ghost")
        proto.clicked.connect(self._insert_protocol)
        chips.addWidget(proto)
        chips.addStretch(1)
        lay.addLayout(chips)
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Write your note. Markdown is welcome.")
        self.body.setMinimumHeight(140)
        lay.addWidget(self.body)
        foot = QHBoxLayout()
        foot.addWidget(QLabel("Ctrl+Enter to save"))
        foot.addStretch(1)
        save = QPushButton("Save note")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        foot.addWidget(save)
        lay.addLayout(foot)

    def _add_tag(self, tag: str) -> None:
        """Append a starter tag to the tag field if not already present."""
        existing = parse_tags(self.tags.text())
        if tag.lower() not in {t.lower() for t in existing}:
            existing.append(tag)
        self.tags.setText(", ".join(existing))

    def _insert_protocol(self) -> None:
        """Drop the protocol skeleton in (and tag the note 'Protokoll' / 'meeting')."""
        self.body.setPlainText(protocol_template())
        if not self.title.text().strip():
            self.title.setText(f"Protokoll {datetime.now().strftime('%Y-%m-%d')}")
        for t in ("Protokoll", "meeting"):
            self._add_tag(t)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and (e.modifiers() & Qt.ControlModifier):
            self._save()
            return
        super().keyPressEvent(e)

    def _save(self):
        title = self.title.text().strip()
        body = self.body.toPlainText().strip()
        tags = parse_tags(self.tags.text())
        if not title and not body:
            return
        note = self.note_store.create(title or "Quick note", body=body, tags=tags)
        # remember new tags in the arsenal so they autocomplete next time
        if tags and self.settings.add_tags(tags):
            self.settings.save()
        self.saved.emit(note)
        self.accept()


class QuickTodoDialog(QDialog):
    added = Signal(object)                 # emits the created Todo

    def __init__(self, todo_store, settings, parent=None, default_due: datetime | None = None):
        super().__init__(parent)
        self.todo_store = todo_store
        self.settings = settings
        self.default_due = default_due       # slice (b): a clicked calendar slot pre-fills the due
        self.setWindowTitle("Quick todo")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        head = QLabel("Quick todo")
        head.setStyleSheet("font-size:14px; font-weight:600;")
        sub = QLabel("Drops it into your task list")
        sub.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(head)
        lay.addWidget(sub)
        self.title = QLineEdit()
        self.title.setPlaceholderText("What needs doing?")
        self.title.returnPressed.connect(self._save)
        lay.addWidget(self.title)
        self.when = QLineEdit()
        self.when.setPlaceholderText("When? e.g. tomorrow 5pm (optional)")
        self.when.returnPressed.connect(self._save)
        lay.addWidget(self.when)
        # hidden until a save fails (H2): an atomic-write OSError keeps the modal open
        self._error = QLabel("Could not save - your disk may be full. Try again.")
        self._error.setStyleSheet("color:#fca5a5; font-size:11px;")
        self._error.setWordWrap(True)
        self._error.hide()
        lay.addWidget(self._error)
        foot = QHBoxLayout()
        foot.addWidget(QLabel("Natural-language dates"))
        foot.addStretch(1)
        add = QPushButton("Add todo")
        add.setObjectName("primary")
        add.clicked.connect(self._save)
        foot.addWidget(add)
        lay.addLayout(foot)

    def _save(self):
        title = self.title.text().strip()
        if not title:
            return
        when = self.when.text().strip()
        if self.default_due is not None:
            # H4 (slice b): a clicked slot pre-fills the due. Parse the WHEN FIELD ONLY so a
            # date token in the title never hijacks placement; a typed when still wins, a blank
            # when falls back to the slot. Category/tags still come from the title parse.
            title_cap = parse_capture(title)
            when_cap = parse_capture(when) if when else None
            due = when_cap.date if (when_cap and when_cap.date) else self.default_due
            recurring = when_cap.recurring if when_cap else None
            todo = Todo(title=title, due=due, recurring=recurring,
                        category=title_cap.category, tags=title_cap.tags)
            tags = title_cap.tags
        else:
            combined = f"{title} {when}".strip()
            cap = parse_capture(combined)
            todo = Todo(title=title, due=cap.date, recurring=cap.recurring,
                        category=cap.category, tags=cap.tags)
            tags = cap.tags
        try:
            self.todo_store.add(todo)
        except OSError:
            # H2: the atomic write failed - undo add()'s in-memory append (it appends before
            # save(), so a later successful write would otherwise flush the phantom) and keep
            # the modal open with an inline error. No settings.save / added.emit / accept.
            if todo in self.todo_store._todos:
                self.todo_store._todos.remove(todo)
            self._error.show()
            return
        if tags and self.settings.add_tags(tags):
            self.settings.save()
        self.added.emit(todo)
        self.accept()


_CHEATSHEET = [
    ("Intent keywords", [
        "Termin / Meeting -> meeting",
        "Notiz / Note / Merk dir -> note",
        "Todo / Aufgabe / Erledige -> todo",
        "Erinnerung / Reminder -> todo + reminder",
        "Idee / Idea -> note (idea)",
        "Frage / Was / Wann / Wie -> Ask-Your-Vault (Phase 2)",
    ]),
    ("Dates", [
        "montag 14.7 8:00",
        "morgen 17 Uhr / tomorrow 5pm",
        "naechste Woche / next week",
        "in 30 min",
        "jeden Werktag (recurring)",
    ]),
    ("Entities", [
        "mit <Person> / with <Person>",
        "#tag",
        "@kategorie",
    ]),
]


class CheatsheetDialog(QDialog):
    """The intent-keyword + grammar overlay shown when the mic opens."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice grammar")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        head = QLabel("Say it naturally - she picks up the intent, date and entities")
        head.setStyleSheet("font-size:13px; font-weight:600;")
        head.setWordWrap(True)
        lay.addWidget(head)
        for section, items in _CHEATSHEET:
            s = QLabel(section)
            s.setObjectName("sectLabel")
            lay.addWidget(s)
            for it in items:
                row = QLabel("  " + it)
                row.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
                lay.addWidget(row)
        note = QLabel("Phase 1 parses this deterministically - no audio is recorded yet. "
                      "Local transcription arrives in Phase 2.")
        note.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
