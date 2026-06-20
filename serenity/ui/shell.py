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

from ..core import paths
from ..core.activity_store import ActivityStore
from ..core.llm import MODELS_SUBDIR, LlamaCppLLM
from ..core.note_store import NoteStore
from ..core.parser import parse_capture
from ..core.phase2_stubs import SemanticIndex
from ..core.semantic import SEMANTIC_DB_FILE, FastEmbedBackend
from ..core.settings import Settings
from ..core.todo_store import TodoStore
from ..core.voice_lines import VoiceLines
from . import icons, platform_win
from .activity_chip import ActivityChip
from .capture_bar import CaptureBar
from .focus_widget import FocusWidget
from .graph_view import GraphView
from .mascot_stage import MascotStage
from .mini_window import MiniWindow
from .modals import CheatsheetDialog, QuickNoteDialog, QuickTodoDialog
from .notes_view import NotesView
from .settings_window import SettingsWindow
from .theme import COLORS, stylesheet
from .todos_view import TodosView
from .trash_view import TrashView
from .weekly_board_view import WeeklyBoardView

DOCK_WIDTH = 348

# Window modes (tray + title-bar control, persisted in settings).
MODE_FULL = "full"
MODE_MINI = "mini"
MODE_HIDDEN = "hidden"


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

        # voice mute/unmute: checked = muted. Reflects settings.tts_enabled, flips + persists
        # it (see Shell.toggle_mute). Voice is ON by default, so it starts un-muted.
        self.mute_btn = QPushButton()
        self.mute_btn.setObjectName("iconbtn")
        self.mute_btn.setCheckable(True)
        self.mute_btn.clicked.connect(shell.toggle_mute)
        self._sync_mute_icon()

        # window-mode control: cycles Full <-> Mini (compact always-on-top)
        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("iconbtn")
        self.mode_btn.setIcon(icons.icon("grip", COLORS["ink2"], 15))
        self.mode_btn.setToolTip("Window mode")
        self.mode_btn.clicked.connect(shell.cycle_window_mode)

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

        for b in (self.pin_btn, self.mute_btn, self.mode_btn, hide_btn, set_btn, min_btn):
            b.setFixedSize(26, 26)
            lay.addWidget(b)

    def _sync_mute_icon(self):
        """Match the mute button to settings.tts_enabled (checked + muted icon when off)."""
        muted = not self.shell.settings.tts_enabled
        self.mute_btn.setChecked(muted)
        self.mute_btn.setIcon(icons.icon("mute" if muted else "volume",
                                         COLORS["ink2"], 15))
        self.mute_btn.setToolTip("Voice muted - click to unmute" if muted
                                 else "Voice on - click to mute")

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
    def __init__(self, boot: bool = False):
        super().__init__()
        # boot=True when launched on login via the autostart Run key (see __main__): it
        # selects the boot greeting over the normal open greeting.
        self._booted = boot
        self.settings = Settings.load()
        vault = Path(self.settings.vault_path)
        self.todo_store = TodoStore(vault)
        self.note_store = NoteStore(vault)
        # 'Meaning' search index (fastembed + sqlite-vec), kept out of the synced vault.
        # Cheap to build - the model only loads on first Meaning search, and it degrades to
        # keyword search when the optional [semantic] deps are absent. The model is
        # configurable via Settings (default mpnet); a model change rebuilds the store.
        self.semantic = SemanticIndex(
            embedder=FastEmbedBackend(model=self.settings.embedding_model),
            db_path=paths.config_dir() / SEMANTIC_DB_FILE,
        )
        # One local text-generation seam shared by BOTH the Notes "Ask" RAG (Job 13) and the
        # AI weekly digest (Job 6). Lazy + degrades: it imports nothing heavy and loads no
        # model until the first generate(), and advertises available=False when llama-cpp / the
        # GGUF is absent - so it costs nothing at idle, Ask falls back to showing the retrieved
        # notes, and the digest falls back to the deterministic board hint. Drop a GGUF named
        # per core.llm.DEFAULT_MODEL_FILE into <config>/models/ to turn the AI features on.
        self.llm = LlamaCppLLM(models_dir=paths.config_dir() / MODELS_SUBDIR)
        self.activity_store = ActivityStore(vault)
        self.voice = VoiceLines()
        self._lang = self.settings.language
        self._mini = None        # the compact always-on-top mini-dock (lazy)
        self._mode = MODE_FULL   # current window mode (set in set_window_mode)
        # Wall-clock of the last user-driven interaction - the real idle clock the break-time
        # proxy reads (the app has no OS input-idle probe). Reset by _touch() on every user
        # slot; _derive_break_state turns "now - this" into idle_seconds so HEAVY maintenance
        # only fires after the user has genuinely been away, never while they are working.
        from datetime import datetime as _dt
        self._last_interaction = _dt.now()

        # Seed the meeting-protocol starter tags into the arsenal (Quick Note protocol
        # template). "Meeting" is already a basic; "Protokoll" is added here.
        if self.settings.add_tags(["Protokoll", "meeting"]):
            self.settings.save()

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

        # Keep the autostart Run key in step with the setting (default ON). No-op off Windows
        # and fully guarded - registry hiccups must never block the app from opening.
        try:
            platform_win.set_autostart(self.settings.autostart)
        except Exception:
            pass

        # apply the persisted window mode (full / mini / hidden)
        self.set_window_mode(getattr(self.settings, "window_mode", MODE_FULL), persist=False)

        # greeting - the boot line on a login launch, the normal open line otherwise
        self.greet("boot" if self._booted else "open")

        # QTimer drives both the board auto-open poll and the break-time maintenance tick.
        from PySide6.QtCore import QTimer

        # Friday 17-18h once-a-day Weekly-Board auto-open (core.activity rule). A 1-minute
        # poll is cheap and lets the board pop the moment the window opens.
        self._board_timer = QTimer(self)
        self._board_timer.setInterval(60_000)
        self._board_timer.timeout.connect(self._maybe_auto_open_board)
        self._board_timer.start()
        self._maybe_auto_open_board()

        # Break-time background maintenance: re-embed changed notes while the user is on a
        # break (HEAVY -> only on AC + a long idle; see core.breaktime). No-ops on a base
        # install (no embedder -> the job skips; detect_on_ac() -> None -> HEAVY gated off),
        # so this costs nothing and changes nothing until the [semantic]+[power] extras land.
        from ..core.breaktime import BreakScheduler, BreakState, detect_on_ac
        from ..core.maintenance import build_maintenance_jobs
        from ..core.perf import PerfSampler
        # Last-minute performance history for the Settings 'AI and voice' panel. Sampled each
        # break tick (a timestamp-only sample without the optional psutil probe) and fed the
        # JobResults the scheduler returns, so the panel can show "is anything running".
        self.perf = PerfSampler()
        self._break_scheduler = BreakScheduler()
        for job in build_maintenance_jobs(semantic=self.semantic,
                                          note_store=self.note_store, llm=self.llm):
            self._break_scheduler.register(job)
        # Stash so _break_tick has them without re-importing each tick.
        self._break_state_cls = BreakState
        self._detect_on_ac = detect_on_ac
        self._break_timer = QTimer(self)
        self._break_timer.setInterval(180_000)   # 3 min - a few minutes, mirrors _board_timer
        self._break_timer.timeout.connect(self._break_tick)
        self._break_timer.start()

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
        for key, label in [("todos", "Todos"), ("notes", "Notes"),
                           ("graph", "Graph"), ("board", "Board")]:
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
        self.notes_view = NotesView(self.note_store, self.semantic,
                                    settings=self.settings, llm=self.llm)
        self.graph_view = GraphView(self.todo_store)
        self.board_view = WeeklyBoardView(self.activity_store, self.todo_store, llm=self.llm)
        self.trash_view = TrashView(self.todo_store, self.note_store)
        self._view_index = {}
        for key, view in [("todos", self.todos_view), ("notes", self.notes_view),
                          ("graph", self.graph_view), ("board", self.board_view),
                          ("trash", self.trash_view)]:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(12, 6, 12, 8)
            wl.addWidget(view)
            self._view_index[key] = self.stack.addWidget(wrap)
        root.addWidget(self.stack, 1)

        # capture bar
        self.capture = CaptureBar()
        root.addWidget(self.capture)

        # running-activity chip + focus (Pomodoro) timer, just above the mascot
        self.activity_chip = ActivityChip()
        root.addWidget(self.activity_chip)
        self.focus_widget = FocusWidget(self.voice, self.settings)
        root.addWidget(self.focus_widget)

        # mascot stage
        self.mascot = MascotStage(self.settings)
        root.addWidget(self.mascot)

        self.setCentralWidget(central)
        self.setFixedWidth(DOCK_WIDTH)
        self.switch_tab("todos")
        # Restore a span that was still running at last quit.
        self.activity_chip.show_running(self.activity_store.running())

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

        # focus (Pomodoro) phase changes -> Serenity comments
        self.focus_widget.phase_changed.connect(self._on_focus_phase)

    def _build_tray(self):
        icon = QIcon(icons.pixmap("pin", COLORS["accent"], 32))
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Serenity")
        menu = QMenu()
        # window-mode radio group (Full / Mini / Hidden)
        from PySide6.QtGui import QActionGroup
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        self._mode_actions = {}
        for mode, label in [(MODE_FULL, "Full window"), (MODE_MINI, "Mini (compact)"),
                            (MODE_HIDDEN, "Hidden (tray only)")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(mode == self._mode)
            act.triggered.connect(lambda _=False, m=mode: self.set_window_mode(m))
            mode_group.addAction(act)
            menu.addAction(act)
            self._mode_actions[mode] = act
        menu.addSeparator()
        set_act = QAction("Settings", self)
        set_act.triggered.connect(self.open_settings)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit)
        menu.addAction(set_act)
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
        self._touch()
        for k, b in self.tab_buttons.items():
            b.setChecked(k == key)
        self.stack.setCurrentIndex(self._view_index[key])
        if key == "trash":
            self.trash_view.refresh()
        elif key == "graph":
            self.graph_view.refresh()
        elif key == "board":
            self.board_view.refresh()

    # ---------------- mascot reactions ----------------
    def _on_todo_completed(self, todo):
        self.mascot.set_state("success")
        self.mascot.says(self.voice.say("todo_completed", self._lang, title=todo.title), "#86efac")
        self._refresh_trash()

    def _on_todo_started(self, todo):
        self.mascot.set_state("working")
        self.mascot.says(self.voice.say("todo_started_inprogress", self._lang, title=todo.title))

    def _on_activity(self, label: str):
        self._touch()
        # Selecting an activity starts a tracked span (closing any prior one); "Idle"
        # just stops tracking. The chip shows the running span + live elapsed.
        if label == "Idle":
            self.activity_store.stop()
            self.activity_chip.clear()
        else:
            entry = self.activity_store.start(label)
            self.activity_chip.show_running(entry)
        # "Focus" reveals the Pomodoro timer; any other activity hides + stops it.
        if label == "Focus":
            self.focus_widget.start()
        else:
            self.focus_widget.set_active(False)
        self.mascot.says(self.voice.say("activity_changed", self._lang, category=label))

    def _on_focus_phase(self, phase: str, text: str):
        """Serenity comments on a Pomodoro phase change (focus done / break over)."""
        color = "#86efac" if phase == "break" or phase == "long_break" else "#19e3ff"
        self.mascot.set_state("success" if phase != "focus" else "coding")
        if text:
            self.mascot.says(text, color)

    def _refresh_trash(self, *_):
        self.trash_view.refresh()

    # ---------------- weekly board auto-open (Fri 17-18h, once a day) ----------------
    def _maybe_auto_open_board(self):
        from datetime import datetime

        from ..core.activity import should_auto_open_board
        now = datetime.now()
        if not should_auto_open_board(now, self.activity_store.last_board_open()):
            return
        self.activity_store.set_last_board_open(now)
        # Make sure the window is visible (a mini/hidden dock comes forward for the review).
        if self._mode != MODE_FULL:
            self.set_window_mode(MODE_FULL)
        self.show_dock()
        self.switch_tab("board")
        # Serenity introduces the review and reads the weekly digest as a comment. switch_tab
        # already refreshed the board view, so digest_text() is the freshly-built digest -
        # the AI comment when an LLM is wired, the deterministic board hint otherwise.
        intro = self.voice.say("weekly_review_intro", self._lang)
        comment = self.board_view.digest_text()
        text = f"{intro} {comment}".strip() if comment else intro
        self.mascot.set_state("thinking")
        self.mascot.says(text, COLORS["accent"])

    # ---------------- break-time maintenance ----------------
    def _touch(self):
        """Record 'the user just did something' - resets the last-interaction idle clock.

        Called from every user-driven slot (activity / tab / capture / mic / quick-add / slot
        answer). _derive_break_state reads `now - self._last_interaction` as the real idle
        time, so any interaction immediately makes the app look 'busy' and re-gates the HEAVY
        maintenance off until the user has genuinely been away again."""
        from datetime import datetime
        self._last_interaction = datetime.now()

    def _break_tick(self):
        """Run any eligible break-time maintenance job once.

        The BreakState is built each tick from a real idle clock (now - last interaction; see
        _derive_break_state) plus the AC probe; HEAVY jobs only fire on AC after a long
        genuine idle, so on a base install nothing runs. Jobs run SYNCHRONOUSLY here on the Qt
        main thread - acceptable for now (the only job is the incremental e5 re-embed, which
        no-ops when nothing changed); a slow re-embed of many changed notes would briefly
        block the UI, so a future hardening step is to move tick() onto a QThread (needs
        SemanticIndex/sqlite-vec thread-safety vetting first). The JobResults are captured into
        the PerfSampler so the Settings 'AI and voice' panel can show recent maintenance, and a
        resource sample is taken each tick to feed its last-minute window."""
        from datetime import datetime
        state = self._derive_break_state()
        try:
            self.perf.sample()
            results = self._break_scheduler.tick(datetime.now(), state)
            self.perf.record_job_results(results)
        except Exception:
            pass  # defensive - tick() already isolates per-job; never break the UI loop

    def _derive_break_state(self):
        """Build the break/idle/AC snapshot for the scheduler from a REAL idle clock + AC probe.

        The app has no OS input-idle clock, so idle is measured from `self._last_interaction`,
        a wall-clock reset by _touch() on every user-driven slot: idle_seconds = now - that.
        on_break is True only once that idle passes the LIGHT threshold (genuine inactivity) -
        so the app's default 'nothing tracked but just launched / actively used' state reports
        a SMALL idle and keeps every job gated off; HEAVY also needs ac_ok + the longer
        heavy-idle, so on a base install (detect_on_ac() -> None) it never fires regardless.
        A running real WORK span (any activity, including a 'Focus' Pomodoro - focus IS work)
        is a hard override: on_break=False, idle_seconds=0.0, so maintenance can never run
        mid-work even if interaction tracking missed a beat. ('Idle' is not a tracked span -
        selecting it stops tracking - so running() here is only ever None or a work span.)"""
        from datetime import datetime
        running = self.activity_store.running()
        if running is not None:
            # A tracked work span is active - the user is working, never on a break.
            return self._break_state_cls(on_break=False, idle_seconds=0.0,
                                         on_ac=self._detect_on_ac())
        idle_seconds = max(0.0, (datetime.now() - self._last_interaction).total_seconds())
        on_break = idle_seconds >= self._break_scheduler.light_idle_seconds
        return self._break_state_cls(on_break=on_break, idle_seconds=idle_seconds,
                                     on_ac=self._detect_on_ac())

    # ---------------- capture ----------------
    def _on_mic(self, recording: bool):
        self._touch()
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
        self._touch()
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
        self._touch()
        dlg = QuickNoteDialog(self.note_store, self.settings, self)
        dlg.saved.connect(self._on_note_saved)
        dlg.exec()

    def _on_note_saved(self, note):
        self.notes_view.refresh()
        self.mascot.says(self.voice.say("quick_note_saved", self._lang, title=note.title), "#86efac")

    def _open_quick_todo(self):
        self._touch()
        dlg = QuickTodoDialog(self.todo_store, self.settings, self)
        dlg.added.connect(self._on_quick_todo)
        dlg.exec()

    def _on_quick_todo(self, todo):
        self.switch_tab("todos")
        self.todos_view.refresh()
        self.mascot.says(self.voice.say("confirm_accepted", self._lang, title=todo.title))

    # ---------------- settings ----------------
    def open_settings(self):
        dlg = SettingsWindow(self.settings, self, perf=self.perf)
        dlg.applied.connect(self._apply_settings)
        dlg.exec()

    def _apply_settings(self):
        self.setStyleSheet(stylesheet(self.settings.accent))
        self._lang = self.settings.language
        self.mascot.refresh_selector()
        self.mascot.refresh_tts()
        self.mascot._relayout()
        # the Settings "Speak Serenity's lines" checkbox may have flipped tts_enabled
        self.title_bar._sync_mute_icon()

    def toggle_mute(self):
        """Title-bar voice toggle: flip + persist tts_enabled, rebuild the speech engine.

        Checked = muted (tts_enabled False). Mirrors the Settings 'Speak Serenity's lines'
        toggle so the two controls always agree."""
        self.settings.tts_enabled = not self.title_bar.mute_btn.isChecked()
        self.settings.save()
        self.title_bar._sync_mute_icon()
        self.mascot.refresh_tts()

    # ---------------- greetings (open / boot / resume) ----------------
    def greet(self, kind: str = "open"):
        """Have Serenity greet, picking the line for how the app came to the foreground.

        kind: "boot" (started on login via autostart), "resume" (woke from standby), or
        "open" (a normal launch). Falls back to the open greeting for an unknown kind so a
        greeting always happens. Routed through the mascot's speech bubble + the speak()
        path, so the title-bar mute toggle (tts_enabled) governs whether it is spoken."""
        event = {
            "boot": "app_boot_greeting",
            "resume": "app_resumed_greeting",
        }.get(kind, "app_opened_greeting")
        self.mascot.says(self.voice.say(event, self._lang))

    def nativeEvent(self, event_type, message):
        """Windows: re-greet when the machine wakes from standby/hibernate.

        WM_POWERBROADCAST carries a resume sub-event in wParam; platform_win.is_resume_message
        makes the decision (pure + unit-tested). Everything here is guarded and lazy: off
        Windows the message is not a WM_POWERBROADCAST so nothing fires, and any ctypes hiccup
        is swallowed so the event loop is never disturbed. Always defers to the base handler."""
        try:
            if platform_win.is_windows():
                import ctypes
                from ctypes import wintypes

                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if platform_win.is_resume_message(int(msg.message), int(msg.wParam)):
                    self._on_resume()
        except Exception:
            pass
        return super().nativeEvent(event_type, message)

    def _on_resume(self):
        """Wake-from-standby handler: bring Serenity back and greet with the resume line."""
        self.greet("resume")

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
        self.set_window_mode(MODE_HIDDEN)
        if self.tray.isVisible():
            self.tray.showMessage("Serenity", "Still here in the tray.",
                                  QSystemTrayIcon.Information, 1500)

    def show_dock(self):
        platform_win.dock_right(self, DOCK_WIDTH)
        self.show()
        self.raise_()

    # ---------------- window modes (Full / Mini / Hidden) ----------------
    def set_window_mode(self, mode: str, persist: bool = True):
        """Switch between Full (the dock), Mini (compact always-on-top), Hidden (tray).

        Persisted in settings so the app reopens in the last mode."""
        if mode not in (MODE_FULL, MODE_MINI, MODE_HIDDEN):
            mode = MODE_FULL
        self._mode = mode
        if persist and getattr(self.settings, "window_mode", None) != mode:
            self.settings.window_mode = mode
            self.settings.save()
        # keep the tray menu radio + title-bar control in step
        self._sync_mode_controls()

        if mode == MODE_HIDDEN:
            if self._mini is not None:
                self._mini.hide()
            self.hide()
            return
        if mode == MODE_MINI:
            self.hide()
            self._ensure_mini().show()
            self._mini.raise_()
            return
        # MODE_FULL
        if self._mini is not None:
            self._mini.hide()
        self.show_dock()

    def _ensure_mini(self) -> "MiniWindow":
        if self._mini is None:
            self._mini = MiniWindow(self.todo_store, self.settings)
            self._mini.activity_changed.connect(self._on_activity)
            self._mini.restore_requested.connect(lambda: self.set_window_mode(MODE_FULL))
            # place it where the dock sits (right edge, top)
            platform_win.dock_right(self._mini, self._mini.width())
        return self._mini

    def _sync_mode_controls(self):
        if hasattr(self, "_mode_actions"):
            for m, act in self._mode_actions.items():
                act.setChecked(m == self._mode)
        if hasattr(self, "title_bar"):
            self.title_bar.mode_btn.setToolTip(f"Window mode: {self._mode} (click to cycle)")

    def cycle_window_mode(self):
        """Title-bar control: Full -> Mini -> Full (Hidden is via tray, not the cycle)."""
        self.set_window_mode(MODE_MINI if self._mode == MODE_FULL else MODE_FULL)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            # toggle the tray: hide when shown, restore to full when hidden
            if self._mode == MODE_HIDDEN:
                self.set_window_mode(MODE_FULL)
            else:
                self.set_window_mode(MODE_HIDDEN)

    def closeEvent(self, e):
        # close to tray instead of quitting (always-on-top secretary stays resident)
        if self.tray.isVisible():
            e.ignore()
            self.hide_to_tray()
        else:
            e.accept()

    def _quit(self):
        self.todo_store.save()
        self.activity_store.save()
        self.note_store.close()
        # Stop the break-time tick so no maintenance job fires during teardown.
        if getattr(self, "_break_timer", None) is not None:
            self._break_timer.stop()
        if self._mini is not None:
            self._mini.close()
        QApplication.instance().quit()
