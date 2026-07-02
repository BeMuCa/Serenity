"""
============================================================
Author:  Berk
Created: 2026-06-30
Purpose: Tests for core data models.
Role:    Verifies serialization/deserialization round-trips and field handling.

Test functions:
- test_ics_uid_roundtrips_and_defaults_none — verify ics_uid field round-trips
- test_ics_uid_missing_in_old_doc_loads_none — verify backward compatibility
- test_todo_state_tag_context_roundtrip — Phase C stamp fields round-trip (Todo)
- test_todo_legacy_dict_defaults_none — pre-Phase-C todo loads with None stamps
- test_todo_invalid_context_and_state_coerce_none — untrusted values coerce to None
- test_note_state_tag_context_roundtrip_and_legacy — Phase C stamp fields (Note)
- test_note_invalid_context_coerces_none — wrong-case/invalid context coerces to None
============================================================
"""

from serenity.core.models import Note, Todo


def test_ics_uid_roundtrips_and_defaults_none():
    assert Todo().ics_uid is None
    t = Todo(title="x", ics_uid="abc@serenity")
    assert Todo.from_dict(t.to_dict()).ics_uid == "abc@serenity"


def test_ics_uid_missing_in_old_doc_loads_none():
    d = Todo(title="legacy").to_dict()
    d.pop("ics_uid", None)            # simulate a pre-field todos.json
    assert Todo.from_dict(d).ics_uid is None


def test_todo_state_tag_context_roundtrip():
    t = Todo(title="x", state_tag="working", context="business")
    d = t.to_dict()
    assert d["state_tag"] == "working" and d["context"] == "business"
    t2 = Todo.from_dict(d)
    assert t2.state_tag == "working" and t2.context == "business"


def test_todo_legacy_dict_defaults_none():
    t = Todo.from_dict({"id": "a", "title": "old"})   # pre-Phase-C dict: keys absent
    assert t.state_tag is None and t.context is None


def test_todo_invalid_context_and_state_coerce_none():
    t = Todo.from_dict({"id": "a", "context": "banana", "state_tag": ["x"]})
    assert t.context is None and t.state_tag is None
    t = Todo.from_dict({"id": "a", "context": 123, "state_tag": ""})
    assert t.context is None and t.state_tag is None


def test_note_state_tag_context_roundtrip_and_legacy():
    n = Note(title="x", state_tag="working", context="private")
    fm = n.to_frontmatter()
    assert fm["state_tag"] == "working" and fm["context"] == "private"
    n2 = Note.from_frontmatter(fm, "body", "/tmp/x.md")
    assert n2.state_tag == "working" and n2.context == "private"
    old = Note.from_frontmatter({"id": "a", "title": "old"}, "b", "/tmp/y.md")
    assert old.state_tag is None and old.context is None


def test_note_invalid_context_coerces_none():
    n = Note.from_frontmatter({"id": "a", "context": "Business"}, "b", "/tmp/y.md")
    assert n.context is None   # wrong case = invalid; matches BOTH contexts downstream
