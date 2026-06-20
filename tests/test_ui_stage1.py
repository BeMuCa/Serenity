"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Headless smoke tests for the Stage-1 feature UIs wired into the PySide6 app.
Role:    Instantiate + lightly interact with the new widgets under QT_QPA_PLATFORM=offscreen
         so a regression in the UI layer (signals, attribute names, build_* calls) is caught
         without a display. The pure logic these widgets USE (activity, weekly_board,
         pomodoro, window_mode, depgraph) is covered by its own unit tests; here we only
         assert the widgets build and react. Skipped cleanly if PySide6 cannot start.

Test classes:
- TestActivityChip - shows/hides on a running span, formats elapsed
- TestFocusWidget - Pomodoro strip start/pause/resume + phase signal
- TestWeeklyBoardView - builds + renders from the activity store
- TestGraphView - renders deps, clean empty-state with none
- TestMiniWindow - compact dock builds + picks the top todo
- TestModals - Quick Note tag field + protocol template
- TestMascotStage - set_state animates the avatar (QMovie set)
- TestNotesViewMeaning - Meaning mode ranks via the semantic index, degrades to keyword
- TestNotesViewRelated - expanding a card lazily builds Related chips (semantic + keyword/tag
  degrade); chips are absent before expand; a chip opens ReadNoteDialog (chainable)
