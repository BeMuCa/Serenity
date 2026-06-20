"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Notes tab "Ask" modal - ask your vault a question, get a grounded answer + cited
         source notes (Ask-Your-Vault RAG, Job 13).
Role:    On-demand UI for core.rag. Built lazily by NotesView when the user clicks "Ask" (next
         to Find-duplicates / Tidy-tags): a question input + Ask button, the synthesized answer
         text, and clickable source-note citation chips. NOTHING runs until the user asks -
         retrieval + any embedding-model load + the LLM call all happen inside _ask(), never on
         open / at idle / on list render. Each ask runs core.rag.answer_question (or a wired
         WarmCache.ask) over the live vault, index-first so a live SemanticIndex queries a
         fresh store (the "caller indexes first" contract, exactly like NotesView.refresh).

         Citation chips reuse the Job-4 ReadNoteDialog (from notes_view), so a cited note opens
         the same chainable read view as a Related chip - note -> note -> note.

         Degrade (never a dead-end): with no usable LLM the answer area shows a clear
         "no answer model available - showing related notes" line and the retrieved notes
         render as citation chips, so the user still gets the relevant notes. With no embedding
         model the retrieval silently falls back to keyword search (core.rag handles it). All
         strings are emoji-free with a single "-" (never an em-dash).

Classes:
- AskDialog - the modal: question input + Ask, answer text, source citation chips, degrade line
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Note
from ..core.rag import answer_question
from .theme import COLORS

# A citation chip's title elides to this pixel budget (the dialog is >= 460px wide; leave room
# for the row padding). The full title is kept as the tooltip, so nothing is lost.
_CHIP_WIDTH = 400


