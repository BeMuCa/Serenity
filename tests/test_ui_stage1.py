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
- TestNotesViewDuplicates - the "Find duplicates" button + DuplicatesDialog (Job 3)
- TestTagConsolidationDialog - the "Tidy tags" button + TagConsolidationDialog (Job 5): lazy
  detection on open, group rows, Apply (confirm + rename + arsenal), edited canonical, Cancel,
  empty canonical guard, Dismiss, empty-state
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

    def test_expand_drives_semantic_index_path(self, qapp, tmp_path):
        # TC-1: prove the card's Related chips come from the SEMANTIC index path (not just the
        # keyword/tag fallback). A spy on SemanticIndex.related must fire on expand with the
        # card's own note id, and chips must render. The StubEmbedder ranking happens to match
        # the fallback for this fixture, so a spy - not output diffing - is what distinguishes
        # the two paths end-to-end through the UI.
        from serenity.ui.notes_view import NotesView

        store = _related_store(tmp_path)
        idx = _stub_index()
        view = NotesView(store, idx)

        calls = []
        real_related = idx.related

        def _spy(note, top_k=5):
            calls.append(note.id)
            return real_related(note, top_k=top_k)

        idx.related = _spy

        card = view.list_box.itemAt(0).widget()
        card._toggle()                                   # expand -> index-first -> related()
        assert card._related_built is True
        assert calls and card.note.id in calls          # the semantic branch ran (not fallback)
        assert not card.related_wrap.isHidden()
        assert len(_related_chips(card)) >= 1

    def test_related_chips_reflect_live_vault_in_text_mode(self, qapp, tmp_path):
        # JOB4-CORR-1 UI regression: index the store via a Meaning-mode refresh, THEN add a new
        # closely-related note, switch back to Text mode and expand a card. The new note must
        # appear among the related chips (chips reflect the LIVE vault, not the stale store left
        # from the Meaning visit). This FAILS before the index-first fix and PASSES after.
        from serenity.ui.notes_view import NotesView

        store = _related_store(tmp_path)
        view = NotesView(store, _stub_index())
        view._set_mode("meaning")                        # refresh() indexes the active notes
        view._set_mode("text")                           # back to default; Text does NOT index

        new_note = store.create(
            "Sailing trip", body="ocean waves beach flight hotel", tags=["travel"]
        )
        view.refresh()                                   # plain Text refresh - no re-index here

        # Expand an EXISTING card (not the new note itself, which sorts first and is self-
        # excluded from its own chips). Index-first on expand must pick up the newly created
        # note so it surfaces among that card's related chips.
        cards = [view.list_box.itemAt(i).widget() for i in range(view.list_box.count())]
        card = next(c for c in cards if c.note.title == "Vacation plan")
        card._toggle()
        tooltips = {c.toolTip() for c in _related_chips(card)}
        assert new_note.title in tooltips


# --------------------------------------------------------------------------- #
# Notes view - Find duplicates / merge (near-duplicate + fragment, Stage-2 job 3)
# --------------------------------------------------------------------------- #
def _dup_rows(dlg):
    """The pair-row cards (QFrame#card) in a DuplicatesDialog's rows_box."""
    from PySide6.QtWidgets import QFrame

    out = []
    for i in range(dlg.rows_box.count()):
        w = dlg.rows_box.itemAt(i).widget()
        if isinstance(w, QFrame) and w.objectName() == "card":
            out.append(w)
    return out


def _row_buttons(row):
    """{text: QPushButton} for the action buttons (Merge / Dismiss) in a pair row."""
    from PySide6.QtWidgets import QPushButton

    return {b.text(): b for b in row.findChildren(QPushButton)}


def _badge_texts(row):
    """All QLabel texts in a row - used to assert the kind badge ('Near-duplicate'/'Fragment')."""
    from PySide6.QtWidgets import QLabel

    return {lab.text() for lab in row.findChildren(QLabel)}


def _dup_store(tmp_path):
    """A NoteStore with two near-identical notes (high Jaccard) + one disjoint note."""
    from serenity.core.note_store import NoteStore

    store = NoteStore(tmp_path)
    body = "discuss roadmap timeline budget hire plan ship review sync standup retro demo"
    store.create("Meeting notes", body=body)
    store.create("Meeting notes copy", body=body)
    store.create("Grocery list", body="milk eggs bread butter cheese apples bananas")
    return store


