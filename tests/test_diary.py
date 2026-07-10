"""
============================================================
Author:  Berk
Created: 2026-07-10
Purpose: Test DiaryStore and DiaryLine persistence, poison-ts handling, and mutations.
Role:    Verify the diary store tolerates corrupt JSON, drops poison timestamps,
         and persists diary lines correctly across reload cycles.

Test classes:
- TestDiaryLine - serialization round-trip
- TestDiaryStore - persistence, mutations, corrupt handling, P1-1 poison-ts skip
============================================================
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from serenity.core.diary import DiaryLine, DiaryStore


class TestDiaryLine:
    """DiaryLine serialization and instantiation."""

    def test_to_dict_serializes_ts_as_iso(self):
        """to_dict converts datetime to ISO string."""
        ts = datetime(2026, 7, 10, 14, 30, 0)
        line = DiaryLine(ts=ts, text="Test entry")
        d = line.to_dict()
        assert d["ts"] == "2026-07-10T14:30:00"
        assert d["text"] == "Test entry"
        assert "id" in d

    def test_from_dict_parses_iso_ts(self):
        """from_dict reconstructs datetime from ISO string."""
        d = {
            "id": "abc123",
            "ts": "2026-07-10T14:30:00",
            "text": "Test entry",
        }
        line = DiaryLine.from_dict(d)
        assert line.id == "abc123"
        assert line.ts == datetime(2026, 7, 10, 14, 30, 0)
        assert line.text == "Test entry"

    def test_from_dict_tolerant_to_missing_ts(self):
        """from_dict with missing ts returns None for ts (caller drops it)."""
        d = {
            "id": "abc123",
            "text": "Test entry",
        }
        line = DiaryLine.from_dict(d)
        assert line.ts is None

    def test_from_dict_tolerant_to_bad_ts(self):
        """from_dict with garbage ts returns None for ts (caller drops it)."""
        d = {
            "id": "abc123",
            "ts": "garbage",
            "text": "Test entry",
        }
        line = DiaryLine.from_dict(d)
        assert line.ts is None

    def test_from_dict_preserves_optional_fields(self):
        """from_dict populates state_tag and context."""
        d = {
            "id": "xyz",
            "ts": "2026-07-10T10:00:00",
            "text": "Entry",
            "state_tag": "done",
            "context": "business",
        }
        line = DiaryLine.from_dict(d)
        assert line.state_tag == "done"
        assert line.context == "business"

    def test_from_dict_generates_id_if_missing(self):
        """from_dict with missing id generates a new uuid4 hex."""
        d = {"ts": "2026-07-10T10:00:00", "text": "Entry"}
        line = DiaryLine.from_dict(d)
        assert line.id  # non-empty
        assert len(line.id) == 32  # uuid4().hex is 32 chars


class TestDiaryStore:
    """DiaryStore persistence, reload, save, and mutations."""

    def test_round_trip(self, tmp_path):
        """add lines -> new store instance -> same lines."""
        store1 = DiaryStore(tmp_path)
        ts1 = datetime(2026, 7, 10, 9, 0, 0)
        ts2 = datetime(2026, 7, 10, 10, 0, 0)

        line1 = DiaryLine(id="l1", ts=ts1, text="First")
        line2 = DiaryLine(id="l2", ts=ts2, text="Second", state_tag="done")

        store1.add(line1)
        store1.add(line2)

        # New instance reloads from disk
        store2 = DiaryStore(tmp_path)
        lines = store2.all()
        assert len(lines) == 2
        assert lines[0].id == "l1"
        assert lines[0].ts == ts1
        assert lines[0].text == "First"
        assert lines[1].id == "l2"
        assert lines[1].state_tag == "done"

    def test_add_persists(self, tmp_path):
        """add() saves immediately."""
        store = DiaryStore(tmp_path)
        line = DiaryLine(ts=datetime.now(), text="Test")
        store.add(line)

        # File should exist
        assert (tmp_path / "diary.json").exists()

    def test_edit_updates_text_only(self, tmp_path):
        """edit(id, text) updates text but preserves ts/state_tag/context."""
        store = DiaryStore(tmp_path)
        original_ts = datetime(2026, 7, 10, 10, 0, 0)
        line = DiaryLine(
            id="edit1",
            ts=original_ts,
            text="Original",
            state_tag="pending",
            context="business",
        )
        store.add(line)

        # Edit the text
        store.edit("edit1", "Updated text")

        # Verify ts/state_tag/context unchanged, text updated
        updated = store.get("edit1")
        assert updated.ts == original_ts
        assert updated.state_tag == "pending"
        assert updated.context == "business"
        assert updated.text == "Updated text"

    def test_edit_persists(self, tmp_path):
        """edit() saves to disk."""
        store1 = DiaryStore(tmp_path)
        line = DiaryLine(ts=datetime.now(), text="Original")
        store1.add(line)
        line_id = line.id

        store1.edit(line_id, "Changed")

        # Reload and verify
        store2 = DiaryStore(tmp_path)
        reloaded = store2.get(line_id)
        assert reloaded.text == "Changed"

    def test_delete_removes_and_persists(self, tmp_path):
        """delete(id) removes line and persists."""
        store1 = DiaryStore(tmp_path)
        line = DiaryLine(ts=datetime.now(), text="Temp")
        store1.add(line)
        line_id = line.id

        store1.delete(line_id)

        # Reload and verify it's gone
        store2 = DiaryStore(tmp_path)
        assert store2.get(line_id) is None
        assert len(store2.all()) == 0

    def test_corrupt_json_backed_up(self, tmp_path):
        """Corrupt JSON is renamed to .corrupt-<ts>, empty list loaded."""
        diary_path = tmp_path / "diary.json"
        diary_path.write_text("{[invalid json]}", encoding="utf-8")

        store = DiaryStore(tmp_path)

        # Should have backed up and loaded empty
        assert len(store.all()) == 0
        corrupt_files = list(tmp_path.glob("diary.json.corrupt-*"))
        assert len(corrupt_files) == 1

    def test_non_dict_rows_skipped(self, tmp_path):
        """JSON list with non-dict element: that element skipped, valid rows load."""
        diary_path = tmp_path / "diary.json"
        data = [
            {
                "id": "valid1",
                "ts": "2026-07-10T10:00:00",
                "text": "Valid",
            },
            "not a dict",  # Should be skipped
            123,  # Should be skipped
            {
                "id": "valid2",
                "ts": "2026-07-10T11:00:00",
                "text": "Also valid",
            },
        ]
        diary_path.write_text(json.dumps(data), encoding="utf-8")

        store = DiaryStore(tmp_path)
        lines = store.all()
        assert len(lines) == 2
        assert lines[0].id == "valid1"
        assert lines[1].id == "valid2"

    def test_poison_ts_dropped_p1_1(self, tmp_path):
        """P1-1: Rows with missing ts, bad ts, or ts=None are dropped from reload."""
        diary_path = tmp_path / "diary.json"
        data = [
            {
                "id": "good1",
                "ts": "2026-07-10T10:00:00",
                "text": "Good row",
            },
            {
                "id": "bad_missing_ts",
                # ts key missing
                "text": "No timestamp",
            },
            {
                "id": "bad_garbage_ts",
                "ts": "not-a-valid-iso",
                "text": "Garbage timestamp",
            },
            {
                "id": "good2",
                "ts": "2026-07-10T11:00:00",
                "text": "Another good row",
            },
        ]
        diary_path.write_text(json.dumps(data), encoding="utf-8")

        store = DiaryStore(tmp_path)
        lines = store.all()

        # Only the two valid rows should be present
        assert len(lines) == 2
        assert lines[0].id == "good1"
        assert lines[1].id == "good2"

        # Verify no line has ts=None
        for line in lines:
            assert line.ts is not None

    def test_all_returns_list(self, tmp_path):
        """all() returns a list of DiaryLine."""
        store = DiaryStore(tmp_path)
        line = DiaryLine(ts=datetime.now(), text="Test")
        store.add(line)

        result = store.all()
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], DiaryLine)

    def test_get_returns_none_if_not_found(self, tmp_path):
        """get(id) returns None if not present."""
        store = DiaryStore(tmp_path)
        assert store.get("nonexistent") is None

    def test_get_finds_by_id(self, tmp_path):
        """get(id) returns the line if present."""
        store = DiaryStore(tmp_path)
        line = DiaryLine(id="target", ts=datetime.now(), text="Target line")
        store.add(line)

        result = store.get("target")
        assert result is not None
        assert result.text == "Target line"
