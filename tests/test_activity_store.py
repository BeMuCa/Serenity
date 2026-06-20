"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Tests for the vault-persisted activity log + weekly-board auto-open marker.
Role:    core.activity_store wraps core.activity.ActivityLog and persists it to
         <vault>/activity.json so tracked time survives restarts and feeds the Weekly
         Board. These tests pin start/stop persistence, reload round-trips (incl. a still
         running span), and the last-board-open marker.

Test classes:
- TestActivityStorePersistence - start/stop, reload round-trip, running span survives
- TestBoardMarker - the Friday auto-open timestamp persists
============================================================
"""

from datetime import datetime

from serenity.core.activity_store import ActivityStore


class TestActivityStorePersistence:
    def test_start_persists_and_reloads(self, tmp_path):
        store = ActivityStore(tmp_path)
        store.start("Working", when=datetime(2026, 6, 20, 9, 0))
        store.stop(when=datetime(2026, 6, 20, 10, 0))
        # a fresh store over the same vault sees the closed span
        reloaded = ActivityStore(tmp_path)
        entries = reloaded.log().entries()
        assert len(entries) == 1
        assert entries[0].category == "Working"
        assert entries[0].seconds() == 3600

    def test_running_span_survives_reload(self, tmp_path):
        store = ActivityStore(tmp_path)
        store.start("Coding", when=datetime(2026, 6, 20, 9, 0))
        reloaded = ActivityStore(tmp_path)
        running = reloaded.running()
        assert running is not None
        assert running.category == "Coding"
        assert running.end is None

    def test_starting_a_new_span_closes_the_open_one(self, tmp_path):
        store = ActivityStore(tmp_path)
        store.start("Working", when=datetime(2026, 6, 20, 9, 0))
        store.start("Meeting", when=datetime(2026, 6, 20, 9, 30))
        entries = store.log().entries()
        assert len(entries) == 2
        assert entries[0].end == datetime(2026, 6, 20, 9, 30)
        assert store.running().category == "Meeting"

    def test_empty_vault_is_clean(self, tmp_path):
        store = ActivityStore(tmp_path)
        assert store.log().entries() == []
        assert store.running() is None
        assert store.last_board_open() is None

    def test_corrupt_file_degrades_to_empty(self, tmp_path):
        (tmp_path / "activity.json").write_text("{not json", encoding="utf-8")
        store = ActivityStore(tmp_path)
        assert store.log().entries() == []
        assert store.running() is None
        assert store.last_board_open() is None

    def test_row_with_bad_start_is_skipped(self, tmp_path):
        (tmp_path / "activity.json").write_text(
            '{"version": 1, "entries": ['
            '{"category": "Bad", "start": "not-a-date", "end": null},'
            '{"category": "Good", "start": "2026-06-20T09:00:00", '
            '"end": "2026-06-20T10:00:00"}]}',
            encoding="utf-8")
        store = ActivityStore(tmp_path)
        cats = [e.category for e in store.log().entries()]
        assert cats == ["Good"]


class TestBoardMarker:
    def test_marker_persists(self, tmp_path):
        store = ActivityStore(tmp_path)
        when = datetime(2026, 6, 19, 17, 30)
        store.set_last_board_open(when)
        assert ActivityStore(tmp_path).last_board_open() == when
