"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The app shell - frameless docked always-on-top window, title bar, tabs, tray.
Role:    Hosts every view and the mascot stage; owns the stores, settings and voice
         lines; routes events between the Todos/Notes/Trash views and Serenity's bubble.
         Windows-only behaviors (dock, tray-only-quit) are guarded so it runs on Linux.

Classes:
- TitleBar - draggable custom title bar (brand + pin/hide/settings/min)
- Shell - the QMainWindow: builds the dock, wires events, manages the tray + capture
============================================================
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..core.note_store import NoteStore
from ..core.parser import parse_capture
from ..core.settings import Settings
from ..core.todo_store import TodoStore
from ..core.voice_lines import VoiceLines
from . import icons, platform_win
from .capture_bar import CaptureBar
from .graph_view import GraphView
from .mascot_stage import MascotStage
from .modals import CheatsheetDialog, QuickNoteDialog, QuickTodoDialog
from .notes_view import NotesView
from .settings_window import SettingsWindow
from .theme import COLORS, stylesheet
from .todos_view import TodosView
from .trash_view import TrashView

DOCK_WIDTH = 348


class TitleBar(QWidget):
    def __init__(self, shell: "Shell"):
        super().__init__()
        self.shell = shell
        self.setObjectName("titleBar")
        self.setFixedHeight(42)
        self._drag = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{COLORS['accent']}; border-radius:4px;")
        brand = QLabel("Serenity")
        brand.setObjectName("brand")
        sub = QLabel("SECRETARY")
        sub.setObjectName("brandSub")
        lay.addWidget(dot)
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addStretch(1)

        self.pin_btn = QPushButton()
        self.pin_btn.setObjectName("iconbtn")
        self.pin_btn.setIcon(icons.icon("pin", COLORS["accent"], 15))
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(True)
        self.pin_btn.setToolTip("Always on top")
        self.pin_btn.clicked.connect(shell.toggle_on_top)

        hide_btn = QPushButton()
        hide_btn.setObjectName("iconbtn")
        hide_btn.setIcon(icons.icon("eye-off", COLORS["ink2"], 15))
        hide_btn.setToolTip("Hide to tray")
        hide_btn.clicked.connect(shell.hide_to_tray)

        set_btn = QPushButton()
        set_btn.setObjectName("iconbtn")
        set_btn.setIcon(icons.icon("settings", COLORS["ink2"], 15))
        set_btn.setToolTip("Settings")
        set_btn.clicked.connect(shell.open_settings)

        min_btn = QPushButton()
        min_btn.setObjectName("iconbtn")
        min_btn.setIcon(icons.icon("minimize", COLORS["ink2"], 15))
        min_btn.setToolTip("Minimize")
        min_btn.clicked.connect(shell.showMinimized)

        for b in (self.pin_btn, hide_btn, set_btn, min_btn):
            b.setFixedSize(26, 26)
            lay.addWidget(b)

    # drag the frameless window by the title bar
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.shell.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.shell.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


