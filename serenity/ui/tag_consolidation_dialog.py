"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The Notes tab "Tidy tags" modal - lists groups of variant / misspelled tags and
         consolidates each into one canonical tag across the whole vault.
Role:    On-demand maintenance UI for Job 5. Built lazily by NotesView when the user clicks
         "Tidy tags": it runs core.tagsync.suggest_tag_groups ONCE on open (never at idle /
         list render - tag clustering is deterministic + model-free, so there is no model to
         load), then shows one card per suggested group - an EDITABLE canonical (a combo of
         the group's members plus free-type, so the user can pick a different variant or type
         a brand-new canonical), the member tags as chips, the affected-note count, and
         Apply / Dismiss actions.

         Apply asks a clear confirm stating it renames N tags across M notes and CANNOT be
         undone (there is no trash-style undo for tag edits), then performs
         core.tagsync.consolidate_tag - rewriting every matching tag to the canonical across
         the active notes (case-insensitive, dedupe, other tags + order preserved; the note
         body is NEVER touched) and updating the settings tag-arsenal. It removes the row and
         emits `applied` so the parent NotesView refreshes its list. Dismiss is session-only
         ("not now" - the group re-appears on the next scan). When no variant groups are found,
         a clean empty-state is shown (also covers empty / one-tag vaults).

         All strings are emoji-free with a single "-" (never em-dash). The dialog is a modal
         (a scroll area is allowed - this is NOT the narrow ~348px dock).

Classes:
- TagConsolidationDialog - the modal: lazy detection on open, group rows, apply confirm, empty-state
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
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

from ..core.tagsync import consolidate_tag, suggest_tag_groups
from .theme import COLORS

# A variant chip elides to this pixel budget (dialog is >= 460px wide); the full tag is kept
# as the tooltip, so a long tag never widens the dialog and nothing is lost.
_CHIP_WIDTH = 180


