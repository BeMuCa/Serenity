"""
============================================================
Author:  Berk
Created: 2026-08-12
Purpose: Test the Meeting-Prep core - block splicing, carry-over extraction, predecessor
         lookup, gathering/rendering, orchestration and auto-prep eligibility.
Role:    Guards the pure logic behind the Vorbereitung block written into a meeting's
         protocol note. Spec: docs/superpowers/specs/2026-08-12-meeting-prep-design.md

Test classes:
- TestSplice - marker region insert/replace, text outside is never touched
- TestExtractCarryover - open vs ticked vs struck entries, defer words, malformed input
- TestFindPredecessor - series key beats topic, strictly-earlier rule (N2), none
- TestGatherAndRender - the four content blocks, source attribution, empty-predecessor line
- TestDueForAutoPrep - the 18h window, arming, already-prepped exclusion
- TestPrepTodo - orchestration against a real NoteStore/TodoStore
- TestSeriesCarry - series_id/prep_auto survive recurrence and the model round-trip
============================================================
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from serenity.core.meeting_prep import (
    PREP_END,
    PREP_START,
    Carryover,
    PrepInput,
    apply_refined,
    due_for_auto_prep,
    extract_carryover,
    find_predecessor,
    gather,
    is_prepped,
    prep_todo,
    render_prep,
    series_tag,
    splice,
)
from serenity.core.models import Note, Todo
from serenity.core.note_store import NoteStore
from serenity.core.todo_store import TodoStore

PROTOCOL = (
    "# Protokoll - 2026-08-07\n\n"
    "## Teilnehmer\n- Berk\n\n"
    "## Agenda\n- [x] Punkt 1\n- Punkt 3 offen\n\n"
    "## Notizen\n- irgendwas\n\n"
    "## Beschluesse\n- Budget Q4 vertagt\n- Tool gekauft\n\n"
    "## Aufgaben\n- [x] Protokoll verschickt\n- Angebot an Mueller schicken\n- ~~alter Punkt~~\n"
)


def _note(title, body="", tags=(), created=None, deleted=False):
    return Note(title=title, body=body, tags=list(tags), deleted=deleted,
                created=created or datetime(2026, 8, 1), updated=created or datetime(2026, 8, 1))


class TestSplice:
    """The marker region: insert, replace, and never touch text outside it."""

    def test_inserts_under_the_heading_when_no_markers_yet(self):
        out = splice("# Protokoll - 2026-08-14\n\n## Teilnehmer\n- \n", "## Vorbereitung\n- x")
        assert out.index(PREP_START) > out.index("# Protokoll")
        assert out.index(PREP_START) < out.index("## Teilnehmer")

    def test_replaces_between_markers_and_keeps_your_text(self):
        first = splice("# P\n\n## Notizen\n- meins\n", "## Vorbereitung\n- alt")
        second = splice(first, "## Vorbereitung\n- neu")
        assert "- neu" in second and "- alt" not in second
        assert "- meins" in second
        assert second.count(PREP_START) == 1 and second.count(PREP_END) == 1

    def test_is_prepped_needs_both_markers(self):
        assert is_prepped(f"{PREP_START}\nx\n{PREP_END}")
        assert not is_prepped(f"{PREP_START}\nx")
        assert not is_prepped("nothing here")

    def test_empty_note_still_gets_a_region(self):
        assert is_prepped(splice("", "## Vorbereitung"))


class TestExtractCarryover:
    """Open vs ticked vs struck entries, defer words, and malformed input."""

    def test_open_aufgaben_only(self):
        c = extract_carryover(PROTOCOL)
        assert c.aufgaben == ["Angebot an Mueller schicken"]

    def test_open_agenda_only(self):
        assert extract_carryover(PROTOCOL).agenda == ["Punkt 3 offen"]

    def test_only_deferred_beschluesse(self):
        assert extract_carryover(PROTOCOL).beschluesse == ["Budget Q4 vertagt"]

    def test_umlaut_and_colon_heading_variants_are_accepted(self):
        c = extract_carryover("## Beschlüsse:\n- Thema verschoben\n")
        assert c.beschluesse == ["Thema verschoben"]

    def test_missing_sections_are_empty_not_an_error(self):
        assert extract_carryover("# nur ein Titel\n\nFliesstext.").is_empty()

    def test_empty_input_is_empty(self):
        assert extract_carryover("").is_empty()


class TestFindPredecessor:
    """Series key first, topic fallback, and the strictly-earlier rule."""

    def test_series_key_beats_a_newer_topical_match(self):
        todo = Todo(title="Weekly", series_id="s1", due=datetime(2026, 8, 14))
        old = _note("Protokoll Weekly", PROTOCOL, ["Protokoll", "meeting", series_tag("s1")],
                    datetime(2026, 8, 7))
        newer = _note("Protokoll Weekly", PROTOCOL, ["Protokoll", "meeting"], datetime(2026, 8, 10))
        found, source = find_predecessor(todo, [newer, old])
        assert (found.id, source) == (old.id, "series")

    def test_topic_fallback_when_no_series_note(self):
        todo = Todo(title="Weekly", due=datetime(2026, 8, 14))
        prot = _note("Protokoll Weekly", PROTOCOL, ["Protokoll", "meeting"], datetime(2026, 8, 7))
        found, source = find_predecessor(todo, [prot, _note("Einkaufsliste")])
        assert (found.id, source) == (prot.id, "topic")

    def test_a_later_note_is_never_the_predecessor(self):
        todo = Todo(title="Weekly", series_id="s1", due=datetime(2026, 8, 7))
        later = _note("Protokoll Weekly", PROTOCOL, ["Protokoll", "meeting", series_tag("s1")],
                      datetime(2026, 8, 14))
        assert find_predecessor(todo, [later]) == (None, None)

    def test_the_occurrences_own_note_is_excluded(self):
        own = _note("Protokoll Weekly", PROTOCOL, ["Protokoll", "meeting"], datetime(2026, 8, 1))
        todo = Todo(title="Weekly", due=datetime(2026, 8, 14), linked_note_ids=[own.id])
        assert find_predecessor(todo, [own]) == (None, None)

    def test_nothing_found_returns_none(self):
        todo = Todo(title="Weekly", due=datetime(2026, 8, 14))
        assert find_predecessor(todo, [_note("Einkaufsliste")]) == (None, None)


class TestGatherAndRender:
    """The four content blocks, the source attribution, and the empty-predecessor line."""

    def _setup(self):
        prot = _note("Protokoll Weekly", PROTOCOL, ["Protokoll", "meeting", series_tag("s1")],
                     datetime(2026, 8, 7))
        fresh = _note("Angebot Mueller", "text", ["Weekly"], datetime(2026, 8, 9))
        stale = _note("Uraltes", "text", ["Weekly"], datetime(2026, 7, 1))
        meeting = Todo(title="Weekly", series_id="s1", due=datetime(2026, 8, 14), tags=["Weekly"])
        mine = Todo(title="Angebot finalisieren", tags=["Weekly"])
        return meeting, [prot, fresh, stale], [meeting, mine]

    def test_gather_collects_all_four_parts(self):
        meeting, notes, todos = self._setup()
        prep = gather(meeting, notes, todos)
        assert prep.source == "series"
        assert prep.carryover.aufgaben == ["Angebot an Mueller schicken"]
        assert prep.carryover.agenda == ["Punkt 3 offen"]
        assert prep.own_todos == ["Angebot finalisieren"]

    def test_related_excludes_notes_older_than_the_predecessor(self):
        meeting, notes, todos = self._setup()
        assert "Uraltes" not in gather(meeting, notes, todos).related

    def test_render_names_the_source_and_the_generation_date(self):
        meeting, notes, todos = self._setup()
        out = render_prep(gather(meeting, notes, todos), "de", datetime(2026, 8, 13))
        assert "2026-08-07" in out and "Serie" in out
        assert "2026-08-13" in out

    def test_render_says_so_when_there_is_no_predecessor(self):
        out = render_prep(gather(Todo(title="Neu", due=datetime(2026, 8, 14)), [], []), "de")
        assert "Kein frueheres Protokoll" in out

    def test_render_is_deterministic(self):
        meeting, notes, todos = self._setup()
        stamp = datetime(2026, 8, 13)
        prep = gather(meeting, notes, todos)
        assert render_prep(prep, "de", stamp) == render_prep(prep, "de", stamp)

    def test_english_renders_english_labels(self):
        out = render_prep(PrepInput(title="Weekly", carryover=Carryover()), "en")
        assert "Preparation" in out and "Vorbereitung" not in out


class TestDueForAutoPrep:
    """The 18h window, the arming flag, and the already-prepped exclusion."""

    def _meeting(self, hours, **kw):
        now = datetime(2026, 8, 12, 20, 0)
        return Todo(title="Weekly", prep_auto=True, due=now + timedelta(hours=hours), **kw)

    def test_inside_the_window_is_eligible(self):
        now = datetime(2026, 8, 12, 20, 0)
        assert due_for_auto_prep([self._meeting(12)], now)

    def test_outside_the_window_is_not(self):
        now = datetime(2026, 8, 12, 20, 0)
        assert due_for_auto_prep([self._meeting(30)], now) == []

    def test_past_due_is_not_prepped(self):
        now = datetime(2026, 8, 12, 20, 0)
        assert due_for_auto_prep([self._meeting(-1)], now) == []

    def test_unarmed_meetings_are_skipped(self):
        now = datetime(2026, 8, 12, 20, 0)
        meeting = self._meeting(12)
        meeting.prep_auto = False
        assert due_for_auto_prep([meeting], now) == []

    def test_already_prepped_is_skipped(self):
        now = datetime(2026, 8, 12, 20, 0)
        assert due_for_auto_prep([self._meeting(12)], now, is_prepped_fn=lambda t: True) == []

    def test_done_and_dateless_are_skipped(self):
        now = datetime(2026, 8, 12, 20, 0)
        done = self._meeting(12)
        done.done = True
        assert due_for_auto_prep([done, Todo(title="x", prep_auto=True)], now) == []


class TestPrepTodo:
    """Orchestration against real stores: create+link, splice, and the stale-result guard."""

    @pytest.fixture()
    def stores(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            notes = NoteStore(vault, index_path=vault / ".index.sqlite")
            todos = TodoStore(vault)
            yield notes, todos
            notes.close()

    def test_creates_links_and_prepares_the_protocol_note(self, stores):
        note_store, todo_store = stores
        meeting = todo_store.add(Todo(title="Weekly", category="meeting", series_id="s1",
                                      due=datetime(2026, 8, 14)))
        note, _ = prep_todo(meeting, note_store, todo_store, [meeting], "# Protokoll - 2026-08-14\n")
        assert meeting.linked_note_ids == [note.id]
        assert is_prepped(note_store.get(note.id).body)
        assert series_tag("s1") in note.tags

    def test_re_prepping_keeps_what_you_typed(self, stores):
        note_store, todo_store = stores
        meeting = todo_store.add(Todo(title="Weekly", category="meeting", due=datetime(2026, 8, 14)))
        note, _ = prep_todo(meeting, note_store, todo_store, [meeting], "# Protokoll\n")
        note.body += "\n## Notizen\n- meine eigene Zeile\n"
        note_store.update(note)
        prep_todo(meeting, note_store, todo_store, [meeting], "# Protokoll\n")
        assert "meine eigene Zeile" in note_store.get(note.id).body

    def test_refined_block_is_applied(self, stores):
        note_store, todo_store = stores
        meeting = todo_store.add(Todo(title="Weekly", category="meeting", due=datetime(2026, 8, 14)))
        note, _ = prep_todo(meeting, note_store, todo_store, [meeting], "# Protokoll\n")
        assert apply_refined(note.id, "## Vorbereitung\n- verfeinert", note_store)
        assert "verfeinert" in note_store.get(note.id).body

    def test_refined_block_is_dropped_when_the_markers_are_gone(self, stores):
        note_store, todo_store = stores
        meeting = todo_store.add(Todo(title="Weekly", category="meeting", due=datetime(2026, 8, 14)))
        note, _ = prep_todo(meeting, note_store, todo_store, [meeting], "# Protokoll\n")
        note.body = "# Protokoll\n\n## Notizen\n- ich habe den Block geloescht\n"
        note_store.update(note)
        assert apply_refined(note.id, "## Vorbereitung\n- verfeinert", note_store) is False
        assert "verfeinert" not in note_store.get(note.id).body

    def test_refined_block_is_dropped_for_a_missing_note(self, stores):
        note_store, _ = stores
        assert apply_refined("nope", "## Vorbereitung", note_store) is False


class TestSeriesCarry:
    """series_id/prep_auto survive the model round-trip and recurrence."""

    def test_round_trip(self):
        t = Todo(title="Weekly", series_id="s1", prep_auto=True)
        back = Todo.from_dict(t.to_dict())
        assert (back.series_id, back.prep_auto) == ("s1", True)

    def test_old_documents_without_the_keys_still_load(self):
        back = Todo.from_dict({"id": "x", "title": "alt"})
        assert (back.series_id, back.prep_auto) == (None, False)

    def test_recurrence_seeds_then_carries_the_series_key(self):
        with tempfile.TemporaryDirectory() as d:
            store = TodoStore(Path(d))
            first = store.add(Todo(title="Weekly", recurring="weekly", prep_auto=True,
                                   due=datetime(2026, 8, 7)))
            store.complete(first.id)
            second = [t for t in store.all() if not t.done][0]
            assert second.series_id == first.id and second.prep_auto is True
            store.complete(second.id)
            third = [t for t in store.all() if not t.done][0]
            assert third.series_id == first.id
