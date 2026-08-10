"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for TodoStore (JSON) and NoteStore (markdown + index).
Role:    Guards persistence + lifecycle: todos round-trip and rank; notes write
         real .md files with parseable front-matter; trash/restore/purge work;
         the index is rebuilt from the filesystem (source of truth).

Test classes:
- TestTodoStore / TestNoteStore / TestSettings
============================================================
"""

from serenity.core.models import SubTask, Todo
from serenity.core.note_store import NoteStore, parse_markdown
from serenity.core.settings import Settings
from serenity.core.todo_store import TodoStore


class TestTodoStore:
    def test_add_and_persist_roundtrip(self, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="buy milk"))
        store2 = TodoStore(tmp_path)              # reopen -> reload from disk
        assert [t.title for t in store2.all()] == ["buy milk"]

    def test_complete_moves_to_trash(self, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="task"))
        store.complete(t.id)
        assert t.id not in [x.id for x in store.active()]
        assert t.id in [x.id for x in store.trash()]

    def test_recurring_spawns_next(self, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="standup", recurring="every weekday"))
        store.complete(t.id)
        active_titles = [x.title for x in store.active()]
        assert "standup" in active_titles          # a fresh occurrence exists

    def test_recurring_clone_resets_state_and_keeps_meta(self, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(
            title="standup",
            recurring="every weekday",
            category="Work",
            tags=["team", "daily"],
            subtasks=[SubTask(text="a", done=True), SubTask(text="b")],
            timer_seconds=120,
        ))
        store.complete(t.id)
        clone = next(x for x in store.active() if x.title == "standup" and x.id != t.id)
        assert clone.subtasks == []          # subtasks reset, not carried
        assert clone.timer_seconds == 0      # timer reset
        assert clone.done is False
        assert clone.category == "Work"      # meta carried
        assert clone.tags == ["team", "daily"]

    def test_soft_delete_restore_purge(self, tmp_path):
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="x"))
        store.soft_delete(t.id)
        assert t.id in [x.id for x in store.trash()]
        store.restore(t.id)
        assert t.id in [x.id for x in store.active()]
        store.purge(t.id)
        assert store.get(t.id) is None

    def test_new_todo_sinks_to_bottom(self, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="first"))
        store.add(Todo(title="second"))
        assert [t.title for t in store.active()] == ["first", "second"]

    def test_subtask_progress(self):
        t = Todo(title="x", subtasks=[SubTask(text="a", done=True), SubTask(text="b")])
        assert t.progress == 0.5

    def test_linked_note_ids_roundtrip(self, tmp_path):
        # FEATURE 4: a todo's linked note ids persist and reload (default []).
        assert Todo(title="x").linked_note_ids == []
        store = TodoStore(tmp_path)
        t = store.add(Todo(title="meeting", linked_note_ids=["nid1", "nid2"]))
        store2 = TodoStore(tmp_path)
        reloaded = store2.get(t.id)
        assert reloaded.linked_note_ids == ["nid1", "nid2"]

    def test_trash_and_purge_keep_linked_note(self, tmp_path):
        # FEATURE 4: the linked note lives in NoteStore and must survive the todo's removal.
        todos = TodoStore(tmp_path)
        notes = NoteStore(tmp_path)
        note = notes.create("Prep", body="agenda")
        t = todos.add(Todo(title="meeting", linked_note_ids=[note.id]))
        todos.soft_delete(t.id)
        assert notes.get(note.id) is not None        # trashing the todo keeps the note
        todos.purge(t.id)
        assert todos.get(t.id) is None
        assert notes.get(note.id) is not None        # purging the todo keeps the note too

    def test_reload_tolerates_document_shape(self, tmp_path):
        # the spec (3.1) documents todos.json as {"version":1,"todos":[...]}.
        # Loading that shape must not crash.
        import json
        (tmp_path / "todos.json").write_text(
            json.dumps({"version": 1, "todos": [{"id": "abc", "title": "doc-shaped"}]}),
            encoding="utf-8",
        )
        store = TodoStore(tmp_path)
        assert [t.title for t in store.all()] == ["doc-shaped"]

    def test_reload_tolerates_corrupt_or_unexpected(self, tmp_path):
        # a non-list/non-doc top-level value must degrade to empty, not crash.
        import json
        (tmp_path / "todos.json").write_text(json.dumps("not a list"), encoding="utf-8")
        store = TodoStore(tmp_path)
        assert store.all() == []


class TestNoteStore:
    def test_create_writes_markdown_file(self, tmp_path):
        store = NoteStore(tmp_path)
        note = store.create("Hello", body="world body", tags=["idea"])
        from pathlib import Path
        assert Path(note.path).exists()
        text = Path(note.path).read_text(encoding="utf-8")
        fm, body = parse_markdown(text)
        assert fm["title"] == "Hello"
        assert "idea" in fm["tags"]
        assert "world body" in body

    def test_index_rebuilt_from_filesystem(self, tmp_path):
        store = NoteStore(tmp_path)
        store.create("Persisted", body="content here")
        store2 = NoteStore(tmp_path)               # reopen -> reindex from disk
        titles = [n.title for n in store2.all_active()]
        assert "Persisted" in titles

    def test_search_finds_by_body(self, tmp_path):
        store = NoteStore(tmp_path)
        store.create("A", body="ship the beta on friday")
        store.create("B", body="nothing relevant")
        out = store.search("beta")
        assert [n.title for n in out] == ["A"]

    def test_pin_floats_to_top(self, tmp_path):
        store = NoteStore(tmp_path)
        a = store.create("A")
        b = store.create("B")
        store.set_pinned(b.id, True)
        assert store.all_active()[0].title == "B"

    def test_delete_restore_purge(self, tmp_path):
        from pathlib import Path
        store = NoteStore(tmp_path)
        n = store.create("Trashable")
        store.soft_delete(n.id)
        assert n.id in [x.id for x in store.trash()]
        assert n.id not in [x.id for x in store.all_active()]
        store.restore(n.id)
        assert n.id in [x.id for x in store.all_active()]
        store.purge(n.id)
        assert store.get(n.id) is None
        assert not Path(n.path).exists()

    def test_color_defaults_assigned(self, tmp_path):
        from serenity.core.models import NOTE_COLORS
        store = NoteStore(tmp_path)
        n = store.create("Colorful")
        assert n.color in NOTE_COLORS

    def test_purge_unlinks_sibling_draft(self, tmp_path):
        # purge must also remove the .draft sidecar so it can't resurrect a note (P1-3)
        from pathlib import Path
        store = NoteStore(tmp_path)
        n = store.create("Trashable")
        draft = Path(n.path + ".draft")
        draft.write_text("x", encoding="utf-8")
        store.purge(n.id)
        assert not Path(n.path).exists()
        assert not draft.exists()

    def test_reload_note_resyncs_from_disk(self, tmp_path):
        # an external .md edit is picked up by reload_note into the in-memory map (P1-11)
        from pathlib import Path
        from serenity.core.note_store import serialize
        store = NoteStore(tmp_path)
        n = store.create("Title", body="orig")
        text = serialize(n).replace("orig", "externally edited")
        Path(n.path).write_text(text, encoding="utf-8")
        store.reload_note(n.id)
        assert "externally edited" in store.get(n.id).body

    def test_reload_note_drops_when_md_vanished(self, tmp_path):
        from pathlib import Path
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        Path(n.path).unlink()
        store.reload_note(n.id)
        assert store.get(n.id) is None

    def test_reload_note_drops_stale_id_when_external_edit_changed_id(self, tmp_path):
        # an external edit that drops/changes the id must NOT leave a phantom duplicate keyed on
        # the old id (which could later overwrite the newer file) - P1-11
        from pathlib import Path
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        orig_id = n.id
        # strip the id line on disk -> from_frontmatter will mint a fresh one on reload
        text = Path(n.path).read_text(encoding="utf-8")
        stripped = "\n".join(ln for ln in text.splitlines() if not ln.startswith("id:")) + "\n"
        Path(n.path).write_text(stripped, encoding="utf-8")
        store.reload_note(orig_id)
        # the stale id is gone (no phantom), and exactly one note points at that path
        assert store.get(orig_id) is None
        same_path = [m for m in store._notes.values() if m.path == n.path]
        assert len(same_path) == 1


class TestSettings:
    def test_defaults_and_roundtrip(self, tmp_path):
        p = tmp_path / "settings.json"
        s = Settings.load(p)
        assert s.render_scale == "M"
        assert s.avatar_px == 152
        s.render_scale = "L"
        s.save()
        s2 = Settings.load(p)
        assert s2.render_scale == "L"
        assert s2.avatar_px == 192

    def test_undo_seconds_default_is_five(self, tmp_path):
        # FEATURE 5: the done-todo grace window defaults to 5s (was 20).
        s = Settings.load(tmp_path / "settings.json")
        assert s.undo_seconds == 5

    def test_corrupt_settings_falls_back_to_defaults(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text("{ not valid json ", encoding="utf-8")
        s = Settings.load(p)
        assert s.render_scale == "M"
        assert s.vault_path != ""

    def test_clone_and_cache_settings_roundtrip(self, tmp_path):
        # The new Chatterbox clone + cache fields persist and reload.
        p = tmp_path / "settings.json"
        s = Settings.load(p)
        assert s.tts_clone_de == "" and s.tts_clone_en == ""
        assert s.tts_cache_enabled is True
        s.tts_engine_de = "chatterbox"
        s.tts_clone_de = "clone:mum_de"
        s.tts_clone_en = "clone:berk_en"
        s.tts_cache_enabled = False
        s.save()
        s2 = Settings.load(p)
        assert s2.tts_engine_de == "chatterbox"
        assert s2.tts_clone_de == "clone:mum_de"
        assert s2.tts_clone_en == "clone:berk_en"
        assert s2.tts_cache_enabled is False

    def test_numeric_fields_coerced_from_strings(self, tmp_path):
        # a hand-edited settings.json may carry stringy numbers; the UI feeds these
        # straight into QSlider.setValue, which requires real ints.
        import json
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"undo_seconds": "30"}), encoding="utf-8")
        s = Settings.load(p)
        assert s.undo_seconds == 30
        assert isinstance(s.undo_seconds, int)

    def test_tag_arsenal_starts_with_basics_and_learns(self, tmp_path):
        s = Settings.load(tmp_path / "settings.json")
        assert "Work" in s.tags and "Health" in s.tags
        grew = s.add_tags(["Garden", "work"])     # 'work' is a dup (case-insensitive)
        assert grew is True
        assert "Garden" in s.tags
        assert sum(1 for t in s.tags if t.lower() == "work") == 1
