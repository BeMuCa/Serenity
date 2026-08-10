"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The Trash/Archive tab - done + deleted todos and deleted notes.
Role:    One place for everything finished or removed (decisions doc 4d). Each row
         has restore + delete-forever. Reads TodoStore.trash() + NoteStore.trash().

Classes:
- TrashRow - one archived item with restore / purge actions
- TrashView - the combined archive list
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import COLORS


class TrashRow(QFrame):
    restore = Signal()
    purge = Signal()

    def __init__(self, title: str, meta: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 8, 11, 8)
        info = QVBoxLayout()
        info.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"color:{COLORS['ink2']}; font-size:13px;")
        m = QLabel(meta)
        m.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        info.addWidget(t)
        info.addWidget(m)
        lay.addLayout(info, 1)

        rb = QPushButton("Restore")
        rb.setObjectName("ghost")
        rb.setIcon(icons.icon("restore", COLORS["ink2"], 12))
        rb.clicked.connect(self.restore.emit)
        lay.addWidget(rb)

        pb = QPushButton()
        pb.setObjectName("danger")
        pb.setIcon(icons.icon("trash", "#fca5a5", 12))
        pb.setToolTip("Delete forever")
        pb.clicked.connect(self.purge.emit)
        lay.addWidget(pb)


class TrashView(QWidget):
    def __init__(self, todo_store, note_store, parent=None):
        super().__init__(parent)
        self.todo_store = todo_store
        self.note_store = note_store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QLabel("Archive - done and deleted items. Restore or delete forever.")
        head.setObjectName("sectLabel")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        c = QWidget()
        c.setLayout(self.list_box)
        lay.addWidget(c)
        self.empty = QLabel("Trash is empty.")
        self.empty.setStyleSheet(f"color:{COLORS['ink3']}; font-size:12px;")
        lay.addWidget(self.empty)
        lay.addStretch(1)
        self.refresh()

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        count = 0
        for todo in self.todo_store.trash():
            tag = "done" if todo.done else "deleted"
            row = TrashRow(todo.title, f"todo - {tag}")
            row.restore.connect(lambda _id=todo.id: self._restore_todo(_id))
            row.purge.connect(lambda _id=todo.id: self._purge_todo(_id))
            self.list_box.addWidget(row)
            count += 1
        for note in self.note_store.trash():
            row = TrashRow(note.title, "note - deleted")
            row.restore.connect(lambda _id=note.id: self._restore_note(_id))
            row.purge.connect(lambda _id=note.id: self._purge_note(_id))
            self.list_box.addWidget(row)
            count += 1
        self.empty.setVisible(count == 0)

    def _restore_todo(self, _id):
        self.todo_store.restore(_id)
        self.refresh()

    def _purge_todo(self, _id):
        if not self._confirm_purge():
            return
        self.todo_store.purge(_id)
        self.refresh()

    def _restore_note(self, _id):
        self.note_store.restore(_id)
        self.refresh()

    def _purge_note(self, _id):
        if not self._confirm_purge():
            return
        self.note_store.purge(_id)
        self.refresh()

    def _confirm_purge(self) -> bool:
        """Ask before an irreversible 'Delete forever'. True only on an explicit Yes.

        Guards both purge handlers (P1 - notes flow 11): a single misclick on the red
        delete button no longer destroys the item. Default button is Cancel."""
        reply = QMessageBox.question(
            self,
            "Delete forever?",
            "Delete forever? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return reply == QMessageBox.Yes
