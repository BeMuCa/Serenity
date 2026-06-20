"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Notes tab "Find duplicates" modal - lists near-duplicate / fragment pairs.
Role:    On-demand maintenance UI for Job 3. Built lazily by NotesView when the user clicks
         "Find duplicates": it runs core.dedup.find_duplicates ONCE on open (never at idle /
         list render), then shows one card per suggested pair - a kind badge, both note titles
         with a 1-line body preview, a score hint, and Merge / Dismiss actions.

         Merge asks a clear confirm (stating the other note goes to recoverable Trash),
         performs core.dedup.merge_notes (append body, union tags, soft-delete the dropped
         note - Trash IS the undo, never purged), removes the row, and emits `merged` so the
         parent NotesView refreshes its list. Dismiss is session-only ("not now" - the pair
         re-appears on the next scan). When no pairs are found, a clean empty-state is shown
         (also covers empty / one-note vaults, where find_duplicates returns []).

         Degrade: with no embedding model wired (this env / the user's machine today), the
         deterministic token path still produces rows - a small footnote says the scan used
         text overlap, so there is NO "Phase 2" dead-end. With a live index, detection uses
         meaning + text overlap. All strings are emoji-free with a single "-" (never em-dash).

Classes:
- DuplicatesDialog - the modal: lazy detection on open, pair rows, merge confirm, empty-state
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.dedup import default_keep, find_duplicates, merge_notes
from ..core.models import Note
from .theme import COLORS

# A pair-row title elides to this pixel budget (dialog is >= 460px wide; leave room for the
# row padding). The full title is kept as the tooltip, so nothing is lost.
_TITLE_WIDTH = 400
# Body preview length, mirroring NoteCard's snippet idea (strip + single-line + cap).
_PREVIEW_CHARS = 110


class DuplicatesDialog(QDialog):
    """Lists suggested near-duplicate / fragment pairs with a safe, recoverable Merge.

    Detection happens ONCE here, in __init__ - the dialog only exists because the user clicked
    "Find duplicates", so "lazy on open" is satisfied. `semantic` is the SemanticIndex-or-None
    NotesView holds (None => the deterministic token path runs); `notes_provider` is a zero-arg
    callable (store.all_active) yielding the live active notes to resolve pair ids against."""

    merged = Signal()   # fired after each successful merge so the parent refreshes its list

    def __init__(self, store, semantic=None, notes_provider=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.semantic = semantic
        self._notes_provider = notes_provider or (lambda: [])
        self.setWindowTitle("Find duplicates")
        self.setMinimumSize(460, 480)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        header = QLabel(
            "Suggested near-duplicate and fragment notes. Merging keeps one note and moves "
            "the other to Trash, where it can be restored."
        )
        header.setWordWrap(True)
        header.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
        lay.addWidget(header)

        # LAZY DETECTION ON OPEN. With no usable index, pass index=None so find_duplicates uses
        # the deterministic token path explicitly. The whole scan is O(n^2) over the vault -
        # fine for a personal vault of hundreds (see core.dedup).
        notes = list(self._notes_provider())
        by_id: dict[str, Note] = {n.id: n for n in notes}
        idx = semantic if getattr(semantic, "available", False) else None
        pairs = find_duplicates(notes, index=idx)

        # Scrollable rows: this is a modal (not the 348px dock), so a scroll area is allowed -
        # MAX_SUGGESTIONS rows can exceed the dialog height.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.rows_box = QVBoxLayout(inner)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(8)
        scroll.setWidget(inner)
        self.scroll = scroll
        lay.addWidget(scroll, 1)

        # Resolve each pair's ids to live Note objects; skip any pair whose note is gone.
        self._row_count = 0
        for pair in pairs:
            a = by_id.get(pair.a_id)
            b = by_id.get(pair.b_id)
            if a is None or b is None:
                continue
            self.rows_box.addWidget(self._build_row(pair, a, b))
            self._row_count += 1
        self.rows_box.addStretch(1)

        # EMPTY STATE: no resolved rows (also covers empty / one-note vaults). Added with
        # stretch=1 and the scroll area HIDDEN when empty (mirrors graph_view's pattern), so the
        # centered message fills the freed central area instead of being pinned to the bottom.
        self.empty_label = QLabel("No duplicates or fragments found.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color:{COLORS['ink3']}; font-size:12.5px;")
        lay.addWidget(self.empty_label, 1)
        self.empty_label.setVisible(self._row_count == 0)
        self.scroll.setVisible(self._row_count > 0)

        # DEGRADE FOOTNOTE: name the scan method so the token path is never a dead-end.
        foot = ("Scanned by meaning + text overlap." if idx is not None
                else "Scanned by text overlap (no embedding model).")
        self.footnote = QLabel(foot)
        self.footnote.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        lay.addWidget(self.footnote)

    # ------------------------------------------------------------------ rows --
    def _build_row(self, pair, a: Note, b: Note) -> QFrame:
        """One card per pair: kind badge, both titles + previews, score hint, Merge/Dismiss."""
        row = QFrame()
        row.setObjectName("card")
        box = QVBoxLayout(row)
        box.setContentsMargins(11, 10, 11, 10)
        box.setSpacing(6)

        is_fragment = pair.kind == "fragment"

        # Kind badge pill (reuses the tag-pill border look; no new theme colors).
        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        badge = QLabel("Fragment" if is_fragment else "Near-duplicate")
        badge.setStyleSheet(
            f"color:{COLORS['ink2']}; border:1px solid {COLORS['line2']};"
            f"border-radius:6px; padding:1px 7px; font-size:10.5px;"
        )
        badge_row.addWidget(badge)
        # Score hint, muted.
        pct = int(round(pair.score * 100))
        hint = QLabel(f"{pct}% contained" if is_fragment else f"{pct}% similar")
        hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        badge_row.addWidget(hint)
        badge_row.addStretch(1)
        box.addLayout(badge_row)

        # For a fragment, a_id is the longer note and b_id the shorter (the fragment): make the
        # relationship explicit.
        if is_fragment:
            sub = QLabel(f"\"{b.title}\" looks like part of \"{a.title}\"")
            sub.setWordWrap(True)
            sub.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11.5px;")
            box.addWidget(sub)

        box.addWidget(self._note_block(a))
        box.addWidget(self._note_block(b))

        # Optional "keep other" toggle: the UI may override the default kept note. For a
        # fragment the default kept is the longer note (a). For a duplicate it is default_keep.
        default_keep_id = a.id if is_fragment else default_keep(a, b)
        other = b if default_keep_id == a.id else a
        keep_other = QCheckBox(self._elide(f"Keep \"{other.title}\" instead", _TITLE_WIDTH))
        keep_other.setToolTip(f"Keep \"{other.title}\" instead")
        keep_other.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        box.addWidget(keep_other)

        # Buttons.
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("ghost")
        dismiss.setToolTip("Hide this pair for now - it will reappear on the next scan")
        dismiss.clicked.connect(lambda: self._dismiss_row(row))
        btns.addWidget(dismiss)
        merge = QPushButton("Merge")
        merge.setObjectName("primary")
        merge.clicked.connect(
            lambda: self._confirm_merge(a, b, default_keep_id, keep_other.isChecked(), row)
        )
        btns.addWidget(merge)
        box.addLayout(btns)
        return row

    def _note_block(self, note: Note) -> QWidget:
        """A note's title (bold-ish) + a 1-line elided body preview (full text as tooltip)."""
        block = QWidget()
        bl = QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(1)

        title = QLabel(self._elide(note.title or "Untitled", _TITLE_WIDTH))
        title.setToolTip(note.title or "Untitled")
        title.setStyleSheet("font-size:12.5px; font-weight:600;")
        bl.addWidget(title)

        raw = (note.body or "").strip().replace("\n", " ")
        snippet = (raw[:_PREVIEW_CHARS] + ("..." if len(raw) > _PREVIEW_CHARS else "")) or "(empty)"
        prev = QLabel(self._elide(snippet, _TITLE_WIDTH))
        prev.setToolTip(raw or "(empty)")
        prev.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        bl.addWidget(prev)
        return block

    def _elide(self, text: str, width: int) -> str:
        return QFontMetrics(self.font()).elidedText(text, Qt.ElideRight, width)

    # --------------------------------------------------------------- actions --
    def _dismiss_row(self, row: QFrame):
        """Session-only 'not now': drop this row. No persistence - re-scan next open."""
        self._remove_row(row)

    def _confirm_merge(self, a: Note, b: Note, default_keep_id: str,
                       keep_other: bool, row: QFrame):
        """Confirm + perform a safe, recoverable merge of this pair."""
        keep_id = (b.id if default_keep_id == a.id else a.id) if keep_other else default_keep_id
        drop_id = b.id if keep_id == a.id else a.id

        # Guard stale rows: another row may already have merged one of these notes away. A
        # merged-away note is either gone (get -> None) or sitting in Trash (deleted True) -
        # both mean "already merged"; do NOT re-merge a trashed note.
        keep = self.store.get(keep_id)
        drop = self.store.get(drop_id)
        if (keep is None or getattr(keep, "deleted", False)
                or drop is None or getattr(drop, "deleted", False)):
            QMessageBox.information(self, "Merge notes", "That note was already merged.")
            self._remove_row(row)
            return

        answer = QMessageBox.question(
            self,
            "Merge notes",
            f"Merge \"{drop.title}\" into \"{keep.title}\"?\n\n"
            f"\"{drop.title}\" will be moved to Trash and can be restored.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return

        merge_notes(self.store, keep_id, drop_id)
        self._remove_row(row)
        self.merged.emit()

    def _remove_row(self, row: QFrame):
        """Drop a row widget and update the empty-state when none remain."""
        row.setParent(None)
        row.deleteLater()
        self._row_count = max(0, self._row_count - 1)
        if self._row_count == 0:
            self.empty_label.setVisible(True)
            self.scroll.setVisible(False)   # free the central area for the empty message
