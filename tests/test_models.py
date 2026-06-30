"""
============================================================
Author:  Berk
Created: 2026-06-30
Purpose: Tests for core data models.
Role:    Verifies serialization/deserialization round-trips and field handling.

Test functions:
- test_ics_uid_roundtrips_and_defaults_none — verify ics_uid field round-trips
- test_ics_uid_missing_in_old_doc_loads_none — verify backward compatibility
============================================================
"""

from serenity.core.models import Todo


def test_ics_uid_roundtrips_and_defaults_none():
    assert Todo().ics_uid is None
    t = Todo(title="x", ics_uid="abc@serenity")
    assert Todo.from_dict(t.to_dict()).ics_uid == "abc@serenity"


def test_ics_uid_missing_in_old_doc_loads_none():
    d = Todo(title="legacy").to_dict()
    d.pop("ics_uid", None)            # simulate a pre-field todos.json
    assert Todo.from_dict(d).ics_uid is None
