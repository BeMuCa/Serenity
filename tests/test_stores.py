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

    def test_tag_arsenal_starts_with_basics_and_learns(self, tmp_path):
        s = Settings.load(tmp_path / "settings.json")
        assert "Work" in s.tags and "Health" in s.tags
        grew = s.add_tags(["Garden", "work"])     # 'work' is a dup (case-insensitive)
        assert grew is True
        assert "Garden" in s.tags
        assert sum(1 for t in s.tags if t.lower() == "work") == 1