class AskDialog(QDialog):
    """Ask your vault a question; show a grounded answer + clickable source-note citations.

    `semantic` is the SemanticIndex-or-None NotesView holds (None / unavailable => keyword
    retrieval inside core.rag); `llm` is the LLMEngine-or-None (None / unavailable => the
    sources-only degrade path); `notes_provider` is a zero-arg callable (store.all_active)
    yielding the live active notes. Nothing runs in __init__ beyond building the empty form -
    retrieval + the LLM call happen only when the user clicks Ask (or presses Enter)."""

    def __init__(self, semantic=None, llm=None, notes_provider=None,
                 cache=None, parent=None):
        super().__init__(parent)
        self.semantic = semantic
        self.llm = llm
        self._notes_provider = notes_provider or (lambda: [])
        # An optional warm-cache (core.rag.WarmCache). When wired, ask() serves precomputed
        # answers for unchanged sources; when None, every ask computes live via answer_question.
        self.cache = cache
        self.setWindowTitle("Ask your notes")
        self.setMinimumSize(460, 420)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        header = QLabel(
            "Ask a question and get an answer grounded in your own notes, with the source "
            "notes it used."
        )
        header.setWordWrap(True)
        header.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
        lay.addWidget(header)

        # Question input + Ask button on one row.
        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        self.question = QLineEdit()
        self.question.setPlaceholderText("e.g. Where did I park at the airport?")
        self.question.returnPressed.connect(self._ask)
        qrow.addWidget(self.question, 1)
        self.ask_btn = QPushButton("Ask")
        self.ask_btn.setObjectName("primary")
        self.ask_btn.clicked.connect(self._ask)
        qrow.addWidget(self.ask_btn)
        lay.addLayout(qrow)

        # The answer area (filled on ask). Starts on a quiet prompt so the dialog is not blank.
        self.answer_label = QLabel("Ask a question to search your notes.")
        self.answer_label.setWordWrap(True)
        self.answer_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.answer_label.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12.5px;")
        lay.addWidget(self.answer_label)

        # The degrade line (shown only when there is no usable LLM and we fell back to notes).
        self.degrade_label = QLabel(
            "No answer model available - showing related notes."
        )
        self.degrade_label.setWordWrap(True)
        self.degrade_label.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        self.degrade_label.hide()
        lay.addWidget(self.degrade_label)

        # Scrollable citation chips ("Sources"): this is a modal (not the 348px dock), so a
        # scroll area is allowed. Hidden until an ask produces sources.
        self.sources_header = QLabel("Sources")
        self.sources_header.setObjectName("sectLabel")
        self.sources_header.hide()
        lay.addWidget(self.sources_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.chips_box = QVBoxLayout(inner)
        self.chips_box.setContentsMargins(0, 0, 0, 0)
        self.chips_box.setSpacing(4)
        scroll.setWidget(inner)
        self.scroll = scroll
        lay.addWidget(scroll, 1)

    # ------------------------------------------------------------------ ask --
    def _ask(self):
        """Run RAG for the typed question over the LIVE vault and render answer + citations.

        Lazy: this is the ONLY place retrieval / a model load / the LLM call happen. Index-
        first when a usable embedding index is wired, so the semantic path queries a fresh
        store (the same contract as NotesView.refresh). Degrades to keyword retrieval / a
        sources-only result entirely inside core.rag - the UI just renders whatever it gets."""
        q = self.question.text().strip()
        if not q:
            return
        notes = list(self._notes_provider())
        # Index-first ONLY when a usable embedding index is wired (cheap + incremental), so the
        # semantic retrieval scans a fresh store. With no model this is skipped (keyword path).
        if notes and getattr(self.semantic, "available", False):
            self.semantic.index(notes)

        if self.cache is not None:
            result = self.cache.ask(q, notes, index=self.semantic, llm=self.llm)
        else:
            result = answer_question(q, notes, index=self.semantic, llm=self.llm)

        self._render(result, notes)

    def _render(self, result, notes: list[Note]):
        """Show the answer (or the degrade line) + the source citation chips."""
        self._clear_chips()
        by_id = {n.id: n for n in notes}
        cited = [by_id[i] for i in result.sources if i in by_id]

        if result.answer:
            self.answer_label.setText(result.answer)
            self.answer_label.setStyleSheet(
                f"color:{COLORS['ink']}; font-size:12.5px;")
            self.degrade_label.hide()
        elif cited:
            # Degrade: no synthesized answer, but we retrieved notes - show them, no dead-end.
            self.answer_label.setText("Here are the notes most related to your question:")
            self.answer_label.setStyleSheet(
                f"color:{COLORS['ink2']}; font-size:12.5px;")
            # The "no model" line is the reason there is no answer (only when no usable LLM).
            self.degrade_label.setVisible(
                self.llm is None or not getattr(self.llm, "available", False))
        else:
            # Nothing retrieved at all (empty vault / no match).
            self.answer_label.setText("No matching notes found.")
            self.answer_label.setStyleSheet(
                f"color:{COLORS['ink3']}; font-size:12.5px;")
            self.degrade_label.hide()

        for note in cited:
            self.chips_box.addWidget(self._citation_chip(note))
        self.chips_box.addStretch(1)
        has_sources = bool(cited)
        self.sources_header.setVisible(has_sources)
        self.scroll.setVisible(has_sources)

    def _citation_chip(self, note: Note) -> QPushButton:
        """A clickable source-note chip; opens the chainable Job-4 ReadNoteDialog on click.

        The full title is the tooltip; the visible label elides to _CHIP_WIDTH. objectName
        'ghost' reuses the theme's secondary-action style so it reads as a soft link."""
        title = note.title or "Note"
        chip = QPushButton()
        chip.setObjectName("ghost")
        chip.setToolTip(title)
        chip.setFixedHeight(26)
        chip.setCursor(Qt.PointingHandCursor)
        chip.setStyleSheet("text-align:left;")
        elided = QFontMetrics(chip.font()).elidedText(title, Qt.ElideRight, _CHIP_WIDTH)
        chip.setText(elided)
        chip.clicked.connect(lambda: self._open_source(note))
        return chip

    def _open_source(self, note: Note):
        """Open a cited note in the chainable read dialog (reuses Job 4's ReadNoteDialog)."""
        from .notes_view import ReadNoteDialog

        dlg = ReadNoteDialog(note, semantic=self.semantic,
                             notes_provider=self._notes_provider, parent=self)
        dlg.exec()

    def _clear_chips(self):
        """Drop any chips from a previous ask before rendering the new result."""
        while self.chips_box.count():
            item = self.chips_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
