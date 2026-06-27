"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The Notes tab - Text/Meaning search toggle, color-accented note cards.
Role:    Renders NoteStore.all_active()/search() as cards with a left color accent +
         tint, pin-to-top, expand-to-read, "view raw .md" (file modal), and a lazy
         "Related" section (note-linking, Job 4). Meaning search ranks by semantic
         similarity when an embedding index is available, else shows a notice and
         falls back to Text; related notes degrade to a keyword/tag ranking the same way.

Classes:
- NoteCard - a note card (title, snippet, tags, expand, pin, view-raw + lazy Related chips
  built on first expand via core.search.related_notes; chips open a ReadNoteDialog)
- RawFileDialog - the view-raw-.md modal
- ReadNoteDialog - a lightweight read-only note viewer (title + body + its own Related chips,
  so the user can chain note -> note -> note without scrolling the narrow dock)
- NotesView - search box + Text/Meaning toggle + "Ask" (Job 13 RAG), "Find duplicates" (Job 3)
  and "Tidy tags" (Job 5) actions (each opens its dialog lazily) + scrollable list
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
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
from ..core.search import related_notes, semantic_search
from . import icons
from .theme import COLORS, NOTE_COLOR_HEX, pill_label

# Chips are stacked one-per-row in the narrow (~348px) dock; cap so the expanded card
# stays compact and the related list reads as a quick "see also", not a second list.
_RELATED_TOP_K = 4
# Pixel budget an ellipsized chip title fits into: the in-card chip's TEXT region at the fixed
# 348px dock - card-content ~302px minus the ghost button's ~22px padding+border, less a few px
# of safety for font-metrics rounding. ReadNoteDialog reuses this in a wider (>=420px) dialog,
# so there it just elides a little earlier - harmless.
_CHIP_WIDTH = 270


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


class ReadNoteDialog(QDialog):
    """A lightweight read-only viewer for a related note (title + body + its own Related chips).

    The narrow (~348px) dock has no QScrollArea, so navigating to a related note by scrolling
    is unreliable; instead a chip opens this self-contained dialog. Each related chip here opens
    ANOTHER ReadNoteDialog, so the user can chain note -> note -> note regardless of the list's
    current filter/sort. Related is computed eagerly here (the user explicitly opened the note);
    with no embedding index that is the deterministic keyword/tag fallback, no model load."""

    def __init__(self, note: Note, semantic=None, notes_provider=None, parent=None):
        super().__init__(parent)
        self.note = note
        self.semantic = semantic
        self._notes_provider = notes_provider
        self.setWindowTitle(note.title or "Note")
        self.setMinimumSize(420, 360)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self.title_label = QLabel(note.title or "Note")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size:15px; font-weight:600;")
        lay.addWidget(self.title_label)

        if note.tags:
            tagrow = QHBoxLayout()
            tagrow.setSpacing(6)
            for t in note.tags:
                tagrow.addWidget(_tag_pill(t))
            tagrow.addStretch(1)
            lay.addLayout(tagrow)

        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlainText(note.body or "")
        self.body.setStyleSheet("font-size:12.5px;")
        lay.addWidget(self.body, 1)

        # This note's own Related section, built the same way as the card's (chainable).
        self.related_wrap = QWidget()
        self.related_box = QVBoxLayout(self.related_wrap)
        self.related_box.setContentsMargins(0, 0, 0, 0)
        self.related_box.setSpacing(4)
        notes = self._notes_provider() if self._notes_provider else []
        # Index-first so related() queries a FRESH store (the "caller indexes first" contract
        # that SemanticIndex.related relies on, mirroring NotesView.refresh). index() is
        # incremental (unchanged notes skipped, deleted pruned), so it is cheap on open.
        if notes and getattr(self.semantic, "available", False):
            self.semantic.index(notes)
        rel = related_notes(note, notes, index=self.semantic, top_k=_RELATED_TOP_K)
        if rel:
            self.related_box.addWidget(_related_header())
            for r in rel:
                self.related_box.addWidget(_related_chip(r, self._open_related))
        else:
            self.related_wrap.hide()
        lay.addWidget(self.related_wrap)

    def _open_related(self, rel_note: Note):
        dlg = ReadNoteDialog(rel_note, semantic=self.semantic,
                             notes_provider=self._notes_provider, parent=self)
        dlg.exec()


