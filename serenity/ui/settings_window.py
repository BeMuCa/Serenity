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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..core.poses import POSE_FILES, default_state_map
from ..core.voice_clones import CloneRegistry
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

    def __init__(self, settings, parent=None, perf=None):
        super().__init__(parent)
        self.settings = settings
        # Optional PerfSampler (core.perf) for the AI & Voice status panel's last-minute
        # performance history. None on a plain open (the panel then shows "no samples yet");
        # the shell passes its live sampler so the rolling window is real.
        self.perf = perf
        # The cloned-voice registry ("drop a clip, pick the language, get that voice").
        voices_dir = getattr(settings, "voices_dir", "") or paths.voices_dir()
        self.voices_dir = voices_dir
        self.clones = CloneRegistry(voices_dir)
        self.setWindowTitle("Serenity - Settings")
        self.setMinimumSize(560, 600)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self._appearance_tab()), "Appearance")
        self.tabs.addTab(_scroll(self._images_tab()), "Images")
        self.tabs.addTab(_scroll(self._general_tab()), "General")
        self.tabs.addTab(_scroll(self._status_tab()), "AI and voice")
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

        lay.addWidget(_section("Meaning search - embedding model (advanced)"))
        from ..core.semantic import MODEL_REGISTRY, DEFAULT_MODEL_KEY
        self._embed_presets = list(MODEL_REGISTRY.items())  # [(key, meta), ...]
        emrow = QHBoxLayout()
        emrow.addWidget(QLabel("Model"))
        self.embed_model_combo = QComboBox()
        for key, meta in self._embed_presets:
            self.embed_model_combo.addItem(meta["label"], key)
        self.embed_model_combo.addItem("Custom fastembed model id ...", "__custom__")
        cur = (self.settings.embedding_model or DEFAULT_MODEL_KEY).strip()
        preset_keys = [k for k, _ in self._embed_presets]
        if cur in preset_keys:
            self.embed_model_combo.setCurrentIndex(preset_keys.index(cur))
        else:
            self.embed_model_combo.setCurrentIndex(len(preset_keys))  # the __custom__ row
        emrow.addWidget(self.embed_model_combo, 1)
        lay.addLayout(emrow)
        # Free-text custom id (only meaningful when the dropdown is on "Custom ...").
        ecrow = QHBoxLayout()
        ecrow.addWidget(QLabel("Custom id"))
        self.embed_custom_edit = QLineEdit("" if cur in preset_keys else cur)
        self.embed_custom_edit.setPlaceholderText("e.g. intfloat/multilingual-e5-large")
        ecrow.addWidget(self.embed_custom_edit, 1)
        lay.addLayout(ecrow)
        embed_hint = QLabel("Default is multilingual MPNet (best DE+EN). Pick a preset or "
                            "enter any fastembed-supported model id. Changing the model "
                            "rebuilds the search index on next use. Needs the [semantic] "
                            "extra installed - otherwise Meaning search uses keyword search.")
        embed_hint.setWordWrap(True)
        embed_hint.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(embed_hint)

        lay.addWidget(_section("Voice output - Serenity reads her lines aloud"))
        self.tts_cb = QCheckBox("Speak Serenity's lines (local, on device)")
        self.tts_cb.setChecked(self.settings.tts_enabled)
        lay.addWidget(self.tts_cb)

        from ..core.tts import (
            KOKORO_VOICE_INFO,
            kokoro_english_voices,
            kokoro_voices_by_language,
            scan_kokoro_voices,
        )
        self._kokoro_english_voices = kokoro_english_voices
        self._kokoro_voices_by_language = kokoro_voices_by_language
        self._scan_kokoro_voices = scan_kokoro_voices
        self._KOKORO_VOICE_INFO = KOKORO_VOICE_INFO

        # --- English: Kokoro (natural), a Chatterbox clone, or Piper. PER LANGUAGE. ---
        lay.addWidget(QLabel("English"))
        en_erow = QHBoxLayout()
        en_erow.addWidget(QLabel("Engine"))
        self.tts_engine_en_combo = QComboBox()
        # (id, label) - Kokoro is the natural English default; Chatterbox clones a voice.
        self._tts_engines_en = [
            ("kokoro", "Kokoro-82M - natural English (recommended)"),
            ("chatterbox", "Chatterbox - cloned voice (drop a clip below)"),
            ("piper", "Piper - local neural voices"),
            ("noop", "Off / silent"),
        ]
        for _id, label in self._tts_engines_en:
            self.tts_engine_en_combo.addItem(label)
        cur_en = self.settings.tts_engine_en or self.settings.tts_engine
        idx = next((i for i, (e, _) in enumerate(self._tts_engines_en) if e == cur_en), 0)
        self.tts_engine_en_combo.setCurrentIndex(idx)
        en_erow.addWidget(self.tts_engine_en_combo, 1)
        lay.addLayout(en_erow)
        # Kokoro voice picker - English (American + British) by default; other languages
        # behind the "show all languages" toggle. Plus a folder scan for hand-added voices.
        kvrow = QHBoxLayout()
        kvrow.addWidget(QLabel("Kokoro voice"))
        self.tts_voice_kokoro_combo = QComboBox()
        kvrow.addWidget(self.tts_voice_kokoro_combo, 1)
        lay.addLayout(kvrow)
        self.kokoro_all_langs_cb = QCheckBox("Show all languages (advanced)")
        self.kokoro_all_langs_cb.toggled.connect(self._rebuild_kokoro_voices)
        lay.addWidget(self.kokoro_all_langs_cb)
        self._rebuild_kokoro_voices()
        # English clone picker (used when English engine = Chatterbox).
        encrow = QHBoxLayout()
        encrow.addWidget(QLabel("Cloned voice"))
        self.tts_clone_en_combo = QComboBox()
        self._fill_clone_combo(self.tts_clone_en_combo, "en", self.settings.tts_clone_en)
        encrow.addWidget(self.tts_clone_en_combo, 1)
        lay.addLayout(encrow)
        # Piper English voice (used only when English engine = Piper).
        evrow = QHBoxLayout()
        evrow.addWidget(QLabel("Piper voice"))
        self.tts_voice_en_edit = QLineEdit(self.settings.tts_voice_en)
        evrow.addWidget(self.tts_voice_en_edit, 1)
        lay.addLayout(evrow)

        # --- German: Chatterbox (natural + cloneable) or Piper. Kokoro has no German. ---
        lay.addWidget(QLabel("German"))
        de_erow = QHBoxLayout()
        de_erow.addWidget(QLabel("Engine"))
        self.tts_engine_de_combo = QComboBox()
        # German cannot use Kokoro (no German voices); Chatterbox now offers a natural,
        # cloneable German voice alongside Piper.
        self._tts_engines_de = [
            ("chatterbox", "Chatterbox - natural German, cloneable (recommended)"),
            ("piper", "Piper - local neural voices"),
            ("noop", "Off / silent"),
        ]
        for _id, label in self._tts_engines_de:
            self.tts_engine_de_combo.addItem(label)
        cur_de = self.settings.tts_engine_de or self.settings.tts_engine
        # A legacy 'kokoro' German setting falls back to Piper.
        if cur_de == "kokoro":
            cur_de = "piper"
        didx = next((i for i, (e, _) in enumerate(self._tts_engines_de) if e == cur_de), 0)
        self.tts_engine_de_combo.setCurrentIndex(didx)
        de_erow.addWidget(self.tts_engine_de_combo, 1)
        lay.addLayout(de_erow)
        # German clone picker (used when German engine = Chatterbox).
        decrow = QHBoxLayout()
        decrow.addWidget(QLabel("Cloned voice"))
        self.tts_clone_de_combo = QComboBox()
        self._fill_clone_combo(self.tts_clone_de_combo, "de", self.settings.tts_clone_de)
        decrow.addWidget(self.tts_clone_de_combo, 1)
        lay.addLayout(decrow)
        dvrow = QHBoxLayout()
        dvrow.addWidget(QLabel("Piper voice"))
        self.tts_voice_de_edit = QLineEdit(self.settings.tts_voice_de)
        dvrow.addWidget(self.tts_voice_de_edit, 1)
        lay.addLayout(dvrow)
        de_note = QLabel("Kokoro has no German voices. For German pick Chatterbox (natural, "
                         "and you can clone a voice below) or Piper.")
        de_note.setWordWrap(True)
        de_note.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(de_note)

        # --- Clone a voice: drop a clip, name it, pick the language, save. ---
        lay.addWidget(_section("Clone a voice"))
        clone_help = QLabel("Drop a short, clean reference clip (5-15 s of speech), name "
                            "it, pick its language, and save. The cloned voice becomes "
                            "selectable above when that language uses Chatterbox. Needs "
                            "the Chatterbox engine installed (see the voice extra).")
        clone_help.setWordWrap(True)
        clone_help.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(clone_help)
        crow = QHBoxLayout()
        self.clone_name_edit = QLineEdit()
        self.clone_name_edit.setPlaceholderText("Voice name (e.g. Berk)")
        crow.addWidget(self.clone_name_edit, 1)
        self.clone_lang_combo = QComboBox()
        self.clone_lang_combo.addItem("German (de)", "de")
        self.clone_lang_combo.addItem("English (en)", "en")
        crow.addWidget(self.clone_lang_combo)
        lay.addLayout(crow)
        crow2 = QHBoxLayout()
        self.clone_clip_edit = QLineEdit()
        self.clone_clip_edit.setPlaceholderText("Reference clip (.wav / .mp3 / .flac)")
        pick_clip = QPushButton("Browse")
        pick_clip.setObjectName("ghost")
        pick_clip.clicked.connect(self._pick_clone_clip)
        add_clone = QPushButton("Save clone")
        add_clone.setObjectName("primary")
        add_clone.clicked.connect(self._add_clone)
        crow2.addWidget(self.clone_clip_edit, 1)
        crow2.addWidget(pick_clip)
        crow2.addWidget(add_clone)
        lay.addLayout(crow2)
        self.clone_list = QListWidget()
        self.clone_list.setMaximumHeight(96)
        lay.addWidget(self.clone_list)
        del_clone = QPushButton("Remove selected clone")
        del_clone.setObjectName("ghost")
        del_clone.clicked.connect(self._remove_clone)
        lay.addWidget(del_clone)
        self._refresh_clone_list()

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
        self.tts_cache_cb = QCheckBox("Cache and pre-warm lines (instant replay of repeated lines)")
        self.tts_cache_cb.setChecked(getattr(self.settings, "tts_cache_enabled", True))
        lay.addWidget(self.tts_cache_cb)
        tts_hint = QLabel("Kokoro downloads its model once (~310 MB) into the voices/kokoro "
                          "folder in your config dir; Chatterbox downloads its weights once "
                          "(PyTorch, the voice extra); Piper voices (.onnx) live in the voices "
                          "folder (ids like de_DE-kerstin-low, en_US-amy-medium). Rendered lines "
                          "are cached under voices/cache for instant replay. "
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

    # ---------- AI and voice status + last-minute performance ----------
    def _probe_status(self) -> list[tuple[str, bool, str]]:
        """Probe each on-device backend's `available` flag cheaply. Returns (label, ok, detail).

        Every probe is try/except-wrapped and uses only the existing CHEAP `available` checks
        (make_engine / LlamaCppLLM / FastEmbedBackend._probe + detect_on_ac) - no model loads,
        no downloads. A backend reads 'Active' when its dep + assets are present, else
        'Fallback' (the app keeps working via the silent / keyword / deterministic path)."""
        rows: list[tuple[str, bool, str]] = []

        # Voice (TTS): the engine make_engine would actually build for each language. A real
        # engine (Kokoro / Chatterbox / Piper) -> Active; the silent NoopEngine -> Fallback.
        from ..core.tts import NOOP, make_engine
        for lang, name in (("en", "Voice (English)"), ("de", "Voice (German)")):
            try:
                eng = make_engine(self.settings, lang)
                ok = bool(getattr(eng, "available", False)) and getattr(eng, "name", NOOP) != NOOP
                detail = getattr(eng, "name", NOOP)
            except Exception:
                ok, detail = False, "unavailable"
            rows.append((name, ok, detail if ok else f"{detail} - silent fallback"))

        # Language model (llama-cpp + a local GGUF): Active only when the dep + model file are
        # both present; otherwise Ask / digest fall back to the deterministic path.
        try:
            from ..core.llm import MODELS_SUBDIR, LlamaCppLLM
            llm = LlamaCppLLM(models_dir=paths.config_dir() / MODELS_SUBDIR)
            ok = bool(getattr(llm, "available", False))
            rows.append(("Language model", ok,
                         getattr(llm, "name", "llama-cpp") if ok
                         else "no model - deterministic fallback"))
        except Exception:
            rows.append(("Language model", False, "unavailable - deterministic fallback"))

        # Meaning search (fastembed): Active when the [semantic] dep is importable; otherwise
        # Meaning search degrades to keyword search.
        try:
            from ..core.semantic import FastEmbedBackend
            be = FastEmbedBackend(model=self.settings.embedding_model)
            ok = bool(getattr(be, "available", False))
            rows.append(("Meaning search", ok,
                         getattr(be, "name", "fastembed") if ok
                         else "keyword-search fallback"))
        except Exception:
            rows.append(("Meaning search", False, "keyword-search fallback"))

        # AC power probe (drives whether HEAVY break-time work may run). Tri-state.
        try:
            from ..core.breaktime import detect_on_ac
            ac = detect_on_ac()
            if ac is True:
                rows.append(("Power (AC)", True, "on mains - heavy maintenance allowed"))
            elif ac is False:
                rows.append(("Power (AC)", False, "on battery - heavy maintenance deferred"))
            else:
                rows.append(("Power (AC)", False, "unknown - heavy maintenance deferred"))
        except Exception:
            rows.append(("Power (AC)", False, "unknown - heavy maintenance deferred"))

        return rows

    def _status_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_section("On-device status"))
        intro = QLabel("Everything runs locally. 'Active' means the backend is installed and "
                       "ready; 'Fallback' means Serenity keeps working with a lighter path "
                       "(silent voice, keyword search, or her deterministic lines).")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
        lay.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(11, 11, 11, 11)
        for r, (label, ok, detail) in enumerate(self._probe_status()):
            grid.addWidget(QLabel(label), r, 0)
            badge = QLabel("Active" if ok else "Fallback")
            badge.setStyleSheet(
                f"color:{'#86efac' if ok else COLORS['ink3']}; font-weight:600;")
            grid.addWidget(badge, r, 1)
            det = QLabel(detail)
            det.setStyleSheet(f"color:{COLORS['ink3']}; font-size:11px;")
            grid.addWidget(det, r, 2)
        lay.addWidget(card)

        lay.addWidget(_section("Last-minute performance"))
        perf_card = QFrame()
        perf_card.setObjectName("card")
        pv = QVBoxLayout(perf_card)
        pv.setContentsMargins(11, 11, 11, 11)
        for line in self._perf_lines():
            lab = QLabel(line)
            lab.setStyleSheet(f"color:{COLORS['ink2']}; font-size:11.5px;")
            lab.setWordWrap(True)
            pv.addWidget(lab)
        lay.addWidget(perf_card)
        lay.addStretch(1)
        return w

    def _perf_lines(self) -> list[str]:
        """Human lines for the rolling performance window: a CPU/RSS summary + recent jobs.

        Reads the optional PerfSampler (self.perf). With no sampler, or no samples yet, it
        says so plainly. psutil-less samples carry no cpu / rss numbers, so the summary
        gracefully reports just the sample count then."""
        perf = self.perf
        if perf is None:
            return ["Performance history is sampled while the app runs."]
        try:
            samples = perf.recent_samples()
            jobs = perf.job_history()
        except Exception:
            return ["Performance history is unavailable."]
        if not samples:
            return ["No samples in the last minute yet."]
        cpus = [s.cpu_percent for s in samples if s.cpu_percent is not None]
        rsss = [s.rss_mb for s in samples if s.rss_mb is not None]
        lines = [f"Samples in the last minute: {len(samples)}"]
        if cpus:
            lines.append(f"CPU: now {cpus[-1]:.0f}% - peak {max(cpus):.0f}%")
        if rsss:
            lines.append(f"Memory (RSS): {rsss[-1]:.0f} MB - peak {max(rsss):.0f} MB")
        if not cpus and not rsss:
            lines.append("CPU / memory detail needs the optional performance probe (psutil).")
        if jobs:
            lines.append("Recent maintenance:")
            for r in jobs:
                name = getattr(r, "name", "job")
                ok = getattr(r, "ok", True)
                val = getattr(r, "value", None)
                err = getattr(r, "error", None)
                tail = (str(val) if ok else f"failed - {err}") or ""
                lines.append(f"  - {name}: {tail}".rstrip(": ").rstrip())
        else:
            lines.append("No background maintenance has run recently.")
        return lines

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

    # ---------- Kokoro voice picker (English-only by default + folder scan) ----------
    def _rebuild_kokoro_voices(self) -> None:
        """Fill the Kokoro picker: English by default, all languages when toggled, plus
        any hand-added voices found by the folder scan. Preserves the current selection."""
        combo = self.tts_voice_kokoro_combo
        prev = combo.currentData() or self.settings.tts_voice_kokoro or "af_heart"
        combo.blockSignals(True)
        combo.clear()
        self._kokoro_voice_index = {}     # voice id -> combo row, for restoring the pick
        show_all = self.kokoro_all_langs_cb.isChecked()

        def _add(vid: str, desc: str = "") -> None:
            combo.addItem(f"{vid}  -  {desc}" if desc else vid, vid)
            self._kokoro_voice_index[vid] = combo.count() - 1

        info = self._KOKORO_VOICE_INFO
        if show_all:
            for group, vids in self._kokoro_voices_by_language().items():
                combo.addItem(f"-- {group} --", None)
                hdr = combo.model().item(combo.count() - 1)
                hdr.setEnabled(False)
                for vid in vids:
                    _add(vid, info.get(vid, ""))
        else:
            combo.addItem("-- English --", None)
            combo.model().item(combo.count() - 1).setEnabled(False)
            for vid in self._kokoro_english_voices():
                _add(vid, info.get(vid, ""))

        # Folder scan: surface manually-added Kokoro voices (<voices_dir>/kokoro/<id>.bin).
        extras = self._scan_kokoro_voices(self.voices_dir)
        if extras:
            combo.addItem("-- Added voices (folder) --", None)
            combo.model().item(combo.count() - 1).setEnabled(False)
            for vid in extras:
                _add(vid, "found in voices folder")

        # restore the previous pick if it is still listed; else fall back to the default
        idx = self._kokoro_voice_index.get(prev, self._kokoro_voice_index.get("af_heart"))
        if idx is None and combo.count():
            idx = next((i for i in range(combo.count()) if combo.itemData(i)), 0)
        if idx is not None:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    # ---------- voice cloning helpers ----------
    def _fill_clone_combo(self, combo: QComboBox, lang: str, selected: str) -> None:
        """Populate a clone picker for a language: a 'default voice' row + each clone."""
        combo.clear()
        combo.addItem("Chatterbox default voice", "")
        for c in self.clones.for_lang(lang):
            combo.addItem(c.label(), c.voice_id)
        idx = next((i for i in range(combo.count())
                    if combo.itemData(i) == selected), 0)
        combo.setCurrentIndex(idx)

    def _refresh_clone_list(self) -> None:
        """Mirror the registry into the list widget and the per-language clone pickers."""
        self.clone_list.clear()
        for c in self.clones.all():
            warn = "" if c.exists() else "  (clip missing)"
            item = QListWidgetItem(f"{c.label()}{warn}")
            item.setData(Qt.UserRole, c.voice_id)
            self.clone_list.addItem(item)
        # Keep the engine pickers in step (preserving the current selection if still valid).
        self._fill_clone_combo(self.tts_clone_en_combo, "en",
                               self.tts_clone_en_combo.currentData() or self.settings.tts_clone_en)
        self._fill_clone_combo(self.tts_clone_de_combo, "de",
                               self.tts_clone_de_combo.currentData() or self.settings.tts_clone_de)

    def _pick_clone_clip(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Choose reference clip", self.clone_clip_edit.text(),
            "Audio (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*)")
        if f:
            self.clone_clip_edit.setText(f)

    def _add_clone(self):
        name = self.clone_name_edit.text().strip()
        clip = self.clone_clip_edit.text().strip()
        lang = self.clone_lang_combo.currentData()
        if not name or not clip:
            QMessageBox.warning(self, "Clone a voice",
                                "Enter a name and choose a reference clip first.")
            return
        from pathlib import Path
        if not Path(clip).exists():
            QMessageBox.warning(self, "Clone a voice", "That reference clip was not found.")
            return
        try:
            self.clones.add(name, lang, Path(clip))
        except OSError as exc:
            QMessageBox.warning(self, "Clone a voice", f"Could not save the clip: {exc}")
            return
        self.clone_name_edit.clear()
        self.clone_clip_edit.clear()
        self._refresh_clone_list()

    def _remove_clone(self):
        item = self.clone_list.currentItem()
        if item is None:
            return
        voice_id = item.data(Qt.UserRole)
        self.clones.remove(voice_id)
        self._refresh_clone_list()

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
        # Embedding model: a preset KEY, or (on the Custom row) the trimmed custom id -
        # falling back to the existing value if the custom box is blank so a save with an
        # empty custom field does not wipe the setting.
        sel = self.embed_model_combo.currentData()
        if sel == "__custom__":
            self.settings.embedding_model = (
                self.embed_custom_edit.text().strip() or self.settings.embedding_model)
        else:
            self.settings.embedding_model = sel
        self.settings.tts_enabled = self.tts_cb.isChecked()
        self.settings.tts_engine_en = self._tts_engines_en[self.tts_engine_en_combo.currentIndex()][0]
        self.settings.tts_engine_de = self._tts_engines_de[self.tts_engine_de_combo.currentIndex()][0]
        # Keep the legacy global default in step with the English choice.
        self.settings.tts_engine = self.settings.tts_engine_en
        self.settings.tts_voice_kokoro = self.tts_voice_kokoro_combo.currentData() or self.settings.tts_voice_kokoro
        self.settings.tts_voice_de = self.tts_voice_de_edit.text().strip() or self.settings.tts_voice_de
        self.settings.tts_voice_en = self.tts_voice_en_edit.text().strip() or self.settings.tts_voice_en
        # Cloned-voice selections (used when that language's engine is Chatterbox).
        self.settings.tts_clone_en = self.tts_clone_en_combo.currentData() or ""
        self.settings.tts_clone_de = self.tts_clone_de_combo.currentData() or ""
        self.settings.tts_rate = self.tts_rate_slider.value() / 100
        self.settings.tts_volume = self.tts_vol_slider.value() / 100
        self.settings.tts_cache_enabled = self.tts_cache_cb.isChecked()
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