- TestShell - the whole shell builds, switches window modes, auto-opens the board once
============================================================
"""

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.activity_store import ActivityStore  # noqa: E402
from serenity.core.models import Todo  # noqa: E402
from serenity.core.settings import Settings  # noqa: E402
from serenity.core.todo_store import TodoStore  # noqa: E402
from serenity.core.voice_lines import VoiceLines  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.vault_path = str(tmp_path / "vault")
    return s


# --------------------------------------------------------------------------- #
# Activity chip (feature 1)
# --------------------------------------------------------------------------- #
class TestActivityChip:
    def test_shows_running_span_and_hides_on_clear(self, qapp):
        from serenity.ui.activity_chip import ActivityChip
        from serenity.core.activity import ActivityEntry

        chip = ActivityChip()
        assert chip.isHidden()
        chip.show_running(ActivityEntry("Working", datetime.now()))
        assert not chip.isHidden()
        assert chip.name.text() == "Working"
        chip.clear()
        assert chip.isHidden()

    def test_idle_and_finished_spans_do_not_show(self, qapp):
        from serenity.ui.activity_chip import ActivityChip, _fmt_elapsed
        from serenity.core.activity import ActivityEntry

        chip = ActivityChip()
        chip.show_running(ActivityEntry("Idle", datetime.now()))
        assert chip.isHidden()
        now = datetime.now()
        chip.show_running(ActivityEntry("Working", now - timedelta(hours=1), end=now))
        assert chip.isHidden()
        assert _fmt_elapsed(65) == "1:05"
        assert _fmt_elapsed(3725) == "1:02:05"


# --------------------------------------------------------------------------- #
# Focus / Pomodoro (feature 3)
# --------------------------------------------------------------------------- #
class TestFocusWidget:
    def test_start_pause_resume(self, qapp, settings):
        from serenity.ui.focus_widget import FocusWidget
        from serenity.core.pomodoro import Phase

        w = FocusWidget(VoiceLines(), settings)
        w.start()
        assert not w.isHidden()
        assert w.pomo.phase == Phase.FOCUS
        w._toggle()                       # pause
        assert w.pomo.paused
        w._toggle()                       # resume
        assert not w.pomo.paused
        w.set_active(False)
        assert w.isHidden()
        assert w.pomo.phase == Phase.IDLE

    def test_phase_change_emits_signal(self, qapp, settings):
        from serenity.ui.focus_widget import FocusWidget

        w = FocusWidget(VoiceLines(), settings)
        seen = []
        w.phase_changed.connect(lambda phase, text: seen.append((phase, text)))
        # force the focus phase to have elapsed, then tick
        w.start()
        w.pomo._ends_at = datetime.now() - timedelta(seconds=1)
        w._tick()
        assert seen and seen[0][0] in ("break", "long_break")
        assert seen[0][1]                 # a non-empty comment


# --------------------------------------------------------------------------- #
# Weekly board (feature 2)
# --------------------------------------------------------------------------- #
class TestWeeklyBoardView:
    def test_builds_and_renders(self, qapp, tmp_path):
        from serenity.ui.weekly_board_view import WeeklyBoardView

        astore = ActivityStore(tmp_path)
        now = datetime.now()
        astore.start("Working", when=now - timedelta(hours=2))
        astore.stop(when=now - timedelta(hours=1))
        tstore = TodoStore(tmp_path)

        view = WeeklyBoardView(astore, tstore)
        view.refresh()
        board = view.build(now)
        assert board.total_seconds == 3600
        assert board.top_category == "Working"

    def test_empty_board_has_a_hint(self, qapp, tmp_path):
        from serenity.ui.weekly_board_view import WeeklyBoardView

        view = WeeklyBoardView(ActivityStore(tmp_path), TodoStore(tmp_path))
        board = view.build()
        assert board.hints                     # the "no time tracked" hint


# --------------------------------------------------------------------------- #
# Dependency graph (feature 7)
# --------------------------------------------------------------------------- #
class TestGraphView:
    def test_empty_state_when_no_deps(self, qapp, tmp_path):
        from serenity.ui.graph_view import GraphView

        store = TodoStore(tmp_path)
        store.add(Todo(title="standalone"))
        view = GraphView(store)
        view.refresh()
        assert not view.empty.isHidden()
        assert view.view.isHidden()

    def test_renders_nodes_and_edges_with_deps(self, qapp, tmp_path):
        from serenity.ui.graph_view import GraphView

        store = TodoStore(tmp_path)
        a = store.add(Todo(title="design"))
        store.add(Todo(title="build", depends_on=[a.id]))
        view = GraphView(store)
        view.refresh()
        assert view.empty.isHidden()
        assert not view.view.isHidden()
        # scene has at least the two node rects + an edge line
        assert len(view.scene.items()) >= 3


# --------------------------------------------------------------------------- #
# Mini window (feature 4)
# --------------------------------------------------------------------------- #
class TestMiniWindow:
    def test_builds_and_picks_top_todo(self, qapp, tmp_path, settings):
        from serenity.ui.mini_window import MiniWindow

        store = TodoStore(tmp_path)
        store.add(Todo(title="urgent thing", due=datetime.now() + timedelta(minutes=30)))
        mini = MiniWindow(store, settings)
        mini.refresh_todo()
        assert mini.todo_label.text() == "urgent thing"

    def test_empty_todos_clean_state(self, qapp, tmp_path, settings):
        from serenity.ui.mini_window import MiniWindow

        mini = MiniWindow(TodoStore(tmp_path), settings)
        mini.refresh_todo()
        assert "clear" in mini.todo_label.text().lower()


# --------------------------------------------------------------------------- #
# Quick Note tags + protocol (feature 5)
# --------------------------------------------------------------------------- #
class TestModals:
    def test_tags_written_to_note(self, qapp, tmp_path, settings):
        from serenity.core.note_store import NoteStore
        from serenity.ui.modals import QuickNoteDialog
        from pathlib import Path

        ns = NoteStore(tmp_path)
        d = QuickNoteDialog(ns, settings)
        d.title.setText("sync")
        d.tags.setText("#Protokoll, meeting")
        d.body.setPlainText("body")
        d._save()
        note = ns.all_active()[0]
        assert note.tags == ["Protokoll", "meeting"]
        assert "Protokoll" in settings.tags

    def test_protocol_template_fills_body_and_tags(self, qapp, tmp_path, settings):
        from serenity.core.note_store import NoteStore
        from serenity.ui.modals import QuickNoteDialog, protocol_template

        d = QuickNoteDialog(NoteStore(tmp_path), settings)
        d._insert_protocol()
        assert d.body.toPlainText().startswith("# Protokoll")
        assert "Protokoll" in d.tags.text() and "meeting" in d.tags.text()
        # no em-dash / double hyphen in the template (house style)
        tpl = protocol_template()
        assert "--" not in tpl and "—" not in tpl


# --------------------------------------------------------------------------- #
# Settings Kokoro picker (feature 6)
# --------------------------------------------------------------------------- #
class TestKokoroPicker:
    def test_english_only_by_default(self, qapp, settings):
        from serenity.ui.settings_window import SettingsWindow

        w = SettingsWindow(settings)
        ids = [w.tts_voice_kokoro_combo.itemData(i)
               for i in range(w.tts_voice_kokoro_combo.count())]
        voices = [v for v in ids if v]
        assert len(voices) == 28                       # American + British only
        assert not any(v.startswith("jf") for v in voices)

    def test_show_all_languages_expands(self, qapp, settings):
        from serenity.ui.settings_window import SettingsWindow

        w = SettingsWindow(settings)
        w.kokoro_all_langs_cb.setChecked(True)
        ids = [w.tts_voice_kokoro_combo.itemData(i)
               for i in range(w.tts_voice_kokoro_combo.count())]
        voices = [v for v in ids if v]
        assert len(voices) == 54
        assert any(v.startswith("jf") for v in voices)

    def test_folder_scan_surfaces_manual_voice(self, qapp, settings, tmp_path):
        from serenity.core.tts import KOKORO_SUBDIR
        from serenity.ui.settings_window import SettingsWindow

        # drop a manual voice file into <voices_dir>/kokoro/ and re-run the scan
        settings.vault_path = str(tmp_path / "vault")
        w = SettingsWindow(settings)
        scan_dir = tmp_path / "scan"
        (scan_dir / KOKORO_SUBDIR).mkdir(parents=True)
        (scan_dir / KOKORO_SUBDIR / "xx_custom.bin").write_bytes(b"x")
        w.voices_dir = str(scan_dir)
        w._rebuild_kokoro_voices()
        ids = [w.tts_voice_kokoro_combo.itemData(i)
               for i in range(w.tts_voice_kokoro_combo.count())]
        assert "xx_custom" in ids


# --------------------------------------------------------------------------- #
# Mascot stage (avatar animation)
# --------------------------------------------------------------------------- #
class TestMascotStage:
    def test_set_state_animates_the_avatar(self, qapp, settings):
        # Regression: a duplicate _play (audio) once shadowed the pose player, so the
        # avatar QMovie was never set and the mascot never animated. set_state must load
        # a pose movie onto the avatar.
        from PySide6.QtGui import QMovie
        from serenity.ui.mascot_stage import MascotStage

        settings.tts_enabled = False          # keep playback out of this test
        stage = MascotStage(settings)
        stage.set_state("working")
        assert isinstance(stage._movie, QMovie)
        assert stage.avatar.movie() is stage._movie


# --------------------------------------------------------------------------- #
# Notes view - Meaning (semantic) search wiring (Stage-2 job 14)
# --------------------------------------------------------------------------- #
def _card_notes(view):
    """The Note objects currently rendered as cards, in list order."""
    out = []
    for i in range(view.list_box.count()):
        w = view.list_box.itemAt(i).widget()
        if w is not None:
            out.append(w.note)
    return out


class TestNotesViewMeaning:
    def test_meaning_mode_ranks_by_semantic_index(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.core.phase2_stubs import SemanticIndex
        from serenity.core.semantic import StubEmbedder
        from serenity.ui.notes_view import NotesView

        store = NoteStore(tmp_path)
        store.create("Vacation plan", body="beach flight hotel sunset ocean")
        store.create("Tax report", body="invoice deadline accountant numbers")
        # A usable (stub) embedder -> available index -> Meaning mode is live.
        index = SemanticIndex(embedder=StubEmbedder(dim=64))
        view = NotesView(store, index)

        view._set_mode("meaning")
        view.search.setText("beach ocean flight")
        view.refresh()                                   # debounce timer bypassed

        assert view.notice.isHidden()                    # notice hidden when the index is live
        cards = _card_notes(view)
        assert cards, "meaning search returned no cards"
        assert cards[0].title == "Vacation plan"         # most token-overlap ranks first

    def test_meaning_mode_degrades_to_keyword_without_index(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.ui.notes_view import NotesView

        store = NoteStore(tmp_path)
        store.create("Vacation plan", body="beach flight hotel sunset ocean")
        store.create("Tax report", body="invoice deadline accountant numbers")
        view = NotesView(store, None)                    # no embedding index wired

        view._set_mode("meaning")
        view.search.setText("beach")
        view.refresh()

        assert not view.notice.isHidden()                # notice shown -> falling back to Text
        titles = [n.title for n in _card_notes(view)]
        assert "Vacation plan" in titles                 # keyword fallback still finds it


# --------------------------------------------------------------------------- #
# Notes view - Related notes (note-linking, Stage-2 job 4)
# --------------------------------------------------------------------------- #
def _related_chips(card_or_dialog):
    """The 'Related' chips (ghost QPushButtons) under a card/dialog's related_box."""
    from PySide6.QtWidgets import QPushButton

    box = card_or_dialog.related_box
    out = []
    for i in range(box.count()):
        w = box.itemAt(i).widget()
        if isinstance(w, QPushButton) and w.objectName() == "ghost":
            out.append(w)
    return out


