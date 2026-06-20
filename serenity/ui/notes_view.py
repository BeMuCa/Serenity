"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The Notes tab - Text/Meaning search toggle, color-accented note cards.
Role:    Renders NoteStore.all_active()/search() as cards with a left color accent +
         tint, pin-to-top, expand-to-read, and "view raw .md" (file modal). Meaning
         search is a Phase-2 stub: selecting it shows a notice and falls back to Text.

Classes:
- NoteCard - a note card (title, snippet, tags, expand, pin, view-raw)
- RawFileDialog - the view-raw-.md modal
- NotesView - search box + Text/Meaning toggle + scrollable list
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Note
from . import icons
from .theme import COLORS, NOTE_COLOR_HEX


class RawFileDialog(QDialog):
    def __init__(self, note: Note, raw: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("View .md file")
        self.setMinimumSize(520, 420)
        lay = QVBoxLayout(self)
        path = QLabel(note.path)
        path.setStyleSheet(f"color:{COLORS['ink2']}; font-family:Consolas,monospace; font-size:11.5px;")
        path.setWordWrap(True)
        lay.addWidget(path)
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(raw)
        body.setStyleSheet("font-family:Consolas,monospace; font-size:11.5px;")
        lay.addWidget(body, 1)
        foot = QLabel("Filesystem is the source of truth - this is the note's markdown on disk.")
        foot.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        lay.addWidget(foot)


class NoteCard(QFrame):
    changed = Signal()
    deleted = Signal(object)

    def __init__(self, note: Note, store, parent=None):
        super().__init__(parent)
        self.note = note
        self.store = store
        self._expanded = False
        accent = NOTE_COLOR_HEX.get(note.color, NOTE_COLOR_HEX["neutral"])
        self.setStyleSheet(
            f"QFrame {{ background:{COLORS['panel2']}; border:1px solid {COLORS['line']};"
            f"border-left:3px solid {accent}; border-radius:10px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(11, 10, 11, 10)
        outer.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.caret = QPushButton()
        self.caret.setObjectName("iconbtn")
        self.caret.setIcon(icons.icon("caret", COLORS["ink3"], 11))
        self.caret.setFixedSize(18, 18)
        self.caret.clicked.connect(self._toggle)
        top.addWidget(self.caret)

        title = QLabel(note.title)
        title.setStyleSheet("font-size:13.5px; font-weight:600;")
        top.addWidget(title, 1)

        self.pin_btn = QPushButton()
        self.pin_btn.setObjectName("iconbtn")
        self.pin_btn.setIcon(icons.icon("pin", accent if note.pinned else COLORS["ink3"], 13))
        self.pin_btn.setFixedSize(22, 22)
        self.pin_btn.setToolTip("Unpin" if note.pinned else "Pin to top")
        self.pin_btn.clicked.connect(self._toggle_pin)
        top.addWidget(self.pin_btn)

        view_btn = QPushButton()
        view_btn.setObjectName("iconbtn")
        view_btn.setIcon(icons.icon("file", COLORS["ink3"], 12))
        view_btn.setFixedSize(22, 22)
        view_btn.setToolTip("View raw .md file")
        view_btn.clicked.connect(self._view_raw)
        top.addWidget(view_btn)

        del_btn = QPushButton()
        del_btn.setObjectName("iconbtn")
        del_btn.setIcon(icons.icon("trash", COLORS["ink3"], 12))
        del_btn.setFixedSize(22, 22)
        del_btn.setToolTip("Move to Trash")
        del_btn.clicked.connect(lambda: self.deleted.emit(self.note))
        top.addWidget(del_btn)
        outer.addLayout(top)

        snippet = (note.body.strip().replace("\n", " ")[:120]) or "(empty)"
        self.snip = QLabel(snippet + ("..." if len(note.body) > 120 else ""))
        self.snip.setWordWrap(True)
        self.snip.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
        outer.addWidget(self.snip)

        self.full = QLabel(note.body.strip() or "(empty)")
        self.full.setWordWrap(True)
        self.full.setTextFormat(Qt.PlainText)
        self.full.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
        self.full.hide()
        outer.addWidget(self.full)

        if note.tags:
            tagrow = QHBoxLayout()
            tagrow.setSpacing(6)
            for t in note.tags:
                tl = QLabel(f"#{t}")
                tl.setStyleSheet(
                    f"color:{COLORS['ink2']}; border:1px solid {COLORS['line']};"
                    f"border-radius:6px; padding:1px 7px; font-size:10.5px;"
                )
                tagrow.addWidget(tl)
            tagrow.addStretch(1)
            outer.addLayout(tagrow)

    def _toggle(self):
        self._expanded = not self._expanded
        self.full.setVisible(self._expanded)
        self.snip.setVisible(not self._expanded)

    def _toggle_pin(self):
        self.store.set_pinned(self.note.id, not self.note.pinned)
        self.changed.emit()

    def _view_raw(self):
        raw = self.store.read_raw(self.note)
        dlg = RawFileDialog(self.note, raw, self)
        dlg.exec()


class NotesView(QWidget):
    note_deleted = Signal(object)

    def __init__(self, store, mascot=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.mascot = mascot
        self._mode = "text"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # search box
        searchbox = QFrame()
        searchbox.setObjectName("card")
        sl = QHBoxLayout(searchbox)
        sl.setContentsMargins(9, 2, 9, 2)
        si = QLabel()
        si.setPixmap(icons.pixmap("search", COLORS["ink3"], 15))
        sl.addWidget(si)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes...")
        self.search.setStyleSheet("border:none; background:transparent;")
        # Debounce typing: collapse a burst of keystrokes into one list rebuild.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_timer.start)
        sl.addWidget(self.search, 1)
        lay.addWidget(searchbox)

        # Text / Meaning toggle
        toggle = QFrame()
        toggle.setObjectName("card")
        tl = QHBoxLayout(toggle)
        tl.setContentsMargins(3, 3, 3, 3)
        tl.setSpacing(3)
        self.text_btn = QPushButton("Text")
        self.meaning_btn = QPushButton("Meaning")
        for b in (self.text_btn, self.meaning_btn):
            b.setObjectName("pill")
            b.setCheckable(True)
        self.text_btn.setChecked(True)
        self.text_btn.clicked.connect(lambda: self._set_mode("text"))
        self.meaning_btn.clicked.connect(lambda: self._set_mode("meaning"))
        tl.addWidget(self.text_btn)
        tl.addWidget(self.meaning_btn)
        tl.addStretch(1)
        lay.addWidget(toggle)

        self.notice = QLabel("Meaning (semantic) search arrives in Phase 2 - showing Text matches.")
        self.notice.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        self.notice.hide()
        lay.addWidget(self.notice)

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        container = QWidget()
        container.setLayout(self.list_box)
        lay.addWidget(container)
        lay.addStretch(1)
        self.refresh()

    def _set_mode(self, mode: str):
        self._mode = mode
        self.text_btn.setChecked(mode == "text")
        self.meaning_btn.setChecked(mode == "meaning")
        self.notice.setVisible(mode == "meaning")
        self.refresh()

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search.text().strip()
        # Phase 1: both modes use keyword search (Meaning stubbed -> notice shown)
        notes = self.store.search(query) if query else self.store.all_active()
        for note in notes:
            card = NoteCard(note, self.store)
            card.changed.connect(self.refresh)
            card.deleted.connect(self._on_delete)
            self.list_box.addWidget(card)

    def _on_delete(self, note: Note):
        self.store.soft_delete(note.id)
        self.refresh()
        self.note_deleted.emit(note)