class Shell(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        vault = Path(self.settings.vault_path)
        self.todo_store = TodoStore(vault)
        self.note_store = NoteStore(vault)
        self.voice = VoiceLines()
        self._lang = self.settings.language

        # frameless, tool window, always-on-top
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowTitle("Serenity")

        self._build_ui()
        self._wire()
        self._build_tray()

        # dock to the right edge (guarded; Qt geometry works cross-platform)
        platform_win.dock_right(self, DOCK_WIDTH)

        # greeting
        self.mascot.says(self.voice.say("app_opened_greeting", self._lang))

    # ---------------- UI ----------------
    def _build_ui(self):
        self.setStyleSheet(stylesheet(self.settings.accent))
        central = QWidget()
        central.setObjectName("dock")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self)
        root.addWidget(self.title_bar)

        # tabs
        tabrow = QWidget()
        tl = QHBoxLayout(tabrow)
        tl.setContentsMargins(10, 8, 10, 0)
        tl.setSpacing(2)
        self.tab_buttons = {}
        for key, label in [("todos", "Todos"), ("notes", "Notes"), ("graph", "Graph")]:
            b = QPushButton(label)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.switch_tab(k))
            self.tab_buttons[key] = b
            tl.addWidget(b)
        # trash icon tab
        tb = QPushButton()
        tb.setObjectName("tab")
        tb.setCheckable(True)
        tb.setIcon(icons.icon("trash", COLORS["ink3"], 15))
        tb.setToolTip("Trash / Archive")
        tb.clicked.connect(lambda: self.switch_tab("trash"))
        self.tab_buttons["trash"] = tb
        tl.addWidget(tb)
        tl.addStretch(1)
        root.addWidget(tabrow)

        # stacked views
        self.stack = QStackedWidget()
        self.todos_view = TodosView(self.todo_store, self.settings)
        self.notes_view = NotesView(self.note_store)
        self.graph_view = GraphView()
        self.trash_view = TrashView(self.todo_store, self.note_store)
        self._view_index = {}
        for key, view in [("todos", self.todos_view), ("notes", self.notes_view),
                          ("graph", self.graph_view), ("trash", self.trash_view)]:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(12, 6, 12, 8)
            wl.addWidget(view)
            self._view_index[key] = self.stack.addWidget(wrap)
        root.addWidget(self.stack, 1)

        # capture bar
        self.capture = CaptureBar()
        root.addWidget(self.capture)

        # mascot stage
        self.mascot = MascotStage(self.settings)
        root.addWidget(self.mascot)

        self.setCentralWidget(central)
        self.setFixedWidth(DOCK_WIDTH)
        self.switch_tab("todos")

    def _wire(self):
        # todos -> mascot reactions
        self.todos_view.todo_completed.connect(self._on_todo_completed)
        self.todos_view.todo_started.connect(self._on_todo_started)
        self.todos_view.todo_added.connect(self._refresh_trash)
        self.notes_view.note_deleted.connect(self._refresh_trash)

        # capture bar
        self.capture.mic_toggled.connect(self._on_mic)
        self.capture.quick_note.connect(self._open_quick_note)
        self.capture.quick_todo.connect(self._open_quick_todo)

        # mascot activity -> log + voice line
        self.mascot.activity_changed.connect(self._on_activity)
        self.mascot.bubble.answered.connect(self._on_slot_answer)

    def _build_tray(self):
        icon = QIcon(icons.pixmap("pin", COLORS["accent"], 32))
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Serenity")
        menu = QMenu()
        show_act = QAction("Show", self)
        show_act.triggered.connect(self.show_dock)
        hide_act = QAction("Hide", self)
        hide_act.triggered.connect(self.hide_to_tray)
        set_act = QAction("Settings", self)
        set_act.triggered.connect(self.open_settings)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit)
        for a in (show_act, hide_act, set_act):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        try:
            self.tray.show()
        except Exception:
            pass  # headless / no tray available

    # ---------------- tab switching ----------------
    def switch_tab(self, key: str):
        for k, b in self.tab_buttons.items():
            b.setChecked(k == key)
        self.stack.setCurrentIndex(self._view_index[key])
        if key == "trash":
            self.trash_view.refresh()

    # ---------------- mascot reactions ----------------
    def _on_todo_completed(self, todo):
        self.mascot.set_state("success")
        self.mascot.says(self.voice.say("todo_completed", self._lang, title=todo.title), "#86efac")
        self._refresh_trash()

    def _on_todo_started(self, todo):
        self.mascot.set_state("working")
        self.mascot.says(self.voice.say("todo_started_inprogress", self._lang, title=todo.title))

    def _on_activity(self, label: str):
        self.mascot.says(self.voice.say("activity_changed", self._lang, category=label))

    def _refresh_trash(self, *_):
        self.trash_view.refresh()

    # ---------------- capture ----------------
    def _on_mic(self, recording: bool):
        if recording:
            self.mascot.says(self.voice.say("listening_start", self._lang))
            dlg = CheatsheetDialog(self)
            dlg.show()
        else:
            # Phase-1 demo: parse a canned utterance to exercise the slot-filling UI.
            self._demo_capture("Erinnerung Zahnarzt anrufen")

    def _demo_capture(self, text: str):
        cap = parse_capture(text)
        self._pending = cap
        if cap.missing:
            slot = cap.missing[0]
            event = "missing_slot_ask_date" if slot == "date" else "missing_slot_ask_title"
            self._pending_slot = slot
            self.mascot.ask(self.voice.say(event, self._lang))
        else:
            self._commit_capture(cap)

    def _on_slot_answer(self, answer: str):
        cap = getattr(self, "_pending", None)
        slot = getattr(self, "_pending_slot", None)
        if not cap:
            return
        if slot == "date":
            from ..core.parser import parse_natural_date
            cap.date = parse_natural_date(answer)
            if cap.date:
                cap.missing = [m for m in cap.missing if m != "date"]
        elif slot == "title":
            cap.title = answer
            cap.missing = [m for m in cap.missing if m != "title"]
        if cap.missing:
            slot = cap.missing[0]
            event = "missing_slot_ask_date" if slot == "date" else "missing_slot_ask_title"
            self._pending_slot = slot
            self.mascot.ask(self.voice.say(event, self._lang))
        else:
            self._commit_capture(cap)

    def _commit_capture(self, cap):
        from ..core.models import Todo
        if cap.kind == "todo":
            self.todo_store.add(Todo(title=cap.title, due=cap.date, recurring=cap.recurring,
                                     category=cap.category, tags=cap.tags))
            self.todos_view.refresh()
            self.mascot.says(self.voice.say("voice_routed_todo", self._lang, title=cap.title,
                                            date=cap.date.strftime("%b %d") if cap.date else "-",
                                            time=cap.date.strftime("%H:%M") if cap.has_time else "-"))
        else:
            self.note_store.create(cap.title, body=cap.raw)
            self.notes_view.refresh()
            self.mascot.says(self.voice.say("voice_routed_note", self._lang, title=cap.title), "#86efac")
        if cap.tags and self.settings.add_tags(cap.tags):
            self.settings.save()

    def _open_quick_note(self):
        dlg = QuickNoteDialog(self.note_store, self.settings, self)
        dlg.saved.connect(self._on_note_saved)
        dlg.exec()

    def _on_note_saved(self, note):
        self.notes_view.refresh()
        self.mascot.says(self.voice.say("quick_note_saved", self._lang, title=note.title), "#86efac")

    def _open_quick_todo(self):
        dlg = QuickTodoDialog(self.todo_store, self.settings, self)
        dlg.added.connect(self._on_quick_todo)
        dlg.exec()

    def _on_quick_todo(self, todo):
        self.switch_tab("todos")
        self.todos_view.refresh()
        self.mascot.says(self.voice.say("confirm_accepted", self._lang, title=todo.title))

    # ---------------- settings ----------------
    def open_settings(self):
        dlg = SettingsWindow(self.settings, self)
        dlg.applied.connect(self._apply_settings)
        dlg.exec()

    def _apply_settings(self):
        self.setStyleSheet(stylesheet(self.settings.accent))
        self._lang = self.settings.language
        self.mascot.refresh_selector()
        self.mascot._relayout()

    # ---------------- window / tray behaviors ----------------
    def toggle_on_top(self):
        on = self.title_bar.pin_btn.isChecked()
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def hide_to_tray(self):
        self.hide()
        if self.tray.isVisible():
            self.tray.showMessage("Serenity", "Still here in the tray.",
                                  QSystemTrayIcon.Information, 1500)

    def show_dock(self):
        platform_win.dock_right(self, DOCK_WIDTH)
        self.show()
        self.raise_()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide_to_tray()
            else:
                self.show_dock()

    def closeEvent(self, e):
        # close to tray instead of quitting (always-on-top secretary stays resident)
        if self.tray.isVisible():
            e.ignore()
            self.hide_to_tray()
        else:
            e.accept()

    def _quit(self):
        self.todo_store.save()
        self.note_store.close()
        QApplication.instance().quit()