def _tag_pill(tag: str) -> QLabel:
    """A single #tag pill, styled to match the card/dialog house style (no new colors)."""
    return pill_label(f"#{tag}", border=COLORS["line"])


def _note_link_chip(note: Note, on_click, *, height: int = 24,
                    width: int = _CHIP_WIDTH) -> QPushButton:
    """A clickable, ellipsized note-link chip (a soft link to a note).

    The full title is kept as the tooltip; the visible label is elided to `width` so a long
    title never widens its container. objectName 'ghost' reuses the theme's secondary-action
    style so the chip reads as a soft link, not a primary button. Shared by the in-dock
    Related chip (Job 4) and AskDialog's citation chips (Job 13), which differ only in the
    fixed height and elide budget (the modal is wider than the dock)."""
    title = note.title or "Note"
    chip = QPushButton()
    chip.setObjectName("ghost")
    chip.setToolTip(title)
    chip.setFixedHeight(height)
    chip.setCursor(Qt.PointingHandCursor)
    chip.setStyleSheet("text-align:left;")
    elided = QFontMetrics(chip.font()).elidedText(title, Qt.ElideRight, width)
    chip.setText(elided)
    chip.clicked.connect(lambda: on_click(note))
    return chip


def _related_chip(rel_note: Note, on_click) -> QPushButton:
    """A clickable, ellipsized 'related note' chip (one per row at the narrow dock width)."""
    return _note_link_chip(rel_note, on_click)


def _related_header() -> QLabel:
    """The muted 'Related' section header (reuses the theme's #sectLabel style)."""
    lab = QLabel("Related")
    lab.setObjectName("sectLabel")
    return lab


class NoteCard(QFrame):
    changed = Signal()
    deleted = Signal(object)
    expand_requested = Signal(str)   # note id -> shell opens the large pop-out editor (Task 10)

    def __init__(self, note: Note, store, semantic=None, notes_provider=None, parent=None):
        super().__init__(parent)
        self.note = note
        self.store = store
        # Deps for the lazy Related section (Job 4). `semantic` is the SemanticIndex-or-None
        # NotesView holds; `notes_provider` is a zero-arg callable (store.all_active) yielding
        # the live active notes to re-project onto. NEITHER is touched until first expand.
        self.semantic = semantic
        self._notes_provider = notes_provider
        self._related_built = False
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

        self.expand_btn = QPushButton()
        self.expand_btn.setObjectName("iconbtn")
        self.expand_btn.setIcon(icons.icon("expand", COLORS["ink3"], 12))
        self.expand_btn.setFixedSize(22, 22)
        self.expand_btn.setToolTip("Open in a large editor")
        self.expand_btn.clicked.connect(lambda: self.expand_requested.emit(self.note.id))
        top.addWidget(self.expand_btn)

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

        # Lazy "Related" section: an empty, hidden container in the expanded read area. It is
        # populated on the FIRST expand (_ensure_related) - never on plain list render, and it
        # never touches the embedding model at idle. Sits below the full body.
        self.related_wrap = QWidget()
        self.related_box = QVBoxLayout(self.related_wrap)
        self.related_box.setContentsMargins(0, 4, 0, 0)
        self.related_box.setSpacing(4)
        self.related_wrap.hide()
        outer.addWidget(self.related_wrap)

        if note.tags:
            tagrow = QHBoxLayout()
            tagrow.setSpacing(6)
            for t in note.tags:
                tagrow.addWidget(_tag_pill(t))
            tagrow.addStretch(1)
            outer.addLayout(tagrow)

    def _toggle(self):
        self._expanded = not self._expanded
        self.full.setVisible(self._expanded)
        self.snip.setVisible(not self._expanded)
        if self._expanded:
            # Compute related notes lazily, only the first time this card is opened.
            self._ensure_related()

    def _ensure_related(self):
        """Build the Related chips on first expand. No-op afterwards; never on plain render.

        Asks core.search.related_notes (which degrades to the keyword/tag ranking when no
        embedding index is available, so chips still appear with no model). If there is
        nothing related, the section stays hidden - no empty 'Related: none' dead-end."""
        if self._related_built:
            return
        self._related_built = True
        notes = self._notes_provider() if self._notes_provider else []
        # Index-first so the chips reflect the LIVE vault, not a store left stale from an
        # earlier Meaning-mode visit (notes added/edited since would otherwise be dropped).
        # index() is incremental, so it stays cheap; indexing happens only on EXPAND here,
        # never on plain list render - so the "no model load on render" invariant holds.
        if notes and getattr(self.semantic, "available", False):
            self.semantic.index(notes)
        rel = related_notes(self.note, notes, index=self.semantic, top_k=_RELATED_TOP_K)
        if not rel:
            self.related_wrap.hide()
            return
        self.related_box.addWidget(_related_header())
        for r in rel:
            self.related_box.addWidget(_related_chip(r, self._open_related))
        self.related_wrap.show()

    def _open_related(self, rel_note: Note):
        """Open a related note in a self-contained read dialog (chainable, robust to the list)."""
        dlg = ReadNoteDialog(rel_note, semantic=self.semantic,
                             notes_provider=self._notes_provider, parent=self)
        dlg.exec()

    def _toggle_pin(self):
        self.store.set_pinned(self.note.id, not self.note.pinned)
        self.changed.emit()

    def _view_raw(self):
        raw = self.store.read_raw(self.note)
        dlg = RawFileDialog(self.note, raw, self)
        dlg.exec()


