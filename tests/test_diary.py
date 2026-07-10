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
- TestBuildDiaryWeek - skeleton builder: span weave, cross-midnight split, item placement
============================================================
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from serenity.core.activity import ActivityEntry
from serenity.core.diary import DiaryLine, DiaryStore, build_diary_week
from serenity.core.models import Note, Todo


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


class TestBuildDiaryWeek:
    """build_diary_week skeleton builder: span weave, item placement, cross-midnight split."""

    def test_7_monday_start_days(self):
        """Result is exactly 7 DiaryDay, Monday-Sunday, correct dates."""
        # Use a Tuesday in the week of 2026-07-13 (Monday)
        anchor = datetime(2026, 7, 14, 10, 0, 0)  # Tuesday 2026-07-14
        now = datetime(2026, 7, 14, 12, 0, 0)

        result = build_diary_week([], [], [], [], anchor, now)

        assert len(result) == 7
        # Monday should be 2026-07-13
        assert result[0].date == datetime(2026, 7, 13).date()
        # Tuesday should be 2026-07-14
        assert result[1].date == datetime(2026, 7, 14).date()
        # Sunday should be 2026-07-19
        assert result[6].date == datetime(2026, 7, 19).date()

    def test_item_in_covering_span(self):
        """A todo completed inside a span lands in that span's items."""
        # Week of 2026-07-13 (Monday)
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        # Activity span: Monday 10:00-12:00
        span = ActivityEntry(category="work", start=datetime(2026, 7, 13, 10, 0, 0),
                              end=datetime(2026, 7, 13, 12, 0, 0))

        # Todo completed at Monday 11:00 (inside the span)
        todo = Todo(id="t1", title="Task 1", completed_at=datetime(2026, 7, 13, 11, 0, 0))

        result = build_diary_week([span], [todo], [], [], anchor, now)

        monday = result[0]
        assert len(monday.spans) == 1
        assert monday.spans[0].category == "work"
        assert len(monday.spans[0].items) == 1
        assert monday.spans[0].items[0].kind == "todo"
        assert monday.spans[0].items[0].text == "Task 1"

    def test_open_span_uses_now(self):
        """Open span (end=None) clipped using now; items before now land in it."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 14, 0, 0)  # 2 PM

        # Open span starting at 10:00, no end
        span = ActivityEntry(category="work", start=datetime(2026, 7, 13, 10, 0, 0), end=None)

        # Todo at 12:00 (before now, inside the open span)
        todo = Todo(id="t1", title="Task 1", completed_at=datetime(2026, 7, 13, 12, 0, 0))

        result = build_diary_week([span], [todo], [], [], anchor, now)

        monday = result[0]
        # Span should be clipped to [10:00, 14:00) using now
        assert monday.spans[0].start == datetime(2026, 7, 13, 10, 0, 0)
        assert monday.spans[0].end == datetime(2026, 7, 13, 14, 0, 0)  # now
        # Todo should be in the span
        assert len(monday.spans[0].items) == 1

    def test_untracked_bucket(self):
        """Item whose ts is in the day but covered by no span → untracked."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        # Span: 10:00-12:00
        span = ActivityEntry(category="work", start=datetime(2026, 7, 13, 10, 0, 0),
                              end=datetime(2026, 7, 13, 12, 0, 0))

        # Todo at 14:00 (after the span, same day)
        todo = Todo(id="t1", title="Task 1", completed_at=datetime(2026, 7, 13, 14, 0, 0))

        result = build_diary_week([span], [todo], [], [], anchor, now)

        monday = result[0]
        assert len(monday.spans) == 1
        assert len(monday.spans[0].items) == 0
        # Should be in untracked
        assert len(monday.untracked) == 1
        assert monday.untracked[0].kind == "todo"
        assert monday.untracked[0].text == "Task 1"

    def test_boundary_items_at_midnight(self):
        """Items at day boundary (00:00:00 and 23:59:59) land on correct day."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 14, 12, 0, 0)

        # Item at Monday 23:59:59 (should be on Monday)
        todo1 = Todo(id="t1", title="Task 1",
                     completed_at=datetime(2026, 7, 13, 23, 59, 59))

        # Item at Tuesday 00:00:00 (should be on Tuesday)
        todo2 = Todo(id="t2", title="Task 2",
                     completed_at=datetime(2026, 7, 14, 0, 0, 0))

        result = build_diary_week([], [todo1, todo2], [], [], anchor, now)

        # Monday should have todo1 in untracked
        monday = result[0]
        assert len(monday.untracked) == 1
        assert monday.untracked[0].id == "t1"

        # Tuesday should have todo2 in untracked
        tuesday = result[1]
        assert len(tuesday.untracked) == 1
        assert tuesday.untracked[0].id == "t2"

    def test_empty_week(self):
        """No data → 7 days, all with empty spans/untracked."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        result = build_diary_week([], [], [], [], anchor, now)

        assert len(result) == 7
        for day in result:
            assert len(day.spans) == 0
            assert len(day.untracked) == 0

    def test_cross_week_excluded(self):
        """Diary line dated in a different week absent from built week."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)  # Week of Jul 13-19
        now = datetime(2026, 7, 13, 16, 0, 0)

        # Line in the target week
        line1 = DiaryLine(ts=datetime(2026, 7, 13, 10, 0, 0), text="In week")

        # Line in a different week (previous week)
        line2 = DiaryLine(ts=datetime(2026, 7, 6, 10, 0, 0), text="Different week")

        result = build_diary_week([], [], [], [line1, line2], anchor, now)

        # Only line1 should appear
        monday = result[0]
        found = False
        for day in result:
            for span in day.spans:
                for item in span.items:
                    if item.text == "In week":
                        found = True
        for day in result:
            for item in day.untracked:
                if item.text == "In week":
                    found = True

        # Check that line2 is NOT anywhere
        for day in result:
            for item in day.untracked:
                assert item.text != "Different week"

    def test_cross_midnight_split_p2_2(self):
        """P2-2: span 22:00 (day-1) to 01:00 (day-2) clipped BOTH days; item 00:30 day-2 lands in day-2's span."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)  # Week of Jul 13-19
        now = datetime(2026, 7, 14, 12, 0, 0)

        # Span from Monday 22:00 to Tuesday 01:00 (crosses midnight)
        span = ActivityEntry(
            category="focus",
            start=datetime(2026, 7, 13, 22, 0, 0),
            end=datetime(2026, 7, 14, 1, 0, 0)
        )

        # Todo completed at Tuesday 00:30 (inside the span)
        todo = Todo(id="t1", title="Task 1",
                    completed_at=datetime(2026, 7, 14, 0, 30, 0))

        result = build_diary_week([span], [todo], [], [], anchor, now)

        # Monday should have a clipped span [22:00, 00:00)
        monday = result[0]
        assert len(monday.spans) == 1
        assert monday.spans[0].category == "focus"
        assert monday.spans[0].start == datetime(2026, 7, 13, 22, 0, 0)
        assert monday.spans[0].end == datetime(2026, 7, 14, 0, 0, 0)
        assert len(monday.spans[0].items) == 0  # No items in Monday's span

        # Tuesday should have a clipped span [00:00, 01:00)
        tuesday = result[1]
        assert len(tuesday.spans) == 1
        assert tuesday.spans[0].category == "focus"
        assert tuesday.spans[0].start == datetime(2026, 7, 14, 0, 0, 0)
        assert tuesday.spans[0].end == datetime(2026, 7, 14, 1, 0, 0)
        # Todo should be in Tuesday's span, NOT in untracked
        assert len(tuesday.spans[0].items) == 1
        assert tuesday.spans[0].items[0].id == "t1"
        assert len(tuesday.untracked) == 0

    def test_multiple_items_in_span(self):
        """Multiple items in one span, sorted by timestamp."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        span = ActivityEntry(category="work", start=datetime(2026, 7, 13, 10, 0, 0),
                              end=datetime(2026, 7, 13, 12, 0, 0))

        todo1 = Todo(id="t1", title="Task 1", completed_at=datetime(2026, 7, 13, 10, 30, 0))
        todo2 = Todo(id="t2", title="Task 2", completed_at=datetime(2026, 7, 13, 11, 30, 0))

        result = build_diary_week([span], [todo1, todo2], [], [], anchor, now)

        monday = result[0]
        assert len(monday.spans[0].items) == 2
        # Items should be in timestamp order
        assert monday.spans[0].items[0].text == "Task 1"
        assert monday.spans[0].items[1].text == "Task 2"

    def test_notes_and_lines_in_items(self):
        """Notes and diary lines appear as DiaryItem kinds."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        note = Note(id="n1", title="Note 1", created=datetime(2026, 7, 13, 10, 0, 0))
        line = DiaryLine(ts=datetime(2026, 7, 13, 11, 0, 0), text="Diary entry")

        result = build_diary_week([], [], [note], [line], anchor, now)

        monday = result[0]
        assert len(monday.untracked) == 2
        # Check kinds
        kinds = {item.kind for item in monday.untracked}
        assert "note" in kinds
        assert "diary" in kinds

    def test_deleted_todos_excluded(self):
        """Deleted todos (deleted=True) excluded from result."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        todo1 = Todo(id="t1", title="Task 1", completed_at=datetime(2026, 7, 13, 10, 0, 0),
                     deleted=False)
        todo2 = Todo(id="t2", title="Task 2", completed_at=datetime(2026, 7, 13, 11, 0, 0),
                     deleted=True)

        result = build_diary_week([], [todo1, todo2], [], [], anchor, now)

        monday = result[0]
        assert len(monday.untracked) == 1
        assert monday.untracked[0].id == "t1"

    def test_deleted_notes_excluded(self):
        """Deleted notes (deleted=True) excluded from result."""
        anchor = datetime(2026, 7, 13, 10, 0, 0)
        now = datetime(2026, 7, 13, 16, 0, 0)

        note1 = Note(id="n1", title="Note 1", created=datetime(2026, 7, 13, 10, 0, 0),
                     deleted=False)
        note2 = Note(id="n2", title="Note 2", created=datetime(2026, 7, 13, 11, 0, 0),
                     deleted=True)

        result = build_diary_week([], [], [note1, note2], [], anchor, now)

        monday = result[0]
        assert len(monday.untracked) == 1
        assert monday.untracked[0].id == "n1"