class TagConsolidationDialog(QDialog):
    """Lists suggested groups of variant / misspelled tags with a confirmed, irreversible Apply.

    Detection happens ONCE here, in __init__ - the dialog only exists because the user clicked
    "Tidy tags", so "lazy on open" is satisfied. Tag clustering is deterministic + model-free
    (core.tagsync), so there is nothing to load and no degrade footnote to show. `notes_provider`
    is a zero-arg callable (store.all_active) yielding the live active notes to scan; `settings`
    supplies the tag-arsenal (so arsenal-only variants surface) and is updated on each Apply."""

    applied = Signal()   # fired after each successful Apply so the parent refreshes its list

    def __init__(self, store, settings, notes_provider=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.settings = settings
        self._notes_provider = notes_provider or (lambda: [])
        self.setWindowTitle("Tidy tags")
        self.setMinimumSize(460, 480)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        header = QLabel(
            "Suggested groups of variant or misspelled tags. Applying renames every matching "
            "tag to the canonical one across your notes. This cannot be undone."
        )
        header.setWordWrap(True)
        header.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
        lay.addWidget(header)

        # LAZY DETECTION ON OPEN. Pass the arsenal so a variant that lives ONLY in the settings
        # tag-arsenal (no note uses it yet) still surfaces for cleanup. The scan is O(n^2) over
        # the DISTINCT tag set - tiny for a personal vault (see core.tagsync).
        notes = list(self._notes_provider())
        arsenal = list(getattr(settings, "tags", []) or [])
        groups = suggest_tag_groups(notes, arsenal=arsenal)

        # Scrollable rows: this is a modal (not the 348px dock), so a scroll area is allowed -
        # MAX_GROUPS rows can exceed the dialog height.
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

        self._row_count = 0
        for group in groups:
            self.rows_box.addWidget(self._build_row(group))
            self._row_count += 1
        self.rows_box.addStretch(1)

        # EMPTY STATE: no groups (also covers empty / one-tag vaults). Added with stretch=1 and
        # the scroll area HIDDEN when empty, so the centered message fills the freed central area
        # instead of being pinned to the bottom (mirrors duplicates_dialog).
        self.empty_label = QLabel("No variant tags found.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color:{COLORS['ink3']}; font-size:12.5px;")
        lay.addWidget(self.empty_label, 1)
        self.empty_label.setVisible(self._row_count == 0)
        self.scroll.setVisible(self._row_count > 0)

        # Footnote (always-true; model-free, so no degrade / Phase-2 dead-end here).
        self.footnote = QLabel("Tags are grouped by spelling similarity.")
        self.footnote.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        lay.addWidget(self.footnote)

    # ------------------------------------------------------------------ rows --
    def _build_row(self, group) -> QFrame:
        """One card per group: editable canonical combo, member chips, count, Apply/Dismiss."""
        row = QFrame()
        row.setObjectName("card")
        # Stash the group on the row (Qt-safe plain attribute) so Apply can re-derive the
        # variant set against the user's chosen canonical.
        row._group = group
        box = QVBoxLayout(row)
        box.setContentsMargins(11, 10, 11, 10)
        box.setSpacing(6)

        # Row 1: canonical editor ("Keep as" + an editable combo of the members).
        canon_row = QHBoxLayout()
        canon_row.setSpacing(6)
        keep_lbl = QLabel("Keep as")
        keep_lbl.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        canon_row.addWidget(keep_lbl)
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(list(group.all_tags))      # canonical first, then variants
        combo.setCurrentText(group.canonical)
        canon_row.addWidget(combo, 1)
        box.addLayout(canon_row)
        row._combo = combo

        # Row 2: member chips (all members, same pill style).
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for member in group.all_tags:
            chip_row.addWidget(self._chip(member))
        chip_row.addStretch(1)
        box.addLayout(chip_row)

        # Row 3: affected-note count + Dismiss / Apply.
        actions = QHBoxLayout()
        actions.setSpacing(8)
        count = QLabel(f"{group.note_count} note(s) affected")
        count.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        actions.addWidget(count)
        actions.addStretch(1)
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("ghost")
        dismiss.setToolTip("Hide this group for now - it reappears on the next scan")
        dismiss.clicked.connect(lambda: self._dismiss_row(row))
        actions.addWidget(dismiss)
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(lambda: self._confirm_apply(row, combo))
        actions.addWidget(apply_btn)
        box.addLayout(actions)
        return row

    def _chip(self, tag: str) -> QLabel:
        """A single tag pill (reuses the card/dialog house style; no new theme colors)."""
        chip = QLabel(self._elide(tag, _CHIP_WIDTH))
        chip.setToolTip(tag)
        chip.setStyleSheet(
            f"color:{COLORS['ink2']}; border:1px solid {COLORS['line2']};"
            f"border-radius:6px; padding:1px 7px; font-size:10.5px;"
        )
        return chip

    def _elide(self, text: str, width: int) -> str:
        return QFontMetrics(self.font()).elidedText(text, Qt.ElideRight, width)

    # --------------------------------------------------------------- actions --
    def _dismiss_row(self, row: QFrame):
        """Session-only 'not now': drop this row. No persistence - re-scan next open."""
        self._remove_row(row)

    def _confirm_apply(self, row: QFrame, combo: QComboBox):
        """Confirm + perform an irreversible consolidation of this group's tags."""
        canonical = combo.currentText().strip()
        if not canonical:
            QMessageBox.information(self, "Tidy tags", "Enter a tag name to keep.")
            return

        group = row._group
        # Every member EXCEPT the exact chosen canonical is folded in. This is correct whether
        # the user kept the suggested canonical, picked a different member, or typed a brand-new
        # canonical (in which case ALL members become variants).
        variants = [t for t in group.all_tags if t != canonical]
        if not variants:
            # The chosen canonical is the sole member after the edit - nothing to fold.
            self._remove_row(row)
            return

        answer = QMessageBox.question(
            self,
            "Tidy tags",
            f"Rename {len(variants)} tag(s) to \"{canonical}\" across "
            f"{group.note_count} note(s)?\n\n"
            f"This rewrites the tags on those notes and cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return

        consolidate_tag(self.store, self.settings, canonical, variants)
        self._remove_row(row)
        self.applied.emit()

    def _remove_row(self, row: QFrame):
        """Drop a row widget and update the empty-state when none remain."""
        row.setParent(None)
        row.deleteLater()
        self._row_count = max(0, self._row_count - 1)
        if self._row_count == 0:
            self.empty_label.setVisible(True)
            self.scroll.setVisible(False)   # free the central area for the empty message