class NotesView(QWidget):
    note_deleted = Signal(object)
    expand_requested = Signal(str)   # bubbled up from a card's ⤢ -> shell.open_expanded (Task 10)

    def __init__(self, store, semantic=None, settings=None, llm=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.semantic = semantic   # a phase2_stubs.SemanticIndex, or None / unavailable
        # The settings object (for the "Tidy tags" arsenal update, Job 5). Optional so existing
        # callers/tests that pass only (store, semantic) keep working; the Tidy-tags dialog reads
        # settings.tags and writes the arsenal, so it is threaded through from the shell.
        self.settings = settings
        # The LLMEngine-or-None for the "Ask" RAG dialog (Job 13). Optional so existing
        # callers/tests that pass only (store, semantic) keep working; None / unavailable means
        # the Ask dialog degrades to showing retrieved notes (no synthesized answer).
        self.llm = llm
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

        # Maintenance actions on their OWN row below the toggle. The narrow ~348px dock (real
        # inner width ~324px) cannot fit Text/Meaning + two ghost buttons on one line without
        # cramming / clipping the trailing label, so the two on-demand actions get a dedicated
        # right-aligned row. Detection (and any model load) happens ONLY when each dialog opens -
        # never here / at idle / on list render. objectName "ghost" reuses the secondary style.
        maint = QHBoxLayout()
        maint.setContentsMargins(0, 0, 0, 0)
        maint.setSpacing(6)
        maint.addStretch(1)
        # "Ask" (Job 13 RAG) sits with the other on-demand actions. Lazy: nothing runs until
        # the dialog is open and the user asks - no retrieval / model load here / at idle.
        self.ask_btn = QPushButton("Ask")
        self.ask_btn.setObjectName("ghost")
        self.ask_btn.setToolTip("Ask a question answered from your notes")
        self.ask_btn.clicked.connect(self._open_ask)
        maint.addWidget(self.ask_btn)
        self.dedup_btn = QPushButton("Find duplicates")
        self.dedup_btn.setObjectName("ghost")
        self.dedup_btn.setToolTip("Scan notes for near-duplicates and fragments")
        self.dedup_btn.clicked.connect(self._open_duplicates)
        maint.addWidget(self.dedup_btn)
        # "Tidy tags" (Job 5) mirrors the dedup button. Tag clustering is deterministic +
        # model-free, so detection happens ONLY when the dialog opens.
        self.tidy_btn = QPushButton("Tidy tags")
        self.tidy_btn.setObjectName("ghost")
        self.tidy_btn.setToolTip("Find and merge variant or misspelled tags")
        self.tidy_btn.clicked.connect(self._open_tag_consolidation)
        maint.addWidget(self.tidy_btn)
        lay.addLayout(maint)

        self.notice = QLabel("Meaning search needs the optional embedding model - showing Text matches.")
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
        self._update_notice()
        self.refresh()

    def _semantic_on(self) -> bool:
        """True only when a usable embedding index is wired (else degrade to Text)."""
        return self.semantic is not None and getattr(self.semantic, "available", False)

    def _update_notice(self):
        # The notice only appears in Meaning mode when no embedding model is available.
        self.notice.setVisible(self._mode == "meaning" and not self._semantic_on())

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search.text().strip()
        if self._mode == "meaning" and self._semantic_on():
            # Lazy + incremental: embed only changed notes (the model loads on first use
            # here; background/break-time re-indexing is a later job), then rank by meaning.
            active = self.store.all_active()
            self.semantic.index(active)
            notes = semantic_search(active, query, index=self.semantic) if query else active
        else:
            notes = self.store.search(query) if query else self.store.all_active()
        for note in notes:
            # Related is computed lazily on expand (NoteCard._ensure_related), so plain list
            # render stays as cheap as before and never loads the embedding model. The card
            # gets the SemanticIndex + a live-notes provider so it can re-project on expand.
            card = NoteCard(note, self.store, semantic=self.semantic,
                            notes_provider=self.store.all_active)
            card.changed.connect(self.refresh)
            card.deleted.connect(self._on_delete)
            card.expand_requested.connect(self.expand_requested)
            self.list_box.addWidget(card)

    def _on_delete(self, note: Note):
        self.store.soft_delete(note.id)
        self.refresh()
        self.note_deleted.emit(note)

    def open_note(self, note: Note):
        """Open a note in the read dialog (used by the Todos tab's prep/protocol link).

        Re-fetches by id so a freshly-created linked note is read from the live store, then
        reuses the same ReadNoteDialog the Related chips use - consistent with the dock's
        note-to-note navigation and robust to the narrow, scroll-less list."""
        self.refresh()
        fresh = self.store.get(note.id) or note
        dlg = ReadNoteDialog(fresh, semantic=self.semantic,
                             notes_provider=self.store.all_active, parent=self)
        dlg.exec()

    def _open_ask(self):
        """Open the Ask-your-vault RAG modal (Job 13). Lazy: nothing runs here - retrieval,
        any embedding-model load and the LLM call all happen inside the dialog when the user
        clicks Ask. The dialog gets the SemanticIndex (or None), the LLMEngine (or None), and a
        live-notes provider so each ask scans the current vault; it degrades to showing the
        retrieved notes when no answer model is available."""
        from .ask_dialog import AskDialog

        dlg = AskDialog(semantic=self.semantic, llm=self.llm,
                        notes_provider=self.store.all_active, parent=self)
        dlg.exec()

    def _open_duplicates(self):
        """Open the Find-duplicates modal. Lazy: detection + any model load happen only inside
        the dialog (on open), never here / at idle / on list render.

        Index-first ONLY when a usable embedding index is wired, so the semantic path scans a
        FRESH store - cheap + incremental, exactly like refresh()'s Meaning branch. With no
        model this is skipped and the dialog uses the deterministic token path (index=None)."""
        from .duplicates_dialog import DuplicatesDialog

        semantic = self.semantic if self._semantic_on() else None
        if semantic is not None:
            semantic.index(self.store.all_active())
        dlg = DuplicatesDialog(self.store, semantic,
                               notes_provider=self.store.all_active, parent=self)
        dlg.merged.connect(self.refresh)   # refresh the list after any merge
        dlg.exec()
        self.refresh()                     # also refresh on close (covers dismiss-only sessions)

    def _open_tag_consolidation(self):
        """Open the Tidy-tags modal. Lazy: tag detection happens only inside the dialog (on
        open), never here / at idle / on list render. Tag clustering is deterministic + model-
        free, so there is no index to warm first (unlike _open_duplicates' Meaning path)."""
        from .tag_consolidation_dialog import TagConsolidationDialog

        dlg = TagConsolidationDialog(self.store, self.settings,
                                     notes_provider=self.store.all_active, parent=self)
        dlg.applied.connect(self.refresh)   # refresh the list after any consolidation
        dlg.exec()
        self.refresh()                      # also refresh on close (covers dismiss-only sessions)
