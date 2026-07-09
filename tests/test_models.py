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
- test_todo_reminder_fields_default_values — reminder fields default to [] / [] / None / None
- test_todo_reminder_fields_roundtrip — round-trip all 4 reminder fields via to_dict/from_dict
- test_todo_reminder_fields_missing_in_old_doc — old dict without reminder keys loads defaults
- test_todo_reminder_offsets_coercion — non-list / dirty values coerce properly
- test_todo_reminder_fired_keeps_sentinel — reminder_fired=[0, 5] is kept (sentinel allowed)
- test_todo_reminder_active_coercion — invalid active values coerce to None, valid ones kept
- test_todo_reminder_nudge_at_coercion — invalid datetime coerces to None, valid ISO round-trips
============================================================
"""

from datetime import datetime
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


def test_todo_reminder_fields_default_values():
    t = Todo(title="x")
    assert t.reminder_offsets == []
    assert t.reminder_fired == []
    assert t.reminder_active is None
    assert t.reminder_nudge_at is None


def test_todo_reminder_fields_roundtrip():
    now = datetime.now()
    t = Todo(
        title="x",
        reminder_offsets=[60, 1440],
        reminder_fired=[0],
        reminder_active=60,
        reminder_nudge_at=now,
    )
    d = t.to_dict()
    assert "reminder_offsets" in d
    assert "reminder_fired" in d
    assert "reminder_active" in d
    assert "reminder_nudge_at" in d
    t2 = Todo.from_dict(d)
    # reminder_offsets are sorted in descending order by _clean_rungs
    assert t2.reminder_offsets == [1440, 60]
    assert t2.reminder_fired == [0]
    assert t2.reminder_active == 60
    assert t2.reminder_nudge_at == now


def test_todo_reminder_fields_missing_in_old_doc():
    d = Todo(title="old").to_dict()
    d.pop("reminder_offsets", None)
    d.pop("reminder_fired", None)
    d.pop("reminder_active", None)
    d.pop("reminder_nudge_at", None)
    t = Todo.from_dict(d)
    assert t.reminder_offsets == []
    assert t.reminder_fired == []
    assert t.reminder_active is None
    assert t.reminder_nudge_at is None


def test_todo_reminder_offsets_coercion():
    # non-list -> []
    t = Todo.from_dict({"id": "a", "reminder_offsets": 60})
    assert t.reminder_offsets == []

    # mixed valid/invalid -> only valid known values kept, desc order, dedup
    t = Todo.from_dict({"id": "a", "reminder_offsets": [60, 99, 60, "x"]})
    assert t.reminder_offsets == [60]


def test_todo_reminder_active_coercion():
    # invalid active values -> None
    t = Todo.from_dict({"id": "a", "reminder_active": 99})
    assert t.reminder_active is None

    # 0 is valid (means no active reminder)
    t = Todo.from_dict({"id": "a", "reminder_active": 0})
    assert t.reminder_active == 0

    # valid known value is kept
    t = Todo.from_dict({"id": "a", "reminder_active": 60})
    assert t.reminder_active == 60


def test_todo_reminder_nudge_at_coercion():
    # invalid datetime -> None
    t = Todo.from_dict({"id": "a", "reminder_nudge_at": "garbage"})
    assert t.reminder_nudge_at is None

    # valid ISO datetime round-trips
    now = datetime.now()
    iso_str = now.isoformat()
    t = Todo.from_dict({"id": "a", "reminder_nudge_at": iso_str})
    assert t.reminder_nudge_at == now


def test_todo_reminder_fired_coercion_non_list():
    # non-list reminder_fired -> []
    t = Todo.from_dict({"id": "a", "reminder_fired": 60})
    assert t.reminder_fired == []


def test_todo_reminder_fired_coercion_dirty_values():
    # [60, 99, 60, "x"] -> [60] (only known rungs, deduped, sorted desc)
    t = Todo.from_dict({"id": "a", "reminder_fired": [60, 99, 60, "x"]})
    assert t.reminder_fired == [60]


def test_todo_reminder_fired_sentinel_coercion():
    # [0, 5] with _clean_rungs(..., extra=(0,)) -> [5, 0] (sorted desc, deduped)
    t = Todo.from_dict({"id": "a", "reminder_fired": [0, 5]})
    assert t.reminder_fired == [5, 0]
