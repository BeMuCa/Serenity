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
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core import ranking
from ..core.models import SubTask, Todo
from ..core.parser import parse_capture
from . import icons
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
    completed = Signal(object)            # emits the Todo
    started = Signal(object)
    reorder = Signal(str, str)            # (dragged_id, target_id)

    def __init__(self, todo: Todo, store, now: datetime, parent=None):
        super().__init__(parent)
        self.todo = todo
        self.store = store
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
        grip.pressed.connect(self._begin_drag)
        row.addWidget(grip)

        self.check = QCheckBox()
        self.check.setChecked(self.todo.done)
        self.check.toggled.connect(self._on_check)
        row.addWidget(self.check, 0, Qt.AlignTop)

        title = QLabel(self.todo.title)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if self.todo.in_progress:
            title.setStyleSheet("color:#d6c9ff; font-size:13.5px;")
        row.addWidget(title, 1)

        if self.todo.subtasks:
            sc = QLabel(f"{sum(s.done for s in self.todo.subtasks)}/{len(self.todo.subtasks)}")
            sc.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10px;")
            row.addWidget(sc)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("iconbtn")
        running = self.todo.in_progress or self.todo.timer_running
        self.start_btn.setIcon(icons.icon("pause" if running else "play",
                                          COLORS["accent"] if running else COLORS["ink2"], 13))
        self.start_btn.setFixedSize(24, 24)
        self.start_btn.setToolTip("Stop" if running else "Start (Serenity goes to Working)")
        self.start_btn.clicked.connect(self._toggle_timer)
        row.addWidget(self.start_btn)
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

        # deadline "heat" fill: a thin bar that grows as the deadline nears.
        self.heat = QProgressBar()
        self.heat.setTextVisible(False)
        self.heat.setFixedHeight(3)
        self.heat.setRange(0, 1000)
        self.heat.setContentsMargins(24, 0, 0, 0)
        outer.addWidget(self.heat)
        self._apply_heat(now)

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

    def _subtask_row(self, st: SubTask):
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(st.done)
        cb.toggled.connect(lambda v, s=st: self._on_subtask(s, v))
        lab = QLabel(st.text)
        lab.setStyleSheet(
            f"color:{COLORS['ink3'] if st.done else COLORS['ink2']}; font-size:12px;"
            + ("text-decoration: line-through;" if st.done else "")
        )
        row.addWidget(cb)
        row.addWidget(lab, 1)
        return row

    # --- actions ---
    def _on_check(self, checked: bool):
        if checked:
            self.completed.emit(self.todo)

    def _on_subtask(self, st: SubTask, value: bool):
        st.done = value
        # auto-complete the todo when all steps done
        if self.todo.subtasks and all(s.done for s in self.todo.subtasks):
            self.completed.emit(self.todo)
        else:
            self.store.update(self.todo)
            self.changed.emit()

    def _add_subtask(self, editor: QLineEdit):
        text = editor.text().strip()
        if not text:
            return
        self.todo.subtasks.append(SubTask(text=text))
        self.store.update(self.todo)
        self.changed.emit()

    def _toggle_timer(self):
        if self.todo.in_progress or self.todo.timer_running:
            self.store.stop_timer(self.todo.id)
        else:
            self.store.start_timer(self.todo.id)
            self.started.emit(self.todo)
        self.changed.emit()

    def _begin_drag(self):
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.todo.id)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

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

    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store = store
        self.settings = settings
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

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        container = QWidget()
        container.setLayout(self.list_box)
        lay.addWidget(container)
        lay.addStretch(1)

        self._cards: list[TodoCard] = []
        # 1s tick that animates running timers + deadline heat without rebuilding
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self.refresh()

    def _add(self):
        text = self.add_input.text().strip()
        if not text:
            return
        cap = parse_capture(text)
        todo = Todo(title=cap.title or text, due=cap.date, recurring=cap.recurring,
                    category=cap.category, tags=cap.tags)
        self.store.add(todo)
        if cap.tags:
            if self.settings.add_tags(cap.tags):
                self.settings.save()
        self.add_input.clear()
        self.refresh()
        self.todo_added.emit(todo)

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []
        now = datetime.now()
        for todo in self.store.active(now=now):
            card = TodoCard(todo, self.store, now)
            card.changed.connect(self.refresh)
            card.completed.connect(self._on_completed)
            card.started.connect(self.todo_started.emit)
            card.reorder.connect(self._on_reorder)
            self.list_box.addWidget(card)
            self._cards.append(card)
        self._sync_tick_timer()

    def _sync_tick_timer(self):
        """Run the 1s tick only while a card has a live timer or a nearing deadline."""
        if any(c.needs_tick() for c in self._cards):
            if not self._tick_timer.isActive():
                self._tick_timer.start()
        elif self._tick_timer.isActive():
            self._tick_timer.stop()

    def _tick(self):
        now = datetime.now()
        for card in self._cards:
            card.tick(now)
        # a deadline may have just entered the heat window; keep the timer in sync
        self._sync_tick_timer()

    def _on_completed(self, todo: Todo):
        self.store.complete(todo.id)
        self.refresh()
        self.todo_completed.emit(todo)

    def _on_reorder(self, src_id: str, target_id: str):
        todos = self.store.all()
        src = next((t for t in todos if t.id == src_id), None)
        tgt = next((t for t in todos if t.id == target_id), None)
        if src and tgt:
            src.order = tgt.order - 1
            self.store.save()
            self.refresh()
