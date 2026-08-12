"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The Todos tab - add input, ranked todo cards, subtasks, timers, reorder.
Role:    Renders TodoStore.active() as cards (matching the mockup): checkbox,
         title, due/timer/recurring chips, expandable subtasks, a start/stop timer
         control, and drag-to-reorder via the grip. Completing a todo sends it to
         Trash and emits events for the mascot.

Classes:
- TodoCard - one todo (header row + chips + subtasks)
- TodosView - the add bar + scrollable ranked list
============================================================
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..core import meeting_prep, ranking, reminders, states
from ..core.models import SubTask, Todo
from ..core.parser import parse_capture
from . import icons
from .modals import protocol_template
from .peek_placeholder import PeekPlaceholder
from .reminder_picker import ReminderPicker
from .state_chip import StateFilterChip
from .theme import COLORS


def _chip(text: str, kind: str = "") -> QLabel:
    palette = {
        "timer": ("#fbbf24", "rgba(251,191,36,0.08)", "rgba(251,191,36,0.25)"),
        "due": ("#7dd3fc", "rgba(125,211,252,0.07)", "rgba(125,211,252,0.22)"),
        "warn": ("#fbbf24", "rgba(251,191,36,0.10)", "rgba(251,191,36,0.30)"),
        "soon": ("#fca5a5", "rgba(251,113,133,0.12)", "rgba(251,113,133,0.35)"),
        "rec": ("#86efac", "rgba(134,239,172,0.07)", "rgba(134,239,172,0.22)"),
    }
    fg, bg, br = palette.get(kind, (COLORS["ink2"], COLORS["panel3"], COLORS["line"]))
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{fg}; background:{bg}; border:1px solid {br}; border-radius:6px;"
        f"padding:1px 7px; font-size:10.5px;"
    )
    return lab


