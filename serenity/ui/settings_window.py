"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The Settings window - mirrors settings.html (appearance, general, grammar).
Role:    Lets the user edit the state->pose map (multi-image per state), browse the
         image library, set render scale S/M/L, vault path, autostart, hotkey, accent,
         language DE/EN, the 20s undo window, the voice-output (TTS) section (engine,
         per-language voice, speed, volume) and the (Phase-2 stub) AI/voice toggles.
         Saves through core.settings.Settings.

Classes:
- SettingsWindow - tabbed settings dialog; emits `applied` when saved
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..core.poses import POSE_FILES, default_state_map
from .theme import COLORS


def _section(title: str) -> QLabel:
    lab = QLabel(title)
    lab.setObjectName("sectLabel")
    return lab


def _scroll(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    return sa


class SettingsWindow(QDialog):
    applied = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Serenity - Settings")
        self.setMinimumSize(560, 600)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self._appearance_tab()), "Appearance")
        self.tabs.addTab(_scroll(self._images_tab()), "Images")
        self.tabs.addTab(_scroll(self._general_tab()), "General")
        self.tabs.addTab(_scroll(self._grammar_tab()), "Voice commands")
        lay.addWidget(self.tabs, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("Close")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        foot.addWidget(cancel)
        foot.addWidget(save)
        lay.addLayout(foot)

    # ---------- Appearance: render scale + state->pose map editor ----------
    def _appearance_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_section("Render scale (avatar size in the dock)"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["S (128px)", "M (152px)", "L (192px)"])
        self.scale_combo.setCurrentIndex({"S": 0, "M": 1, "L": 2}.get(self.settings.render_scale, 1))
        lay.addWidget(self.scale_combo)

        lay.addWidget(_section("Pose for each state (one or more images per state)"))
        info = QLabel("Comma-separated pose keys. A random one is picked per transition.")
        info.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(info)

        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(11, 11, 11, 11)
        self.state_edits = {}
        smap = self.settings.state_map() or default_state_map()
        for r, (state, keys) in enumerate(smap.items()):
            grid.addWidget(QLabel(state), r, 0)
            edit = QLineEdit(", ".join(keys))
            self.state_edits[state] = edit
            grid.addWidget(edit, r, 1)
        lay.addWidget(card)
        keys_hint = QLabel("Available poses: " + ", ".join(sorted(POSE_FILES.keys())))
        keys_hint.setWordWrap(True)
        keys_hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:10.5px;")
        lay.addWidget(keys_hint)
        lay.addStretch(1)
        return w

    # ---------- Images library ----------
    def _images_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_section(f"Image library - {len(POSE_FILES)} poses ship with Serenity"))
        lst = QListWidget()
        lst.setIconSize(QSize(64, 64))
        for key, fname in sorted(POSE_FILES.items()):
            p = paths.poses_dir() / fname
            item = QListWidgetItem(f"{key}  -  {fname}")
            if p.exists():
                item.setIcon(QIcon(QPixmap(str(p)).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            lst.addItem(item)
        lay.addWidget(lst, 1)
        return w

    # ---------- General ----------
    def _general_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(_section("Vault"))
        vrow = QHBoxLayout()
        self.vault_edit = QLineEdit(self.settings.vault_path)
        browse = QPushButton("Change")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._pick_vault)
        vrow.addWidget(self.vault_edit, 1)
        vrow.addWidget(browse)
        lay.addLayout(vrow)

        lay.addWidget(_section("Startup and shortcuts"))
        self.autostart_cb = QCheckBox("Start Serenity on login (to tray) - Windows only")
        self.autostart_cb.setChecked(self.settings.autostart)
        lay.addWidget(self.autostart_cb)
        hrow = QHBoxLayout()
        hrow.addWidget(QLabel("Global capture hotkey"))
        self.hotkey_edit = QLineEdit(self.settings.global_hotkey)
        hrow.addWidget(self.hotkey_edit, 1)
        lay.addLayout(hrow)

        lay.addWidget(_section("AI and voice - on device (Phase 2)"))
        self.ai_cb = QCheckBox("Language model routing (llama-cpp-python + Qwen3-4B) - stubbed")
        self.ai_cb.setChecked(self.settings.ai_enabled)
        self.voice_cb = QCheckBox("Local voice transcription (whisper.cpp) - stubbed")
        self.voice_cb.setChecked(self.settings.voice_enabled)
        for cb in (self.ai_cb, self.voice_cb):
            lay.addWidget(cb)
        stub = QLabel("These wire up Phase-2 backends. In Phase 1 the entry points exist "
                      "but no model runs and no audio is captured.")
        stub.setWordWrap(True)
        stub.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(stub)

        lay.addWidget(_section("Voice output - Serenity reads her lines aloud"))
        self.tts_cb = QCheckBox("Speak Serenity's lines (local, on device)")
        self.tts_cb.setChecked(self.settings.tts_enabled)
        lay.addWidget(self.tts_cb)
        erow = QHBoxLayout()
        erow.addWidget(QLabel("Engine"))
        self.tts_engine_combo = QComboBox()
        # (id, label) - Piper is the local-first default; SAPI is the Windows baseline.
        self._tts_engines = [
            ("piper", "Piper - local neural voices (recommended)"),
            ("sapi", "Windows built-in (SAPI5) - offline baseline"),
            ("noop", "Off / silent"),
        ]
        for _id, label in self._tts_engines:
            self.tts_engine_combo.addItem(label)
        idx = next((i for i, (e, _) in enumerate(self._tts_engines)
                    if e == self.settings.tts_engine), 0)
        self.tts_engine_combo.setCurrentIndex(idx)
        erow.addWidget(self.tts_engine_combo, 1)
        lay.addLayout(erow)
        dvrow = QHBoxLayout()
        dvrow.addWidget(QLabel("German voice"))
        self.tts_voice_de_edit = QLineEdit(self.settings.tts_voice_de)
        dvrow.addWidget(self.tts_voice_de_edit, 1)
        lay.addLayout(dvrow)
        evrow = QHBoxLayout()
        evrow.addWidget(QLabel("English voice"))
        self.tts_voice_en_edit = QLineEdit(self.settings.tts_voice_en)
        evrow.addWidget(self.tts_voice_en_edit, 1)
        lay.addLayout(evrow)
        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Speed"))
        self.tts_rate_slider = QSlider(Qt.Horizontal)
        self.tts_rate_slider.setRange(50, 200)            # 0.50x .. 2.00x
        self.tts_rate_slider.setValue(int(self.settings.tts_rate * 100))
        self.tts_rate_label = QLabel(f"{self.settings.tts_rate:.2f}x")
        self.tts_rate_slider.valueChanged.connect(
            lambda v: self.tts_rate_label.setText(f"{v / 100:.2f}x"))
        rrow.addWidget(self.tts_rate_slider, 1)
        rrow.addWidget(self.tts_rate_label)
        lay.addLayout(rrow)
        volrow = QHBoxLayout()
        volrow.addWidget(QLabel("Volume"))
        self.tts_vol_slider = QSlider(Qt.Horizontal)
        self.tts_vol_slider.setRange(0, 100)
        self.tts_vol_slider.setValue(int(self.settings.tts_volume * 100))
        self.tts_vol_label = QLabel(f"{int(self.settings.tts_volume * 100)}%")
        self.tts_vol_slider.valueChanged.connect(
            lambda v: self.tts_vol_label.setText(f"{v}%"))
        volrow.addWidget(self.tts_vol_slider, 1)
        volrow.addWidget(self.tts_vol_label)
        lay.addLayout(volrow)
        tts_hint = QLabel("Piper voices (.onnx) live in the voices folder in your config "
                          "dir. Voice ids look like de_DE-kerstin-low and en_US-amy-medium. "
                          "Local only - nothing is sent to the cloud.")
        tts_hint.setWordWrap(True)
        tts_hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(tts_hint)

        lay.addWidget(_section("Language"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["English (en)", "Deutsch (de)"])
        self.lang_combo.setCurrentIndex(1 if self.settings.language == "de" else 0)
        lay.addWidget(self.lang_combo)

        lay.addWidget(_section("Theme accent"))
        self.accent_edit = QLineEdit(self.settings.accent)
        lay.addWidget(self.accent_edit)

        lay.addWidget(_section("Capture and safety"))
        urow = QHBoxLayout()
        urow.addWidget(QLabel("Undo window"))
        self.undo_slider = QSlider(Qt.Horizontal)
        self.undo_slider.setRange(5, 40)
        self.undo_slider.setSingleStep(5)
        self.undo_slider.setValue(self.settings.undo_seconds)
        self.undo_label = QLabel(f"{self.settings.undo_seconds} s")
        self.undo_slider.valueChanged.connect(lambda v: self.undo_label.setText(f"{v} s"))
        urow.addWidget(self.undo_slider, 1)
        urow.addWidget(self.undo_label)
        lay.addLayout(urow)
        lay.addStretch(1)
        return w

    # ---------- Voice commands help ----------
    def _grammar_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_section("Intent keywords"))
        for line in [
            "Termin / Meeting -> meeting",
            "Notiz / Note / Merk dir -> note",
            "Todo / Aufgabe / Erledige -> todo",
            "Erinnerung / Reminder -> todo + reminder",
            "Idee / Idea -> note (idea)",
            "Frage / Was / Wann / Wie -> Ask-Your-Vault (Phase 2)",
        ]:
            lab = QLabel(line)
            lab.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
            lay.addWidget(lab)
        lay.addWidget(_section("Natural-language dates"))
        for line in ["montag 14.7 8:00", "morgen 17 Uhr", "naechste Woche", "in 30 min",
                     "jeden Werktag (recurring)"]:
            lab = QLabel(line)
            lab.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
            lay.addWidget(lab)
        lay.addWidget(_section("Entities"))
        for line in ["mit <Person> / with <Person>", "#tag", "@kategorie"]:
            lab = QLabel(line)
            lab.setStyleSheet(f"color:{COLORS['ink2']}; font-size:12px;")
            lay.addWidget(lab)
        note = QLabel("She always confirms before writing to the vault, with the undo window above.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    def _pick_vault(self):
        d = QFileDialog.getExistingDirectory(self, "Choose vault folder", self.vault_edit.text())
        if d:
            self.vault_edit.setText(d)

    def _save(self):
        self.settings.render_scale = ["S", "M", "L"][self.scale_combo.currentIndex()]
        self.settings.vault_path = self.vault_edit.text().strip() or self.settings.vault_path
        self.settings.autostart = self.autostart_cb.isChecked()
        self.settings.global_hotkey = self.hotkey_edit.text().strip()
        self.settings.ai_enabled = self.ai_cb.isChecked()
        self.settings.voice_enabled = self.voice_cb.isChecked()
        self.settings.tts_enabled = self.tts_cb.isChecked()
        self.settings.tts_engine = self._tts_engines[self.tts_engine_combo.currentIndex()][0]
        self.settings.tts_voice_de = self.tts_voice_de_edit.text().strip() or self.settings.tts_voice_de
        self.settings.tts_voice_en = self.tts_voice_en_edit.text().strip() or self.settings.tts_voice_en
        self.settings.tts_rate = self.tts_rate_slider.value() / 100
        self.settings.tts_volume = self.tts_vol_slider.value() / 100
        self.settings.language = "de" if self.lang_combo.currentIndex() == 1 else "en"
        self.settings.accent = self.accent_edit.text().strip() or self.settings.accent
        self.settings.undo_seconds = self.undo_slider.value()
        # parse the state->pose map edits
        new_map = {}
        for state, edit in self.state_edits.items():
            keys = [k.strip() for k in edit.text().split(",") if k.strip() in POSE_FILES]
            if keys:
                new_map[state] = keys
        self.settings.state_pose_map = new_map
        # autostart side effect (Windows only)
        from .platform_win import set_autostart
        set_autostart(self.settings.autostart)
        self.settings.save()
        self.applied.emit()
        self.accept()
