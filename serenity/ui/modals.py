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
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core import reminders
from ..core.models import Todo
from ..core.parser import parse_capture
from .reminder_picker import ReminderPicker
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

    def __init__(self, note_store, settings, parent=None, stamp=None):
        super().__init__(parent)
        self.note_store = note_store
        self.settings = settings
        # zero-arg callable -> (state_tag, context), read at SAVE time (Phase C R10)
        self._stamp = stamp
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
        st, ctx = self._stamp() if self._stamp else (None, None)
        note = self.note_store.create(title or "Quick note", body=body, tags=tags,
                                      state_tag=st, context=ctx)
        # remember new tags in the arsenal so they autocomplete next time
        if tags and self.settings.add_tags(tags):
            self.settings.save()
        self.saved.emit(note)
        self.accept()


def save_quick_todo(todo_store, settings, *, title: str, when_text: str = "",
                    default_due: "datetime | None" = None, due: "datetime | None" = None,
                    recurring: str | None = None, stamp=None, rungs=(),
                    prep_auto: bool = False) -> "Todo | None":
    """Build + persist a quick-capture todo. Returns the Todo, or None when nothing was
    saved (blank title, or the disk write failed - the caller keeps its form open).

    Shared by QuickTodoDialog (natural-language `when_text`, or a clicked calendar slot via
    `default_due`) and CaptureBubble (an explicit `due` from its date/time pickers), so the
    two entry points cannot drift apart. Rules are exactly the dialog's originals:
    - with an explicit `due` or a `default_due`, a date token in the TITLE must not hijack
      placement - the title is parsed only for category/tags;
    - otherwise title+when parse together (the Phase-1 behaviour);
    - an OSError from the atomic write undoes add()'s in-memory append, so a later
      successful save cannot flush a phantom todo;
    - reminders are armed (and re-saved) only when rungs were picked;
    - new tags are registered in Settings;
    - `prep_auto` (Meeting-Prep, default OFF) only sticks on a meeting - arming a non-meeting
      would leave a flag nothing ever reads."""
    title = (title or "").strip()
    if not title:
        return None
    when_text = (when_text or "").strip()
    st, ctx = stamp() if stamp else (None, None)
    if due is not None or default_due is not None:
        title_cap = parse_capture(title)
        when_cap = parse_capture(when_text) if when_text else None
        chosen = due if due is not None else (
            when_cap.date if (when_cap and when_cap.date) else default_due)
        todo = Todo(title=title, due=chosen,
                    recurring=recurring or (when_cap.recurring if when_cap else None),
                    category=title_cap.category, tags=title_cap.tags,
                    state_tag=st, context=ctx)
    else:
        cap = parse_capture(f"{title} {when_text}".strip())
        todo = Todo(title=title, due=cap.date, recurring=recurring or cap.recurring,
                    category=cap.category, tags=cap.tags, state_tag=st, context=ctx)
    if prep_auto and todo.category == "meeting":
        todo.prep_auto = True
    try:
        todo_store.add(todo)
    except OSError:
        if todo in todo_store._todos:
            todo_store._todos.remove(todo)
        return None
    if rungs:
        reminders.arm(todo, list(rungs), datetime.now())
        todo_store.save()
    if todo.tags and settings.add_tags(todo.tags):
        settings.save()
    return todo


class QuickTodoDialog(QDialog):
    added = Signal(object)                 # emits the created Todo

    def __init__(self, todo_store, settings, parent=None, default_due: datetime | None = None,
                 stamp=None):
        super().__init__(parent)
        self.todo_store = todo_store
        self.settings = settings
        self.default_due = default_due       # slice (b): a clicked calendar slot pre-fills the due
        # zero-arg callable -> (state_tag, context), read at SAVE time (Phase C R10)
        self._stamp = stamp
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
        # Reminder picker row (H5 / task 9): bound to the when field for due date
        self.reminder_picker = ReminderPicker(due_provider=self._get_reminder_due)
        self.reminder_picker.refresh()  # Evaluate rungs against initial default_due
        self.when.textChanged.connect(self.reminder_picker.refresh)  # Re-evaluate as user types
        lay.addWidget(self.reminder_picker)
        # Meeting-Prep: default OFF, and only shown once the title actually parses as a meeting
        # (arming a non-meeting would leave a flag nothing ever reads).
        self.prep_auto = QCheckBox("Auto-prep this meeting")
        self.prep_auto.setToolTip(
            "Prepare this meeting automatically the evening before or the morning of: carry "
            "over what the last protocol left open, plus related notes and your open todos.")
        self.prep_auto.hide()
        self.title.textChanged.connect(self._sync_prep_auto)
        lay.addWidget(self.prep_auto)
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

    def _sync_prep_auto(self, text: str) -> None:
        """Reveal the auto-prep toggle only while the typed title parses as a meeting."""
        is_meeting = parse_capture(text).category == "meeting" if text.strip() else False
        self.prep_auto.setVisible(is_meeting)
        if not is_meeting:
            self.prep_auto.setChecked(False)

    def _get_reminder_due(self) -> datetime | None:
        """Compute the due date for the reminder picker: from the when field if set, else
        from default_due (the calendar slot). Used as the due_provider for the picker."""
        when = self.when.text().strip()
        if when:
            when_cap = parse_capture(when)
            if when_cap and when_cap.date:
                return when_cap.date
        return self.default_due

    def _save(self):
        todo = save_quick_todo(
            self.todo_store, self.settings,
            title=self.title.text(), when_text=self.when.text(),
            default_due=self.default_due, stamp=self._stamp,
            rungs=self.reminder_picker.selected(),
            prep_auto=self.prep_auto.isChecked())
        if todo is None:
            if self.title.text().strip():
                self._error.show()          # H2: the write failed - keep the modal open
            return
        self.added.emit(todo)
        self.accept()

_CHEATSHEET = [
    ("Intent keywords", [
        "Termin / Meeting -> meeting",
        "Notiz / Note / Merk dir -> note",
        "Todo / Aufgabe / Erledige -> todo",
        "Erinnerung / Reminder -> todo + reminder",
        "Idee / Idea -> note (idea)",
        "Tagebuch / Diary / Journal -> diary",
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