def _fragment_store(tmp_path):
    """A NoteStore with a long note + a short note whose tokens are contained in the long one."""
    from serenity.core.note_store import NoteStore

    store = NoteStore(tmp_path)
    # The short note's title tokens (alpha/project) also appear in the long note, so the whole-
    # document containment (title+body via _haystack) clears FRAGMENT_CONTAINMENT, while the
    # short note stays genuinely shorter (under FRAGMENT_MAX_RATIO of the long note's tokens).
    store.create(
        "Project alpha plan",
        body="alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi project plan",
    )
    store.create("Alpha project", body="alpha beta gamma delta epsilon zeta")
    return store


class TestNotesViewDuplicates:
    def test_find_duplicates_button_present(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.ui.notes_view import NotesView

        view = NotesView(NoteStore(tmp_path), None)
        assert view.dedup_btn.text() == "Find duplicates"
        assert view.dedup_btn.objectName() == "ghost"

    def test_detection_is_lazy_not_on_render(self, qapp, tmp_path, monkeypatch):
        # find_duplicates (imported into duplicates_dialog) must NOT run on list render - only
        # when the dialog opens. A spy on it stays at zero through construction + refresh().
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.notes_view import NotesView

        calls = []
        real = dd.find_duplicates
        monkeypatch.setattr(
            dd, "find_duplicates",
            lambda notes, index=None, **kw: (calls.append(1), real(notes, index=index, **kw))[1],
        )

        store = _dup_store(tmp_path)
        view = NotesView(store, None)   # __init__ calls refresh()
        view.refresh()
        assert calls == []              # detection has not run before the dialog opens

    def test_open_duplicates_runs_detection_and_lists_rows(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.notes_view import NotesView

        calls = []
        real = dd.find_duplicates
        monkeypatch.setattr(
            dd, "find_duplicates",
            lambda notes, index=None, **kw: (calls.append(1), real(notes, index=index, **kw))[1],
        )
        # Capture the constructed dialog and never block on exec().
        captured = {}
        real_init = dd.DuplicatesDialog.__init__

        def _spy_init(self, store, semantic=None, notes_provider=None, parent=None):
            real_init(self, store, semantic=semantic, notes_provider=notes_provider, parent=parent)
            captured["dlg"] = self

        monkeypatch.setattr(dd.DuplicatesDialog, "__init__", _spy_init)
        monkeypatch.setattr(dd.DuplicatesDialog, "exec", lambda self: None)

        view = NotesView(_dup_store(tmp_path), None)
        view._open_duplicates()
        assert calls == [1]                              # detection ran exactly once, on open
        assert len(_dup_rows(captured["dlg"])) >= 1      # the near-duplicate pair is listed

    def test_dialog_lists_duplicate_row(self, qapp, tmp_path):
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert len(rows) >= 1
        assert any("Near-duplicate" in _badge_texts(r) for r in rows)
        assert dlg.empty_label.isHidden()

    def test_dialog_lists_fragment_row(self, qapp, tmp_path):
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _fragment_store(tmp_path)
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert len(rows) >= 1
        assert any("Fragment" in _badge_texts(r) for r in rows)

    def test_merge_button_merges_and_soft_deletes(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        before_active = {n.id for n in store.all_active()}
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert rows

        merged_fired = []
        dlg.merged.connect(lambda: merged_fired.append(1))
        monkeypatch.setattr(dd.QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)

        _row_buttons(rows[0])["Merge"].click()

        # Row removed; merged signal fired.
        assert len(_dup_rows(dlg)) == len(rows) - 1
        assert merged_fired == [1]
        # Exactly one of the pair went to Trash (recoverable).
        trashed = store.trash()
        assert len(trashed) == 1
        dropped_id = trashed[0].id
        assert dropped_id in before_active
        # The survivor stays active and carries BOTH bodies (merge_notes appended the drop).
        survivor = next(n for n in store.all_active()
                        if n.id in before_active and n.id != dropped_id)
        assert "discuss roadmap" in survivor.body
        # The dropped note is restorable (Trash IS the undo, never purged).
        assert store.restore(dropped_id) is not None

    def test_merge_keep_other_flips_survivor(self, qapp, tmp_path, monkeypatch):
        # The "Keep ... instead" checkbox is the only control deciding WHICH note survives a
        # merge and which goes to Trash. Pin it: with the box CHECKED, the note default_keep
        # would have KEPT is the one trashed, and the other survives carrying both bodies.
        from PySide6.QtWidgets import QCheckBox, QMessageBox
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.duplicates_dialog import DuplicatesDialog
        from serenity.core.dedup import default_keep

        store = _dup_store(tmp_path)
        meetings = [n for n in store.all_active() if "Meeting" in n.title]
        assert len(meetings) == 2
        default_keep_id = default_keep(meetings[0], meetings[1])

        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        row = _dup_rows(dlg)[0]
        boxes = row.findChildren(QCheckBox)
        assert boxes
        boxes[0].setChecked(True)                       # override the default survivor

        monkeypatch.setattr(dd.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        _row_buttons(row)["Merge"].click()

        trashed = store.trash()
        assert len(trashed) == 1
        # The box FLIPPED the survivor: the default-kept note is the one now in Trash.
        assert trashed[0].id == default_keep_id
        # The OTHER note survives, is still active, and carries both bodies.
        survivor = next(n for n in store.all_active() if n.id != default_keep_id
                        and "Meeting" in n.title)
        assert survivor.id != default_keep_id
        assert "discuss roadmap" in survivor.body
        # The trashed note is recoverable (Trash IS the undo, never purged).
        assert store.restore(default_keep_id) is not None

    def test_fragment_merge_keeps_longer_drops_fragment(self, qapp, tmp_path, monkeypatch):
        # The fragment merge is a distinct code path: it hardcodes the kept note to the LONGER
        # note (a_id), not default_keep. Pin it - merging a fragment row must trash the SHORTER
        # fragment and keep the longer note with the fragment's body appended.
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _fragment_store(tmp_path)
        actives = store.all_active()
        longer = max(actives, key=lambda n: len(n.body or ""))
        shorter = min(actives, key=lambda n: len(n.body or ""))
        assert longer.id != shorter.id

        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        frag_row = next(r for r in rows if "Fragment" in _badge_texts(r))

        monkeypatch.setattr(dd.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        _row_buttons(frag_row)["Merge"].click()

        trashed = store.trash()
        assert len(trashed) == 1
        assert trashed[0].id == shorter.id              # the fragment went to Trash
        # The longer note survives with the fragment's body appended under the separator.
        survivor = next(n for n in store.all_active() if n.id == longer.id)
        assert "zeta" in survivor.body                  # fragment token now in the kept note
        # Recoverable (never purged).
        assert store.restore(shorter.id) is not None

    def test_merge_cancel_does_nothing(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert rows
        monkeypatch.setattr(dd.QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Cancel)

        _row_buttons(rows[0])["Merge"].click()
        assert len(_dup_rows(dlg)) == len(rows)   # row still present
        assert store.trash() == []                # nothing trashed

    def test_dismiss_removes_row_no_delete(self, qapp, tmp_path):
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        n_active = len(store.all_active())
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert rows

        _row_buttons(rows[0])["Dismiss"].click()
        assert len(_dup_rows(dlg)) == len(rows) - 1   # row gone
        assert store.trash() == []                    # nothing deleted
        assert len(store.all_active()) == n_active     # both notes still active

    def test_empty_state(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = NoteStore(tmp_path)
        store.create("Alpha", body="zzz qqq disjoint words here completely")
        store.create("Beta", body="www vvv different tokens entirely none shared")
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        assert _dup_rows(dlg) == []
        assert not dlg.empty_label.isHidden()
        assert dlg.empty_label.text() == "No duplicates or fragments found."
        # The empty message sits in the freed central area, not pinned to the bottom: the
        # stretchy scroll area is hidden so the centered label fills the space (ux-1).
        assert dlg.scroll.isHidden()

    def test_empty_state_centered_after_dismiss_all(self, qapp, tmp_path):
        # Dismissing the last row must reach the same clean empty-state (scroll hidden, message
        # centered in the freed area), not leave a tall blank scroll with a bottom-pinned line.
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        dlg.resize(460, 480)
        rows = _dup_rows(dlg)
        assert rows
        for row in rows:
            _row_buttons(row)["Dismiss"].click()
        assert _dup_rows(dlg) == []
        assert not dlg.empty_label.isHidden()
        assert dlg.scroll.isHidden()
        # The label occupies the central region (well above the bottom edge), not pinned low.
        dlg.show()
        qapp.processEvents()
        assert dlg.empty_label.y() < dlg.height() / 2
        dlg.hide()

    def test_degrade_footnote_without_model(self, qapp, tmp_path):
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        # No model (this env): rows still appear AND the footnote names the text-overlap scan
        # (no Phase-2 dead-end).
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        assert _dup_rows(dlg)
        assert "no embedding model" in dlg.footnote.text()

        # With a live (stub) index, the footnote is the meaning + text variant.
        store2 = _dup_store(tmp_path / "two")
        idx = _stub_index()
        idx.index(store2.all_active())
        dlg2 = DuplicatesDialog(store2, idx, notes_provider=store2.all_active)
        assert "meaning" in dlg2.footnote.text()

    def test_merge_prunes_stale_sibling_rows(self, qapp, tmp_path, monkeypatch):
        # Three near-identical notes -> three rows (A-B, A-C, B-C). Merging one row drops a
        # note that two rows reference; the merged row AND the sibling pointing at the trashed
        # note must both disappear, leaving only rows whose notes are still active - no row left
        # pointing at a Trashed note, and no later "already merged" popup (ux-2).
        from PySide6.QtWidgets import QMessageBox
        from serenity.core.note_store import NoteStore
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = NoteStore(tmp_path)
        body = "discuss roadmap timeline budget hire plan ship review sync standup retro demo"
        for t in ("One", "Two", "Three"):
            store.create(t, body=body)

        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert len(rows) == 3

        monkeypatch.setattr(dd.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        _row_buttons(rows[0])["Merge"].click()

        dropped_id = store.trash()[0].id
        remaining = _dup_rows(dlg)
        # The merged row + the one sibling referencing the trashed note are both gone.
        assert len(remaining) == 1
        # No surviving row references the note now in Trash.
        for r in remaining:
            assert dropped_id not in getattr(r, "_pair_ids", ())
        # And the surviving row is genuinely live: merging it shows no "already merged" popup.
        info = []
        monkeypatch.setattr(dd.QMessageBox, "information", lambda *a, **k: info.append(1))
        _row_buttons(remaining[0])["Merge"].click()
        assert info == []
        assert len(store.trash()) == 2

    def test_already_merged_row_guard(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.duplicates_dialog import DuplicatesDialog

        store = _dup_store(tmp_path)
        dlg = DuplicatesDialog(store, None, notes_provider=store.all_active)
        rows = _dup_rows(dlg)
        assert rows
        target = rows[0]

        # Soft-delete BOTH notes of this pair behind the dialog's back so the row is stale.
        for n in store.all_active():
            store.soft_delete(n.id)

        info = []
        monkeypatch.setattr(dd.QMessageBox, "information",
                            lambda *a, **k: info.append(1))
        monkeypatch.setattr(dd.QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)

        _row_buttons(target)["Merge"].click()
        assert info == [1]                         # "already merged" shown, no crash
        assert target not in _dup_rows(dlg)        # stale row removed

    def test_button_in_meaning_mode_indexes_first(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.duplicates_dialog as dd
        from serenity.ui.notes_view import NotesView

        monkeypatch.setattr(dd.DuplicatesDialog, "exec", lambda self: None)

        # Live (stub) index: _open_duplicates must index() once before opening the dialog.
        idx = _stub_index()
        store = _dup_store(tmp_path)
        view = NotesView(store, idx)
        index_calls = []
        real_index = idx.index
        idx.index = lambda notes: (index_calls.append(1), real_index(notes))[1]
        view._open_duplicates()
        assert index_calls == [1]                  # index-first contract honoured

        # No index: index() is never called (degrade path passes index=None).
        store2 = _dup_store(tmp_path / "two")
        view2 = NotesView(store2, None)
        view2._open_duplicates()                   # must not raise


# --------------------------------------------------------------------------- #
# Notes view - Tidy tags (tag consolidation, Stage-2 job 5)
# --------------------------------------------------------------------------- #
def _tag_rows(dlg):
    """The group-row cards (QFrame#card) in a TagConsolidationDialog's rows_box."""
    from PySide6.QtWidgets import QFrame

    out = []
    for i in range(dlg.rows_box.count()):
        w = dlg.rows_box.itemAt(i).widget()
        if isinstance(w, QFrame) and w.objectName() == "card":
            out.append(w)
    return out


def _tag_row_buttons(row):
    """{text: QPushButton} for the action buttons (Apply / Dismiss) in a group row."""
    from PySide6.QtWidgets import QPushButton

    return {b.text(): b for b in row.findChildren(QPushButton)}


def _tag_store(tmp_path):
    """A NoteStore whose notes carry case-variant + spelling-variant tags to consolidate."""
    from serenity.core.note_store import NoteStore

    store = NoteStore(tmp_path)
    store.create("A", body="alpha", tags=["Work", "urgent"])
    store.create("B", body="beta", tags=["work"])
    store.create("C", body="gamma", tags=["works"])
    return store


def _tag_settings(tmp_path):
    from serenity.core.settings import Settings

    s = Settings()
    s._path = tmp_path / "settings.json"
    s.tags = ["Work", "work", "works", "Other"]
    return s


class TestTagConsolidationDialog:
    def test_tidy_tags_button_present(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.ui.notes_view import NotesView

        view = NotesView(NoteStore(tmp_path), None)
        assert view.tidy_btn.text() == "Tidy tags"
        assert view.tidy_btn.objectName() == "ghost"
        assert view.tidy_btn.toolTip() == "Find and merge variant or misspelled tags"

    def test_notes_view_accepts_and_stores_settings(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.ui.notes_view import NotesView

        settings = _tag_settings(tmp_path)
        view = NotesView(NoteStore(tmp_path), None, settings=settings)
        assert view.settings is settings

    def test_detection_is_lazy_not_on_render(self, qapp, tmp_path, monkeypatch):
        # suggest_tag_groups (used by the dialog) must NOT run on list render - only when the
        # dialog opens. A spy on it stays at zero through construction + refresh().
        import serenity.ui.tag_consolidation_dialog as tcd
        from serenity.ui.notes_view import NotesView

        calls = []
        real = tcd.suggest_tag_groups
        monkeypatch.setattr(
            tcd, "suggest_tag_groups",
            lambda notes, arsenal=None: (calls.append(1), real(notes, arsenal=arsenal))[1],
        )

        view = NotesView(_tag_store(tmp_path), None, settings=_tag_settings(tmp_path))
        view.refresh()
        assert calls == []              # detection has not run before the dialog opens

    def test_open_runs_detection_and_lists_rows(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.tag_consolidation_dialog as tcd
        from serenity.ui.notes_view import NotesView

        calls = []
        real = tcd.suggest_tag_groups
        monkeypatch.setattr(
            tcd, "suggest_tag_groups",
            lambda notes, arsenal=None: (calls.append(1), real(notes, arsenal=arsenal))[1],
        )
        captured = {}
        real_init = tcd.TagConsolidationDialog.__init__

        def _spy_init(self, store, settings, notes_provider=None, parent=None):
            real_init(self, store, settings, notes_provider=notes_provider, parent=parent)
            captured["dlg"] = self

        monkeypatch.setattr(tcd.TagConsolidationDialog, "__init__", _spy_init)
        monkeypatch.setattr(tcd.TagConsolidationDialog, "exec", lambda self: None)

        view = NotesView(_tag_store(tmp_path), None, settings=_tag_settings(tmp_path))
        view._open_tag_consolidation()
        assert calls == [1]                          # detection ran exactly once, on open
        assert len(_tag_rows(captured["dlg"])) >= 1  # the Work/work/works group is listed

    def test_dialog_lists_group_row(self, qapp, tmp_path):
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = _tag_store(tmp_path)
        dlg = TagConsolidationDialog(store, _tag_settings(tmp_path),
                                     notes_provider=store.all_active)
        rows = _tag_rows(dlg)
        assert len(rows) >= 1
        assert dlg.empty_label.isHidden()
        assert not dlg.scroll.isHidden()
        # The group's editable canonical defaults to the suggested canonical (a member tag).
        assert rows[0]._combo.currentText() in {"Work", "work", "works"}

    def test_apply_renames_tags_across_notes_and_arsenal(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.tag_consolidation_dialog as tcd
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = _tag_store(tmp_path)
        settings = _tag_settings(tmp_path)
        dlg = TagConsolidationDialog(store, settings, notes_provider=store.all_active)
        rows = _tag_rows(dlg)
        assert rows
        row = rows[0]
        # Pin the canonical to a known member so the assertions are deterministic.
        row._combo.setCurrentText("Work")

        applied_fired = []
        dlg.applied.connect(lambda: applied_fired.append(1))
        monkeypatch.setattr(tcd.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

        _tag_row_buttons(row)["Apply"].click()

        # Row removed; applied signal fired.
        assert len(_tag_rows(dlg)) == len(rows) - 1
        assert applied_fired == [1]
        # Every note now carries the exact canonical "Work" and NO variant case/plural form.
        all_tags = [t for n in store.all_active() for t in n.tags]
        assert "Work" in all_tags
        assert "work" not in all_tags and "works" not in all_tags
        # An unrelated tag on note A is preserved.
        a = next(n for n in store.all_active() if n.title == "A")
        assert "urgent" in a.tags
        # Arsenal: variants dropped, canonical present, unrelated "Other" kept.
        assert "work" not in settings.tags and "works" not in settings.tags
        assert "Work" in settings.tags and "Other" in settings.tags

    def test_apply_respects_edited_canonical(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.tag_consolidation_dialog as tcd
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = _tag_store(tmp_path)
        settings = _tag_settings(tmp_path)
        dlg = TagConsolidationDialog(store, settings, notes_provider=store.all_active)
        row = _tag_rows(dlg)[0]
        # Type a brand-new canonical not among the members: ALL members fold into it.
        row._combo.setCurrentText("Job")

        monkeypatch.setattr(tcd.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        _tag_row_buttons(row)["Apply"].click()

        all_tags = [t for n in store.all_active() for t in n.tags]
        assert "Job" in all_tags
        for variant in ("Work", "work", "works"):
            assert variant not in all_tags
        assert "Job" in settings.tags

    def test_apply_cancel_does_nothing(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        import serenity.ui.tag_consolidation_dialog as tcd
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = _tag_store(tmp_path)
        settings = _tag_settings(tmp_path)
        dlg = TagConsolidationDialog(store, settings, notes_provider=store.all_active)
        rows = _tag_rows(dlg)
        assert rows
        applied_fired = []
        dlg.applied.connect(lambda: applied_fired.append(1))
        monkeypatch.setattr(tcd.QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)

        _tag_row_buttons(rows[0])["Apply"].click()

        assert len(_tag_rows(dlg)) == len(rows)          # row still present
        assert applied_fired == []                       # signal NOT emitted
        # No note rewritten: the variant tags survive untouched.
        all_tags = [t for n in store.all_active() for t in n.tags]
        assert "work" in all_tags and "works" in all_tags

    def test_apply_empty_canonical_shows_info_no_consolidate(self, qapp, tmp_path, monkeypatch):
        import serenity.ui.tag_consolidation_dialog as tcd
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = _tag_store(tmp_path)
        settings = _tag_settings(tmp_path)
        dlg = TagConsolidationDialog(store, settings, notes_provider=store.all_active)
        row = _tag_rows(dlg)[0]
        row._combo.setCurrentText("   ")                 # blank -> guarded

        info = []
        monkeypatch.setattr(tcd.QMessageBox, "information", lambda *a, **k: info.append(1))
        # question must NOT be reached; if it is, fail loudly.
        monkeypatch.setattr(tcd.QMessageBox, "question",
                            lambda *a, **k: pytest.fail("confirm reached on empty canonical"))

        _tag_row_buttons(row)["Apply"].click()
        assert info == [1]                               # info shown
        assert len(_tag_rows(dlg)) == 1                  # row kept (not consolidated)
        all_tags = [t for n in store.all_active() for t in n.tags]
        assert "work" in all_tags                        # nothing rewritten

    def test_dismiss_removes_row_no_change(self, qapp, tmp_path):
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = _tag_store(tmp_path)
        settings = _tag_settings(tmp_path)
        before = sorted(t for n in store.all_active() for t in n.tags)
        dlg = TagConsolidationDialog(store, settings, notes_provider=store.all_active)
        rows = _tag_rows(dlg)
        assert rows

        _tag_row_buttons(rows[0])["Dismiss"].click()
        assert len(_tag_rows(dlg)) == len(rows) - 1      # row gone (session-only)
        # Store + arsenal untouched by a dismiss.
        assert sorted(t for n in store.all_active() for t in n.tags) == before
        assert settings.tags == ["Work", "work", "works", "Other"]

    def test_empty_state_when_no_groups(self, qapp, tmp_path):
        from serenity.core.note_store import NoteStore
        from serenity.core.settings import Settings
        from serenity.ui.tag_consolidation_dialog import TagConsolidationDialog

        store = NoteStore(tmp_path)
        store.create("A", body="x", tags=["alpha"])
        store.create("B", body="y", tags=["beta"])      # no two tags are variants
        settings = Settings()
        settings.tags = ["alpha", "beta"]
        dlg = TagConsolidationDialog(store, settings, notes_provider=store.all_active)
        assert _tag_rows(dlg) == []
        assert not dlg.empty_label.isHidden()
        assert dlg.empty_label.text() == "No variant tags found."
        assert dlg.scroll.isHidden()


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