def _related_store(tmp_path):
    """A NoteStore with three notes sharing tags/tokens so 'related' is non-empty."""
    from serenity.core.note_store import NoteStore

    store = NoteStore(tmp_path)
    store.create("Vacation plan", body="beach flight hotel ocean", tags=["travel"])
    store.create("Trip budget", body="flight hotel money ocean", tags=["travel"])
    store.create("Beach day", body="beach ocean sunset waves", tags=["travel"])
    return store


def _stub_index():
    from serenity.core.phase2_stubs import SemanticIndex
    from serenity.core.semantic import StubEmbedder

    return SemanticIndex(embedder=StubEmbedder(dim=64))


class TestNotesViewRelated:
    def test_related_not_built_until_expanded(self, qapp, tmp_path):
        from serenity.ui.notes_view import NotesView

        store = _related_store(tmp_path)
        view = NotesView(store, _stub_index())
        cards = [view.list_box.itemAt(i).widget() for i in range(view.list_box.count())]
        assert cards
        # Nothing computed on plain render: every card un-built, the section hidden.
        for c in cards:
            assert c._related_built is False
            assert c.related_wrap.isHidden()
            assert _related_chips(c) == []

        card = cards[0]
        card._toggle()                                   # expand the first card
        assert card._related_built is True
        assert not card.related_wrap.isHidden()          # has >=1 related neighbour
        chips = _related_chips(card)
        assert 1 <= len(chips) <= 4

        # Re-collapsing and re-expanding must not rebuild (idempotent _ensure_related).
        n_chips = len(chips)
        card._toggle()                                   # collapse
        card._toggle()                                   # expand again
        assert len(_related_chips(card)) == n_chips

    def test_related_chip_opens_read_dialog(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.notes_view as nv
        from serenity.ui.notes_view import NotesView

        store = _related_store(tmp_path)
        view = NotesView(store, _stub_index())
        card = view.list_box.itemAt(0).widget()

        # Record what ReadNoteDialog is constructed with, and never block on exec().
        opened = {}

        class _RecordingDialog:
            def __init__(self, note, semantic=None, notes_provider=None, parent=None):
                opened["note"] = note

            def exec(self):
                return None

        monkeypatch.setattr(nv, "ReadNoteDialog", _RecordingDialog)

        card._toggle()                                   # expand -> build chips
        chips = _related_chips(card)
        assert chips
        chips[0].click()                                 # open the first related note
        assert "note" in opened
        # The opened note is one of the OTHER notes, never the card's own note.
        assert opened["note"].id != card.note.id
        assert opened["note"].id in {n.id for n in store.all_active()}

    def test_related_chips_without_index_use_fallback(self, qapp, tmp_path):
        from serenity.ui.notes_view import NotesView

        store = _related_store(tmp_path)
        view = NotesView(store, None)                    # no embedding index wired
        card = view.list_box.itemAt(0).widget()
        card._toggle()
        assert not card.related_wrap.isHidden()          # keyword/tag fallback still surfaces
        assert len(_related_chips(card)) >= 1            # related notes - no Phase-2 dead-end

    def test_no_related_section_when_nothing_in_common(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.ui.notes_view import NotesView

        store = NoteStore(tmp_path)
        store.create("Alpha", body="zzz qqq", tags=["red"])
        store.create("Beta", body="www vvv", tags=["blue"])   # disjoint tags + tokens
        view = NotesView(store, None)
        card = view.list_box.itemAt(0).widget()
        card._toggle()
        assert card._related_built is True
        assert card.related_wrap.isHidden()              # section omitted, no empty label
        assert _related_chips(card) == []

    def test_read_dialog_builds_and_chains(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.notes_view as nv
        from serenity.ui.notes_view import ReadNoteDialog

        store = _related_store(tmp_path)
        note = store.all_active()[0]
        dlg = ReadNoteDialog(note, semantic=_stub_index(),
                             notes_provider=store.all_active)
        assert dlg.title_label.text() == note.title
        assert dlg.body.toPlainText() == note.body
        # The dialog builds its own Related chips for a note with neighbours -> chainable.
        chips = _related_chips(dlg)
        assert not dlg.related_wrap.isHidden()
        assert len(chips) >= 1

        # Clicking a chip in the dialog opens ANOTHER ReadNoteDialog (chaining note->note).
        chained = {}
        real_init = ReadNoteDialog.__init__

        def _spy_init(self, note, semantic=None, notes_provider=None, parent=None):
            chained["note"] = note
            real_init(self, note, semantic=semantic,
                      notes_provider=notes_provider, parent=parent)

        monkeypatch.setattr(ReadNoteDialog, "__init__", _spy_init)
        monkeypatch.setattr(ReadNoteDialog, "exec", lambda self: None)
        chips[0].click()
        assert chained.get("note") is not None
        assert chained["note"].id != note.id

    def test_plain_refresh_computes_no_related(self, qapp, tmp_path):
        # Regression guard: a plain refresh() must build N cards with NO related work, so the
        # model is never touched on list render.
        from serenity.ui.notes_view import NotesView

        store = _related_store(tmp_path)
        view = NotesView(store, _stub_index())
        view.refresh()
        cards = [view.list_box.itemAt(i).widget() for i in range(view.list_box.count())]
        assert len(cards) == len(store.all_active())
        assert all(c._related_built is False for c in cards)


# --------------------------------------------------------------------------- #
# Whole shell (cross-feature wiring)
# --------------------------------------------------------------------------- #
class TestShell:
    def test_shell_builds_and_switches_modes(self, qapp, tmp_path, monkeypatch):
        # isolate config + vault under tmp
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell, MODE_MINI, MODE_FULL, MODE_HIDDEN

        shell = Shell()
        try:
            # activity selection starts a span + shows the chip
            shell._on_activity("Working")
            assert shell.activity_store.running().category == "Working"
            assert not shell.activity_chip.isHidden()
            # Focus reveals the pomodoro strip
            shell._on_activity("Focus")
            assert not shell.focus_widget.isHidden()
            # Idle stops tracking
            shell._on_activity("Idle")
            assert shell.activity_store.running() is None
            # window modes
            shell.set_window_mode(MODE_MINI)
            assert shell._mini is not None
            assert not shell._mini.isHidden()          # mini dock is shown in MINI
            shell.set_window_mode(MODE_HIDDEN)
            assert shell._mini.isHidden()              # mini hidden when going to tray
            shell.set_window_mode(MODE_FULL)
            assert shell._mini.isHidden()              # mini hidden behind the full dock
            assert shell._mode == MODE_FULL
            assert shell.settings.window_mode == MODE_FULL
            # unknown mode clamps to FULL (shell.py:499-500)
            shell.set_window_mode("bogus")
            assert shell._mode == MODE_FULL
            # board + graph tabs render
            shell.switch_tab("board")
            shell.switch_tab("graph")
        finally:
            shell.tray.hide()

    def test_auto_open_board_fires_once(self, qapp, tmp_path, monkeypatch):
        # isolate config + vault under tmp
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        import serenity.core.activity as activity_mod
        from serenity.ui.shell import Shell, MODE_FULL, MODE_MINI

        shell = Shell()                       # __init__ calls _maybe_auto_open_board once
        try:
            shell.set_window_mode(MODE_MINI)
            # force the timing rule True deterministically (avoids the real clock)
            monkeypatch.setattr(activity_mod, "should_auto_open_board",
                                lambda now, last: True)
            shell._maybe_auto_open_board()
            assert shell.activity_store.last_board_open() is not None
            assert shell._mode == MODE_FULL                 # mini/hidden forced to FULL
            assert shell.tab_buttons["board"].isChecked()   # board tab switched to
            marker = shell.activity_store.last_board_open()

            # once-a-day guard: real rule says no (already opened today) -> marker unchanged
            monkeypatch.setattr(activity_mod, "should_auto_open_board",
                                lambda now, last: False)
            shell._maybe_auto_open_board()
            assert shell.activity_store.last_board_open() == marker
        finally:
            shell.tray.hide()
