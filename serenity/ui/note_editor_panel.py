"""
============================================================
Author:  Berk
Created: 2026-06-27
Purpose: NoteEditorPanel - the plain-text body editor + raw-YAML front-matter sub-editor
         that lives inside an ExpandedPanel for the Notes-expand pop-out.
Role:    The thin UI layer of Notes-expand: it RENDERS choices and WIRES signals, but every
         fail-safe decision is delegated to the Qt-free core.note_draft (draft write, the
         strict commit gate, content-keyed recover, external-change detection, the promote
         orchestration). It owns only the widgets, the debounce timer, the dirty indicator,
         and the QMessageBox prompts that surface note_draft's outcomes.

Classes:
- NoteEditorPanel - body QPlainTextEdit + toggled raw-YAML QPlainTextEdit + Save / Front-matter
  / Open-in-OS buttons + dirty indicator + child single-shot debounce timer; committed = Signal(str)
============================================================
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import note_draft as nd
from ..core.note_store import parse_markdown, serialize
from ..core.paths import atomic_write_text
from . import platform_win
from .theme import COLORS

# Debounce: collapse a burst of keystrokes into one .draft write (mirrors the notes_view idiom).
_DEBOUNCE_MS = 600


def _frontmatter_text(note) -> str:
    """The loaded note's front-matter as raw YAML text (no fences), byte-identical to the store.

    Single-sourced from note_store.serialize so the seeded sub-editor matches exactly what the
    store writes on disk; we just slice the text between the two `---` fences (P1-6)."""
    full = serialize(note)
    # serialize() shape: "---\n{front}\n---\n\n{body}\n"
    inner = full.split("---\n", 1)[1]      # drop the opening fence
    return inner.split("\n---", 1)[0]      # up to the closing fence


class NoteEditorPanel(QWidget):
    """The note editor hosted inside an ExpandedPanel.

    Body edits live in the main editor; a Front-matter button reveals an editable raw-YAML
    sub-editor (seeded from the loaded note on open). Edits restart a debounce timer that writes
    the .draft sidecar; Ctrl+S / close->Save promote the draft to the durable .md. All decisions
    are delegated to core.note_draft; this widget only renders the outcomes."""

    committed = Signal(str)        # note id, after a successful durable .md write
    closeRequested = Signal()      # the panel asks its host (ExpandedPanel) to close it

    def __init__(self, note, store, parent=None):
        super().__init__(parent)
        self.note = note
        self.store = store
        self.note_id = note.id
        self._dirty = False
        # whether the user ever opened/edited the FM sub-editor: when False, promote() carries the
        # store's metadata (pin/color/tags) untouched instead of re-reading the seeded buffer.
        self._fm_edited = False
        # the load-time content hash of the on-disk .md: the baseline for external-change detection
        # (content-keyed, never mtime - P2-8). Refreshed after any reload from disk (P2-14).
        self._baseline = nd.content_hash(self._read_md_or_serialize())

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        # header row: dirty indicator + Save / Front-matter / Open-in-OS
        header = QHBoxLayout()
        header.setSpacing(8)
        self._dirty_dot = QLabel("")
        self._dirty_dot.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        header.addWidget(self._dirty_dot)
        header.addStretch(1)

        self._fm_btn = QPushButton("Front-matter")
        self._fm_btn.setObjectName("ghost")
        self._fm_btn.setCheckable(True)
        self._fm_btn.setToolTip("Show / hide the raw YAML front-matter")
        self._fm_btn.toggled.connect(self._show_frontmatter)
        header.addWidget(self._fm_btn)

        self._os_btn = QPushButton("Open in OS editor")
        self._os_btn.setObjectName("ghost")
        self._os_btn.setToolTip("Hand the .md file off to your default editor")
        self._os_btn.clicked.connect(self.open_in_os)
        header.addWidget(self._os_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primary")
        self._save_btn.setToolTip("Save (Ctrl+S)")
        self._save_btn.clicked.connect(self.commit)
        header.addWidget(self._save_btn)
        root.addLayout(header)

        # inline error / notice line (validation failures, write-locks, source-missing, etc.)
        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color:#fca5a5; font-size:11.5px;")
        self._error.hide()
        root.addWidget(self._error)

        # the body editor (plain text - no live markdown render, per the brainstorm)
        self.body = QPlainTextEdit()
        self.body.setPlainText(note.body or "")
        self.body.textChanged.connect(self._mark_dirty)
        root.addWidget(self.body, 1)

        # the raw-YAML front-matter sub-editor, seeded from the loaded note, hidden until toggled
        self.fm_edit = QPlainTextEdit()
        self.fm_edit.setPlainText(_frontmatter_text(note))
        self.fm_edit.setStyleSheet("font-family:Consolas,monospace; font-size:11.5px;")
        self.fm_edit.textChanged.connect(self._on_fm_changed)
        self.fm_edit.hide()
        root.addWidget(self.fm_edit)

        # CHILD single-shot debounce timer (P2-3): stop() is the first line of commit/discard/close.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._flush_draft)

        # open-time crash-recovery offer (content-keyed; prompts only on a real divergence).
        self._offer_recovery()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _read_md_or_serialize(self) -> str:
        try:
            return Path(self.note.path).read_text(encoding="utf-8")
        except OSError:
            return serialize(self.note)

    def _set_error(self, msg: str) -> None:
        self._error.setText(msg)
        self._error.setVisible(bool(msg))

    def _clear_error(self) -> None:
        self._error.clear()
        self._error.hide()

    def _show_frontmatter(self, on: bool) -> None:
        if self._fm_btn.isChecked() != on:
            self._fm_btn.setChecked(on)
        self.fm_edit.setVisible(on)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._dirty_dot.setText("● Unsaved")   # ● Unsaved
        self._dirty_dot.setStyleSheet(f"color:{COLORS['accent']}; font-size:11px;")
        self._timer.start()

    def _on_fm_changed(self) -> None:
        self._fm_edited = True
        self._mark_dirty()

    def _flush_draft(self) -> None:
        """Debounce slot: write the .draft sidecar. write_draft never raises (P2-5); on a
        False result flip the dirty indicator into a visible 'couldn't autosave' warning."""
        ok = nd.write_draft(self.note.path, self.fm_edit.toPlainText(), self.body.toPlainText())
        if ok:
            # our own write - advance the baseline is NOT done here (baseline tracks the .md, not
            # the .draft); the dirty dot stays until commit.
            self._dirty_dot.setText("● Unsaved")
        else:
            self._dirty_dot.setText("⚠ Couldn't autosave")  # ⚠
            self._dirty_dot.setStyleSheet("color:#fca5a5; font-size:11px;")

    def _clear_dirty(self) -> None:
        self._dirty = False
        self._dirty_dot.setText("")
        self._dirty_dot.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")

    # ------------------------------------------------------------------ #
    # open-time recovery (P2-2)
    # ------------------------------------------------------------------ #
    def _offer_recovery(self) -> None:
        res = nd.recover(self.note.path)
        if res.status != "recoverable":
            return
        reply = QMessageBox.question(
            self, "Recover unsaved draft?",
            "An unsaved draft of this note was found.\n\nRecover the draft?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            _, body = parse_markdown(res.draft_text or "")
            # load the draft into the editors; FM text is re-sliced from the draft verbatim.
            self.fm_edit.setPlainText(self._fm_from_text(res.draft_text or ""))
            self.body.setPlainText(body)
            self._fm_edited = True
            self._mark_dirty()
        else:
            # declining a recovery offer IS a discard (P2-2). A real OSError keeps the panel
            # open with an inline error rather than a false 'discarded'.
            try:
                nd.discard(self.note.path)
            except OSError as e:
                self._set_error(f"Couldn't discard the draft: {e}")

    @staticmethod
    def _fm_from_text(md_text: str) -> str:
        inner = md_text.split("---\n", 1)
        if len(inner) < 2:
            return ""
        return inner[1].split("\n---", 1)[0]

    # ------------------------------------------------------------------ #
    # commit (Ctrl+S / close->Save)
    # ------------------------------------------------------------------ #
    def commit(self) -> bool:
        """Promote the draft to the durable .md. Returns True on a successful commit.

        stop() the debounce FIRST (P2-3), then promote() in try/except so every typed
        note_draft error renders as an inline message and the panel stays open."""
        self._timer.stop()
        self._clear_error()
        # external-change guard at commit time too, not just on focus-in (P2-8): a write that
        # kept focus the whole time would otherwise blindly clobber an outside-Serenity edit.
        if not self._external_ok_to_commit():
            return False
        # capture the store's deleted flag before the write so we can acknowledge a false->true
        # flip made via the FM editor afterwards (P3-2). The note may already be gone (purged).
        live = self.store.get(self.note_id)
        was_deleted = bool(live.deleted) if live is not None else False
        try:
            nd.promote(
                self.store, self.note_id,
                self.fm_edit.toPlainText(), self.body.toPlainText(),
                self._fm_edited,
            )
        except nd.NoteDraftInvalid as e:
            self._set_error(str(e))                 # bad front-matter - keep open (P1-1)
            return False
        except nd.NoteSourceMissing:
            self._save_as_new()                     # purged under us - offer save-as-new (P1-10)
            return False
        except (nd.NoteWriteFailed, OSError) as e:
            # external lock / permission - keep the draft + panel open, inline message (P2-10)
            self._set_error(f"Couldn't save: {e}")
            return False
        # success: refresh our in-memory note + baseline, drop the dirty state, announce.
        self.note = self.store.get(self.note_id) or self.note
        self._baseline = nd.content_hash(self._read_md_or_serialize())
        self._clear_dirty()
        # deleted flipped false->true via the FM editor -> a non-blocking acknowledgment, never a
        # refusal (Trash is recoverable from the Trash tab) - P3-2.
        if not was_deleted and self.note.deleted:
            self._set_error("Moved to Trash - restore it from the Trash tab.")
        self.committed.emit(self.note_id)
        return True

    def _save_as_new(self) -> None:
        """The note's .md was purged under the panel; offer to keep the edits as a new note."""
        reply = QMessageBox.question(
            self, "Note no longer exists",
            "This note was deleted while you were editing it.\n\nSave your edits as a NEW note?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            self._set_error("The note no longer exists on disk.")
            return
        new = self.store.create(self.note.title or "Untitled", self.body.toPlainText(),
                                tags=list(self.note.tags), color=self.note.color)
        # the old draft is keyed to the gone note's path; drop it and re-home onto the new note.
        try:
            nd.discard(self.note.path)
        except OSError:
            pass
        self.note = new
        self.note_id = new.id
        self.fm_edit.setPlainText(_frontmatter_text(new))
        self._baseline = nd.content_hash(self._read_md_or_serialize())
        self._clear_dirty()
        self.committed.emit(self.note_id)

    # ------------------------------------------------------------------ #
    # close (X / Esc, routed from ExpandedPanel.closeRequested) - P2-12
    # ------------------------------------------------------------------ #
    def handle_close(self) -> bool:
        """Resolve a close request. Returns True if the host may close the panel.

        A clean panel closes immediately and NEVER deletes the draft (a sibling surface may own
        it). A dirty panel prompts Save/Discard/Cancel (default Cancel)."""
        self._timer.stop()
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes.\n\nSave before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply == QMessageBox.Save:
            return self.commit()                    # only close if the commit actually succeeds
        if reply == QMessageBox.Discard:
            try:
                nd.discard(self.note.path)
            except OSError as e:
                self._set_error(f"Couldn't discard the draft: {e}")  # keep open (P2-4)
                return False
            self._clear_dirty()
            return True
        return False                                # Cancel

    # ------------------------------------------------------------------ #
    # focus-in external-change guard (P2-9/14, P1-9)
    # ------------------------------------------------------------------ #
    def on_panel_activated(self) -> None:
        """The host ExpandedPanel calls this when its window becomes active - the REAL focus route
        (the container's focusInEvent never fires because focus lands on the child editors)."""
        self._resolve_external_change()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._resolve_external_change()             # belt: rarely fires (container is NoFocus)

    def _resolve_external_change(self) -> None:
        """Activation/focus route: detect + resolve an outside-Serenity edit. Content-keyed, never
        mtime; a both-diverged conflict shows a bounded 3-way CHOICE, never a merge (P1-4/9, P2-9/14)."""
        self._timer.stop()
        state = nd.detect_external_change(self.note.path, self._baseline)
        if state == "source_missing":
            self._set_error("This note's file was moved or deleted outside Serenity - "
                            "use Save to re-create it.")
        elif state == "changed":
            if self._dirty:
                self._handle_changed_conflict()
            else:
                self._reload_from_disk()            # no local edits -> adopt the newer file

    def _external_ok_to_commit(self) -> bool:
        """commit() guard (P2-8): True if it's safe to write our buffer. A content conflict with
        unsaved edits routes through the 3-way; a missing .md falls through to promote (which
        re-creates it, or raises NoteSourceMissing when the note was purged)."""
        state = nd.detect_external_change(self.note.path, self._baseline)
        if state in ("unchanged", "source_missing"):
            return True
        # state == "changed"
        if not self._dirty:
            self._reload_from_disk()
            return False
        return self._handle_changed_conflict()

    def _handle_changed_conflict(self) -> bool:
        """The both-diverged 3-way. Returns True only on 'keep mine' (caller may overwrite disk)."""
        choice = self._ask_conflict()
        if choice == "keep_mine":
            # acknowledge this disk version so activation doesn't re-prompt; commit overwrites it.
            self._baseline = nd.content_hash(self._read_md_or_serialize())
            return True
        if choice == "keep_both":
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            sidecar = f"{self.note.path}.conflict-{ts}.md"
            try:
                atomic_write_text(
                    Path(sidecar),
                    nd.build_draft_text(self.fm_edit.toPlainText(), self.body.toPlainText()),
                )
            except OSError as e:
                self._set_error(f"Couldn't keep both copies: {e}")   # never throw into the loop
                return False
            self._reload_from_disk()
            return False
        if choice == "load_disk":
            self._reload_from_disk()
        return False                                # load_disk / cancel

    def _ask_conflict(self) -> str:
        """The bounded 3-way conflict prompt. Returns 'keep_mine'|'load_disk'|'keep_both'|'cancel'."""
        box = QMessageBox(self)
        box.setWindowTitle("This note changed on disk")
        box.setText("This note was edited outside Serenity while you had unsaved changes.")
        keep_mine = box.addButton("Keep mine", QMessageBox.AcceptRole)
        load_disk = box.addButton("Load from disk", QMessageBox.DestructiveRole)
        keep_both = box.addButton("Keep both", QMessageBox.ActionRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is keep_mine:
            return "keep_mine"
        if clicked is keep_both:
            return "keep_both"
        if clicked is load_disk:
            return "load_disk"
        return "cancel"

    def _reload_from_disk(self) -> None:
        """Adopt the on-disk .md into both editors and refresh the baseline (P2-14)."""
        self.store.reload_note(self.note_id)
        fresh = self.store.get(self.note_id)
        if fresh is None:
            self._set_error("This note's file was moved or deleted outside Serenity.")
            return
        # the superseded draft must not re-trigger recovery on the next open (P1-4); drop it.
        # (keep-both has already preserved our edits in a .conflict-<ts>.md sidecar.)
        try:
            nd.discard(self.note.path)
        except OSError:
            pass
        self.note = fresh
        self.body.setPlainText(fresh.body or "")
        self.fm_edit.setPlainText(_frontmatter_text(fresh))
        self._fm_edited = False
        self._baseline = nd.content_hash(self._read_md_or_serialize())
        self._clear_dirty()
        self._clear_error()

    # ------------------------------------------------------------------ #
    # open in the OS editor (hand-off) - P1-8, P3-3
    # ------------------------------------------------------------------ #
    def _ask_os_action(self) -> str:
        """The dirty-panel Open-in-OS prompt. Returns 'save'|'open'|'cancel'."""
        box = QMessageBox(self)
        box.setWindowTitle("Open in OS editor")
        box.setText("You have unsaved changes.")
        save_open = box.addButton("Save && open", QMessageBox.AcceptRole)
        open_only = box.addButton("Open without saving", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_open:
            return "save"
        if clicked is open_only:
            return "open"
        return "cancel"

    def open_in_os(self) -> None:
        self._timer.stop()
        if self._dirty:
            action = self._ask_os_action()
            if action == "save":
                if not self.commit():               # a failed validation aborts the hand-off (P1-8)
                    return
            elif action == "open":
                # keep the draft for recovery, but clear the dirty state so the close that follows
                # does NOT re-prompt / let a later Save clobber the handed-off file (P1-8).
                self._clear_dirty()
            else:
                return                              # Cancel - keep the draft + panel
        # capture the openUrl bool BEFORE closing; only close on True (P3-3).
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(self.note.path))
        if not opened:
            note = "" if platform_win.is_windows() else " (no OS editor is wired in this environment)"
            self._set_error(f"Couldn't open the file in an OS editor{note}.")
            return
        # the OS editor now owns the file; re-sync the store from disk so a later in-app write
        # can't serialize a stale note over the newer file (P1-11), then ask the host to close.
        self.store.reload_note(self.note_id)
        self.closeRequested.emit()

    # ------------------------------------------------------------------ #
    # keyboard: Ctrl+S commits
    # ------------------------------------------------------------------ #
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_S and (e.modifiers() & Qt.ControlModifier):
            self.commit()
            return
        super().keyPressEvent(e)