class TodoCard(QFrame):
    changed = Signal()
    started = Signal(object)
    reorder = Signal(str, str)            # (dragged_id, target_id)
    open_note = Signal(object)            # emits the linked Note to open in the Notes tab
    reminders_changed = Signal(object)    # emits the Todo when reminders are modified
    # Done-grace (FEATURE 5) is owned by TodosView so its timer survives a card rebuild; the card
    # only reports the user arming/cancelling it and shows the line-through.
    grace_armed = Signal(object)          # emits the Todo when ticked done (view starts the timer)
    grace_cancelled = Signal(object)      # emits the Todo when un-ticked within the window
    drag_active = Signal(bool)            # True while drag.exec's nested loop runs (view defers refresh)
    # Ring banner (Phase H): acknowledge buttons emit the todo when clicked
    ring_snooze = Signal(object)          # emits the Todo when Snooze button clicked
    ring_dismiss = Signal(object)         # emits the Todo when Dismiss button clicked
    prep_requested = Signal(object)       # emits the meeting Todo when Prep is pressed

    def __init__(self, todo: Todo, store, now: datetime, note_store=None, parent=None):
        super().__init__(parent)
        self.todo = todo
        self.store = store
        # The NoteStore (or None) for the prep/protocol link (FEATURE 4). Optional so existing
        # callers/tests that build a card without notes keep working - the button hides then.
        self.note_store = note_store
        self.setObjectName("card")
        self.setProperty("todoId", todo.id)
        self.setAcceptDrops(True)
        self._build(now)

    def _build(self, now: datetime):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 9, 11, 9)
        outer.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)

        grip = QPushButton()
        grip.setObjectName("iconbtn")
        grip.setIcon(icons.icon("grip", COLORS["ink3"], 14))
        grip.setFixedWidth(16)
        grip.setCursor(Qt.OpenHandCursor)
        grip.setToolTip("Drag to reorder this todo")
        grip.pressed.connect(self._begin_drag)
        row.addWidget(grip)

        self.check = QCheckBox()
        self.check.setChecked(self.todo.done)
        self.check.setToolTip("Mark this todo done (undoable for a few seconds)")
        self.check.toggled.connect(self._on_check)
        row.addWidget(self.check, 0, Qt.AlignTop)

        self.title = QLabel(self.todo.title)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if self.todo.in_progress:
            self.title.setStyleSheet("color:#d6c9ff; font-size:13.5px;")
        self.title.setToolTip("Double-click to edit")
        # Inline title edit (FEATURE 6): double-click the label swaps in a QLineEdit.
        self.title.mouseDoubleClickEvent = lambda e: self._edit_title()
        row.addWidget(self.title, 1)

        self.subtask_count = None
        if self.todo.subtasks:
            self.subtask_count = QLabel(
                f"{sum(s.done for s in self.todo.subtasks)}/{len(self.todo.subtasks)}")
            self.subtask_count.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")
            row.addWidget(self.subtask_count)

        # Prep-note / protocol link (FEATURE 4). Only when a NoteStore is wired.
        self.note_btn = None
        if self.note_store is not None:
            self.note_btn = QPushButton()
            self.note_btn.setObjectName("iconbtn")
            self.note_btn.setIcon(icons.icon("file", COLORS["ink2"], 13))
            self.note_btn.setFixedSize(24, 24)
            self.note_btn.clicked.connect(self._on_note_btn)
            self._sync_note_btn()
            row.addWidget(self.note_btn)

        # Meeting-Prep: only meetings can be prepped, and only with a NoteStore to write into.
        self.prep_btn = None
        if self.note_store is not None and self.todo.category == "meeting":
            self.prep_btn = QPushButton()
            self.prep_btn.setObjectName("iconbtn")
            self.prep_btn.setFixedSize(24, 24)
            self.prep_btn.clicked.connect(lambda: self.prep_requested.emit(self.todo))
            self._sync_prep_btn()
            row.addWidget(self.prep_btn)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("iconbtn")
        running = self.todo.in_progress or self.todo.timer_running
        self.start_btn.setIcon(icons.icon("pause" if running else "play",
                                          COLORS["accent"] if running else COLORS["ink2"], 13))
        self.start_btn.setFixedSize(24, 24)
        self.start_btn.setToolTip("Stop" if running else "Start (Serenity goes to Working)")
        self.start_btn.clicked.connect(self._toggle_timer)
        row.addWidget(self.start_btn)

        # Reminder bell (H5 / task 9): only for due-dated todos (reminders need a due)
        self.reminder_btn = None
        if self.todo.due:
            self.reminder_btn = QPushButton()
            self.reminder_btn.setObjectName("iconbtn")
            self.reminder_btn.setIcon(icons.icon("bell", COLORS["ink2"], 13))
            self.reminder_btn.setFixedSize(24, 24)
            self.reminder_btn.setToolTip("Set reminders")
            self.reminder_btn.clicked.connect(self._on_reminder_btn)
            row.addWidget(self.reminder_btn)

        outer.addLayout(row)

        # chips
        chips = QHBoxLayout()
        chips.setSpacing(5)
        chips.setContentsMargins(24, 0, 0, 0)
        added = False
        self.due_chip = None
        self.timer_chip = None
        if self.todo.due:
            kind = "soon" if ranking.is_due_soon(self.todo, now) else (
                "warn" if ranking.is_due_warn(self.todo, now) else "due")
            self.due_chip = _chip(self._due_label(now), kind)
            chips.addWidget(self.due_chip)
            added = True
        if self.todo.timer_running or self.todo.timer_seconds:
            self.timer_chip = _chip(self._timer_label(now), "timer")
            chips.addWidget(self.timer_chip)
            added = True
        if self.todo.recurring:
            chips.addWidget(_chip(self.todo.recurring, "rec"))
            added = True
        if self.todo.category:
            chips.addWidget(_chip(f"@{self.todo.category}"))
            added = True
        if added:
            chips.addStretch(1)
            outer.addLayout(chips)

        # Ring banner (Phase H): when reminder_active, show time-left + Snooze/Dismiss
        self._build_ring_banner(outer, now)

        # deadline "heat" fill: a thin bar that grows as the deadline nears.
        self.heat = QProgressBar()
        self.heat.setTextVisible(False)
        self.heat.setFixedHeight(3)
        self.heat.setRange(0, 1000)
        self.heat.setContentsMargins(24, 0, 0, 0)
        outer.addWidget(self.heat)
        self._apply_heat(now)

        # Linked-note title, shown inline when a prep/protocol note is attached (FEATURE 4).
        self.note_link = QLabel()
        self.note_link.setContentsMargins(24, 0, 0, 0)
        self.note_link.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        self.note_link.hide()
        outer.addWidget(self.note_link)
        if self.note_store is not None:
            self._sync_note_link()

        # subtasks
        if self.todo.subtasks:
            for st in self.todo.subtasks:
                outer.addLayout(self._subtask_row(st))
        add_st = QLineEdit()
        add_st.setPlaceholderText("Add a sub-step...")
        add_st.returnPressed.connect(lambda e=add_st: self._add_subtask(e))
        add_st.setStyleSheet("font-size:11.5px;")
        outer.addWidget(add_st)

    def _due_label(self, now: datetime) -> str:
        due = self.todo.due
        delta = (due - now).total_seconds()
        if abs(delta) < 3600:
            mins = int(delta // 60)
            return f"in {mins} min" if mins >= 0 else f"{-mins} min overdue"
        if due.date() == now.date():
            return f"today {due.strftime('%H:%M')}"
        return due.strftime("%b %d, %H:%M")

    def _timer_label(self, now: datetime) -> str:
        secs = self.todo.live_timer_seconds(now)
        if self.todo.timer_running:
            return f"{secs // 60}:{secs % 60:02d}"
        return f"{secs // 60} min"

    def _apply_heat(self, now: datetime) -> None:
        heat = ranking.due_heat(self.todo, now) if self.todo.due else 0.0
        self.heat.setValue(int(heat * 1000))
        self.heat.setVisible(heat > 0.0)
        # warmer color as it fills: sky -> amber -> rose
        color = "#7dd3fc" if heat < 0.5 else ("#fbbf24" if heat < 0.85 else "#fca5a5")
        self.heat.setStyleSheet(
            "QProgressBar { background: transparent; border: none; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 1px; }}"
        )

    def needs_tick(self) -> bool:
        """True while this card has something to animate (live timer or near deadline)."""
        if self.todo.timer_running:
            return True
        return self.todo.due is not None and ranking.due_heat(self.todo, datetime.now()) > 0.0

    def tick(self, now: datetime) -> None:
        """Update the live timer chip + deadline heat without rebuilding the card."""
        if self.timer_chip is not None and self.todo.timer_running:
            self.timer_chip.setText(self._timer_label(now))
        if self.due_chip is not None:
            self.due_chip.setText(self._due_label(now))
        self._apply_heat(now)

    def _build_ring_banner(self, outer: QVBoxLayout, now: datetime) -> None:
        """Build the reminder ring banner when reminder_active is set."""
        if self.todo.reminder_active is None:
            return

        # Banner row: icon + time-left text + Snooze + Dismiss buttons
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 0, 0)
        row.setSpacing(8)

        # Icon + time-left text
        time_text = ranking.format_time_left(self.todo.due, now) if self.todo.due else "due"
        banner_label = QLabel(f"⏰ {time_text}")
        banner_label.setStyleSheet("color:#fca5a5; font-size:11px;")
        row.addWidget(banner_label)

        # Snooze button
        snooze_btn = QPushButton("Snooze")
        snooze_btn.setObjectName("snooze_btn")
        snooze_btn.setStyleSheet("font-size:10px; padding:2px 8px;")
        snooze_btn.clicked.connect(lambda: self.ring_snooze.emit(self.todo))
        row.addWidget(snooze_btn)

        # Dismiss button
        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.setObjectName("dismiss_btn")
        dismiss_btn.setStyleSheet("font-size:10px; padding:2px 8px;")
        dismiss_btn.clicked.connect(lambda: self.ring_dismiss.emit(self.todo))
        row.addWidget(dismiss_btn)

        row.addStretch(1)
        outer.addLayout(row)

    def _subtask_row(self, st: SubTask):
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(st.done)
        lab = QLabel(st.text)
        lab.setStyleSheet(
            f"color:{COLORS['ink3'] if st.done else COLORS['ink2']}; font-size:12px;"
            + ("text-decoration: line-through;" if st.done else "")
        )
        lab.setToolTip("Double-click to edit")
        # Inline subtask edit (FEATURE 6): double-click swaps in a QLineEdit on commit persists.
        lab.mouseDoubleClickEvent = lambda e, s=st, la=lab: self._edit_subtask(s, la)
        cb.toggled.connect(lambda v, s=st, la=lab: self._on_subtask(s, v, la))
        row.addWidget(cb)
        row.addWidget(lab, 1)
        return row

    # --- actions ---
    def _on_check(self, checked: bool):
        # Grace period (FEATURE 5): ticking done does NOT complete immediately - it line-throughs
        # the card and tells the view to arm an undo timer; un-ticking tells it to cancel. The
        # timer lives on TodosView (not the card) so it survives a list rebuild mid-window.
        self._strike(checked)
        if checked:
            self.grace_armed.emit(self.todo)
        else:
            self.grace_cancelled.emit(self.todo)

    def _strike(self, on: bool):
        """Apply (or remove) the done-grace line-through on the title."""
        if on:
            self.title.setStyleSheet(
                self.title.styleSheet()
                + "text-decoration: line-through; color:" + COLORS["ink3"] + ";")
        else:
            self.title.setStyleSheet(
                "color:#d6c9ff; font-size:13.5px;" if self.todo.in_progress else "")

    def show_grace_pending(self):
        """Re-show the checked + struck state on a freshly-rebuilt card whose grace timer is
        still running on the view - WITHOUT re-arming (signals blocked); the view owns the timer."""
        self.check.blockSignals(True)
        self.check.setChecked(True)
        self.check.blockSignals(False)
        self._strike(True)

    def _on_subtask(self, st: SubTask, value: bool, lab: QLabel):
        st.done = value
        self.store.update(self.todo)
        all_done = bool(self.todo.subtasks) and all(s.done for s in self.todo.subtasks)
        if value and all_done:
            # Last step ticked -> auto-complete via the grace period. Repaint the chip + this
            # label IN PLACE (a full refresh would tear the card down and drop the grace), then
            # sync the main checkbox: checking it arms grace via _on_check, and the box is the
            # undo handle (un-tick it to cancel).
            lab.setStyleSheet(
                f"color:{COLORS['ink3']}; font-size:12px; text-decoration: line-through;")
            if self.subtask_count is not None:
                self.subtask_count.setText(
                    f"{sum(s.done for s in self.todo.subtasks)}/{len(self.todo.subtasks)}")
            if not self.check.isChecked():
                self.check.setChecked(True)
        else:
            # A non-final tick, or un-ticking a step: if grace was armed via the box, cancel it.
            if self.check.isChecked():
                self.check.setChecked(False)
            self.changed.emit()

    def _add_subtask(self, editor: QLineEdit):
        text = editor.text().strip()
        if not text:
            return
        self.todo.subtasks.append(SubTask(text=text))
        self.store.update(self.todo)
        self.changed.emit()

    # --- inline editing (FEATURE 6) ---
    def _edit_title(self):
        """Swap the title label for a line edit; commit on Enter / focus-out, persist + refresh."""
        editor = QLineEdit(self.todo.title)
        editor.setStyleSheet("font-size:13.5px;")
        # The title label lives in the header row (the card's first layout item).
        lay = self.layout().itemAt(0).layout()
        idx = lay.indexOf(self.title)
        lay.takeAt(idx)
        self.title.hide()
        lay.insertWidget(idx, editor, 1)
        editor.setFocus()
        editor.selectAll()

        def commit():
            text = editor.text().strip()
            if text and text != self.todo.title:
                self.todo.title = text
                self.store.update(self.todo)
            self.changed.emit()

        editor.editingFinished.connect(commit)

    def _edit_subtask(self, st: SubTask, lab: QLabel):
        """Swap a subtask label for a line edit; commit updates the SubTask text + persists."""
        editor = QLineEdit(st.text)
        editor.setStyleSheet("font-size:12px;")
        # Each subtask row is a QHBoxLayout added to the card's outer layout; find the one
        # holding this label and replace the label in place.
        target = None
        for i in range(self.layout().count()):
            sub = self.layout().itemAt(i).layout()
            if sub is not None and sub.indexOf(lab) != -1:
                target = sub
                break
        if target is None:
            return
        idx = target.indexOf(lab)
        target.takeAt(idx)
        lab.hide()
        target.insertWidget(idx, editor, 1)
        editor.setFocus()
        editor.selectAll()

        def commit():
            text = editor.text().strip()
            if text and text != st.text:
                st.text = text
                self.store.update(self.todo)
            self.changed.emit()

        editor.editingFinished.connect(commit)

    # --- linked note (FEATURE 4) ---
    def _sync_note_btn(self):
        """Set the prep/protocol button text+tooltip from whether a note is linked."""
        if self.note_btn is None:
            return
        linked = self._linked_note()
        if linked is not None:
            self.note_btn.setToolTip("Open protocol" if self.todo.category == "meeting"
                                     else "Open note")
        else:
            self.note_btn.setToolTip("Prep note")

    def is_prepped(self) -> bool:
        """Whether this meeting's linked protocol note already carries a prep block.

        The markers in the note ARE the fact - there is no separate flag that could drift."""
        linked = self._linked_note()
        return linked is not None and meeting_prep.is_prepped(linked.body)

    def _sync_prep_btn(self):
        """Tint + hover explanation from whether a prep already exists."""
        if self.prep_btn is None:
            return
        prepped = self.is_prepped()
        self.prep_btn.setIcon(icons.icon("prep", COLORS["accent"] if prepped else COLORS["ink2"], 13))
        self.prep_btn.setToolTip(
            "Prepared - press to rebuild it from the latest protocol and notes" if prepped
            else "Prepare this meeting: carry over what the last protocol left open, "
                 "plus related notes and your own open todos")

    def _sync_note_link(self):
        """Show the linked note's title inline when one is attached, else hide the label."""
        linked = self._linked_note()
        if linked is not None:
            self.note_link.setText(f"\U0001F4CE {linked.title}")
            self.note_link.show()
        else:
            self.note_link.hide()

    def _linked_note(self):
        """The first live linked Note (skipping ids whose note was purged OR trashed), or None."""
        if self.note_store is None:
            return None
        for nid in self.todo.linked_note_ids:
            n = self.note_store.get(nid)
            if n is not None and not n.deleted:
                return n
        return None

    def _on_note_btn(self):
        """Open the linked note, or create one (prefilled) on first click and open it."""
        linked = self._linked_note()
        if linked is None:
            if self.todo.category == "meeting":
                body = protocol_template()
            else:
                body = f"# {self.todo.title}\n\n"
            # Backlink note -> todo: a reference line in the body survives the round-trip and
            # is human-readable. (The Note model has no dedicated field; a tag with the todo id
            # would round-trip too but reads as noise.)
            body += f"\nLinked todo: {self.todo.title} ({self.todo.id})\n"
            # the prep note inherits its todo's stamp - it belongs to that todo's
            # world, not to whatever is running right now (Phase C R12)
            note = self.note_store.create(self.todo.title or "Untitled", body=body,
                                          state_tag=self.todo.state_tag,
                                          context=self.todo.context)
            self.todo.linked_note_ids.append(note.id)
            self.store.update(self.todo)
            self._sync_note_btn()
            self._sync_note_link()
            linked = note
        self.open_note.emit(linked)

    def _toggle_timer(self):
        if self.todo.in_progress or self.todo.timer_running:
            self.store.stop_timer(self.todo.id)
        else:
            self.store.start_timer(self.todo.id)
            self.started.emit(self.todo)
        self.changed.emit()

    def _on_reminder_btn(self):
        """Open a reminder picker popover menu; commit selection once on menu close."""
        if self.reminder_btn is None or self.todo.due is None:
            return

        # Create a popover menu with the ReminderPicker as a QWidgetAction
        menu = QMenu(self)
        picker = ReminderPicker(
            due_provider=lambda: self.todo.due,
            initial=self.todo.reminder_offsets,
            fired=self.todo.reminder_fired,
        )

        # Trigger refresh after widget is shown
        picker.refresh()

        # Commit ONCE on menu close, not per-toggle (fixes double-save + refresh spam)
        def _commit_on_close():
            offsets = picker.selected()
            reminders.arm(self.todo, offsets, datetime.now())
            self.store.update(self.todo, persist=False)
            self.reminders_changed.emit(self.todo)

        menu.aboutToHide.connect(_commit_on_close)

        action = QWidgetAction(menu)
        action.setDefaultWidget(picker)
        menu.addAction(action)
        menu.exec(self.reminder_btn.mapToGlobal(self.reminder_btn.rect().bottomLeft()))

    def _begin_drag(self):
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.todo.id)
        drag.setMimeData(mime)
        # drag.exec spins a nested event loop: a boundary-timer refresh firing inside it
        # would deleteLater this very card mid-drag - flag the window so it defers.
        self.drag_active.emit(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.drag_active.emit(False)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        src = e.mimeData().text()
        if src and src != self.todo.id:
            self.reorder.emit(src, self.todo.id)
        e.acceptProposedAction()


class TodosView(QWidget):
    """Add bar + ranked todo list."""

    todo_completed = Signal(object)
    todo_started = Signal(object)
    todo_added = Signal(object)
    open_note = Signal(object)            # forwards a linked Note to open in the Notes tab
    prep_requested = Signal(object)       # forwards a meeting Todo whose Prep button was pressed
    reminders_changed = Signal(object)    # emits todo when reminders are modified
    reveal_context = Signal(str)          # blurred peek confirmed -> shell.set_context (R-D)
    ring_acked = Signal(object)           # emits todo when Snooze/Dismiss acknowledged (Phase H)

    def __init__(self, store, settings, note_store=None, stamp=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.settings = settings
        # The NoteStore (or None) threaded to each card for the prep/protocol link (FEATURE 4).
        self.note_store = note_store
        # zero-arg callable -> (state_tag, context), read at SAVE time (Phase C R10)
        self._stamp = stamp
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        addrow = QFrame()
        addrow.setObjectName("card")
        al = QHBoxLayout(addrow)
        al.setContentsMargins(9, 4, 9, 4)
        plus = QLabel()
        plus.setPixmap(icons.pixmap("plus", COLORS["accent"], 15))
        al.addWidget(plus)
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("Add a todo - try \"call Tom tomorrow 5pm\"")
        self.add_input.setStyleSheet("border:none; background:transparent;")
        self.add_input.returnPressed.connect(self._add)
        al.addWidget(self.add_input, 1)
        lay.addWidget(addrow)

        # Phase C: the deselectable "current state" filter chip + hidden-count hint.
        self.state_chip = StateFilterChip()
        self.state_chip.toggled_filter.connect(self.refresh)
        lay.addWidget(self.state_chip)
        self.filter_notice = QLabel()
        self.filter_notice.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        self.filter_notice.hide()
        lay.addWidget(self.filter_notice)

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        container = QWidget()
        container.setLayout(self.list_box)
        lay.addWidget(container)
        lay.addStretch(1)

        self._cards: list[TodoCard] = []
        self._peek_widgets: list[PeekPlaceholder] = []
        # FEATURE 5 done-grace timers live HERE (keyed by todo.id), not on the cards, so they
        # survive a refresh() that tears down and rebuilds every card mid-window.
        self._grace_timers: dict[str, QTimer] = {}
        # 1s tick that animates running timers + deadline heat without rebuilding
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        # R-A: single-shot re-classification timer - a HIDDEN todo crossing into the urgent
        # band has no card/tick to surface it, so refresh() arms this for the earliest
        # hide->peek boundary. Input-uncorrelated triggers route through safe_refresh so
        # they never tear down an in-flight inline edit or drag.
        self._drag_active = False
        self._boundary_timer = QTimer(self)
        self._boundary_timer.setSingleShot(True)
        self._boundary_timer.timeout.connect(self.safe_refresh)
        self.refresh()

    def safe_refresh(self):
        """refresh() for input-UNCORRELATED triggers (boundary timer, wake-from-sleep).

        A bare refresh deleteLater's every card - destroying a half-typed inline title
        edit or the source card of an in-flight drag. When either is live, retry in 2s
        instead of rebuilding under the user's hands."""
        from PySide6.QtWidgets import QApplication
        focus = QApplication.focusWidget()
        editing = isinstance(focus, QLineEdit) and any(
            c.isAncestorOf(focus) for c in self._cards)
        if editing or self._drag_active:
            self._boundary_timer.start(2000)
            return
        self.refresh()

    def _add(self):
        text = self.add_input.text().strip()
        if not text:
            return
        cap = parse_capture(text)
        st, ctx = self._stamp() if self._stamp else (None, None)
        todo = Todo(title=cap.title or text, due=cap.date, recurring=cap.recurring,
                    category=cap.category, tags=cap.tags, state_tag=st, context=ctx)
        self.store.add(todo)
        if cap.tags:
            if self.settings.add_tags(cap.tags):
                self.settings.save()
        self.add_input.clear()
        self.refresh()
        self.todo_added.emit(todo)

    def set_state_filter(self, key, label, color, checked):
        """Shell-driven chip sync (R1/R4/R7): key=None hides the chip (axis off)."""
        if key is None:
            self.state_chip.clear()
        else:
            self.state_chip.set_state(key, label, color, checked)
        self.refresh()

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []
        self._peek_widgets = []
        now = datetime.now()
        ranked = self.store.active(now=now)
        ctx = self.settings.context() if self.settings else None
        skey = self.state_chip.active_key()
        # Urgency-peek classification (rank order preserved, so urgent peeks sit on top):
        # grace-pending todos BYPASS classification entirely (R-C: exactly one full card,
        # the un-tick undo handle stays reachable, never counted hidden); urgent filtered
        # todos peek (full card when only the state axis rejected them, blurred placeholder
        # cross-context); only non-urgent filtered todos hide + count toward the hint.
        rows: list[tuple[str, Todo]] = []
        hidden = 0
        hidden_due: list[Todo] = []
        for t in ranked:
            if ctx is None or t.id in self._grace_timers:
                rows.append(("card", t))
                continue
            cls = ranking.peek_class(t, ctx, skey, now)
            # [R-4] Always-render bypass: ringing todos never hide (render full card in-context,
            # blurred placeholder cross-context), regardless of urgency tier.
            if t.reminder_active is not None and cls == "hide":
                cls = ("peek_blurred" if ranking.is_cross_context(t, ctx)
                       else "peek_full")
            if cls == "hide":
                hidden += 1
                if t.due is not None:
                    hidden_due.append(t)
                continue
            rows.append(("blur" if cls == "peek_blurred" else "card", t))
        # R5: count-only hint, only while the chip actively hides items (never in plain browsing)
        if skey is not None and hidden > 0:
            self.filter_notice.setText(f"{hidden} hidden by context/state filter")
            self.filter_notice.show()
        else:
            self.filter_notice.hide()
        for kind, todo in rows:
            if kind == "blur":
                peek = PeekPlaceholder(todo, now=now)
                peek.reveal_requested.connect(
                    lambda c=todo.context: self.reveal_context.emit(c))
                # [Phase H] Ring banner Snooze/Dismiss on cross-context placeholder
                peek.ring_snooze.connect(lambda t=todo: self._on_ring_snooze(t))
                peek.ring_dismiss.connect(lambda t=todo: self._on_ring_dismiss(t))
                self.list_box.addWidget(peek)
                self._peek_widgets.append(peek)
                continue
            card = TodoCard(todo, self.store, now, note_store=self.note_store)
            card.changed.connect(self.refresh)
            card.grace_armed.connect(self._arm_grace)
            card.grace_cancelled.connect(self._cancel_grace)
            card.started.connect(self.todo_started.emit)
            card.reorder.connect(self._on_reorder)
            card.open_note.connect(self.open_note.emit)
            card.prep_requested.connect(self.prep_requested.emit)
            card.reminders_changed.connect(self._on_reminders_changed)
            card.drag_active.connect(self._set_drag_active)
            # [Phase H] Ring banner Snooze/Dismiss on card
            card.ring_snooze.connect(self._on_ring_snooze)
            card.ring_dismiss.connect(self._on_ring_dismiss)
            self.list_box.addWidget(card)
            self._cards.append(card)
            # A grace timer armed before this rebuild keeps running on the view; re-show the
            # pending (checked + struck) state on the fresh card so the completion isn't lost.
            if todo.id in self._grace_timers:
                card.show_grace_pending()
        self._sync_tick_timer()
        self._arm_boundary_timer(hidden_due, now)

    def _arm_boundary_timer(self, hidden_due: list[Todo], now: datetime) -> None:
        """R-A: re-run refresh() at the earliest instant a HIDDEN due-dated todo crosses
        into the urgent band (due - WARN_HOURS), so it surfaces as a peek without any
        user interaction. Disarmed when nothing hidden has a deadline; capped at 24h
        (QTimer int-ms range) - the fired refresh() re-arms for the remainder."""
        boundaries = [ranking.seconds_until_due(t, now) - ranking.WARN_HOURS * 3600
                      for t in hidden_due]
        future = [b for b in boundaries if b > 0]
        if not future:
            self._boundary_timer.stop()
            return
        ms = max(1000, int(min(future) * 1000))
        self._boundary_timer.start(min(ms, 24 * 3600 * 1000))

    def _sync_tick_timer(self):
        """Run the 1s tick only while a card has a live timer or a nearing deadline.
        Blurred peek placeholders count too (R-B) - their countdown is their whole
        information payload, so it must never freeze."""
        if any(w.needs_tick() for w in self._cards + self._peek_widgets):
            if not self._tick_timer.isActive():
                self._tick_timer.start()
        elif self._tick_timer.isActive():
            self._tick_timer.stop()

    def _tick(self):
        now = datetime.now()
        for card in self._cards + self._peek_widgets:
            card.tick(now)
        # a deadline may have just entered the heat window; keep the timer in sync
        self._sync_tick_timer()

    def _on_completed(self, todo: Todo):
        self.store.complete(todo.id)
        self.refresh()
        self.todo_completed.emit(todo)

    def _on_reminders_changed(self, todo: Todo):
        """Reminders modified via card popover: store already updated, save and refresh."""
        self.store.save()
        self.refresh()
        self.reminders_changed.emit(todo)

    def _on_ring_snooze(self, todo: Todo):
        """Snooze button on ring banner: acknowledge_snooze + save + refresh + emit."""
        reminders.acknowledge_snooze(todo, datetime.now())
        self.store.save()
        self.refresh()
        self.ring_acked.emit(todo)

    def _on_ring_dismiss(self, todo: Todo):
        """Dismiss button on ring banner: acknowledge_dismiss + save + refresh + emit."""
        reminders.acknowledge_dismiss(todo)
        self.store.save()
        self.refresh()
        self.ring_acked.emit(todo)

    # --- done-grace timers (FEATURE 5), owned by the view so they survive card rebuilds ---
    def _arm_grace(self, todo: Todo):
        """Ticking a todo done arms a single-shot timer; only on fire does it actually complete.

        [R-10] grace-arm silence: if the todo is ringing (reminder_active or reminder_nudge_at),
        silence it immediately (not at grace commit) so the alarm doesn't blare on a just-ticked task."""
        # [R-10] Silence any active reminder at grace-arm time
        if todo.reminder_active is not None or todo.reminder_nudge_at is not None:
            reminders.silence(todo)
            self.store.save()

        if todo.id in self._grace_timers:
            return
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda tid=todo.id: self._grace_fire(tid))
        self._grace_timers[todo.id] = t
        t.start(max(0, int(self.settings.undo_seconds)) * 1000)

    def _cancel_grace(self, todo: Todo):
        """Un-ticked within the window: drop the pending completion; the todo stays active."""
        t = self._grace_timers.pop(todo.id, None)
        if t is not None:
            t.stop()
            # The R3 grace-render forced this card to show even when the context/state filter
            # would hide it; once the pending completion is gone that exception no longer holds,
            # so rebuild if the todo is now filtered out (else it lingers as a stale card).
            ctx = self.settings.context() if self.settings else None
            if ctx is not None and not states.visible(todo, ctx, self.state_chip.active_key()):
                self.refresh()

    def _grace_fire(self, todo_id: str):
        """The grace window elapsed: complete the todo for real (if it still exists)."""
        self._grace_timers.pop(todo_id, None)
        todo = self.store.get(todo_id)
        if todo is not None:
            self._on_completed(todo)

    def _set_drag_active(self, active: bool):
        self._drag_active = active

    def _on_reorder(self, src_id: str, target_id: str):
        todos = self.store.all()
        src = next((t for t in todos if t.id == src_id), None)
        tgt = next((t for t in todos if t.id == target_id), None)
        if src and tgt:
            src.order = tgt.order - 1
            self.store.save()
            self.refresh()
