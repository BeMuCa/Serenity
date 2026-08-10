"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: Regression tests for the P1 data-safety gaps in the JSON stores:
         (1) every save() must be atomic (no leftover .tmp, complete content) and
         (2) a corrupt JSON file on load must be renamed to a .corrupt-<ts> sibling
         (recoverable) before the store degrades to its empty/default state.
Role:    Headless unit tests over serenity.core.{todo_store,activity_store,settings,
         voice_clones}, guarding the atomic-write + corrupt-backup safety nets that
         close the largest family of P1s in notes/5_Interaction_Flows.md.

Test classes:
- TestAtomicSaves - each store's save() leaves no .tmp + the file round-trips intact
- TestCorruptBackup - a corrupted todos/activity/settings file is backed up on load,
  then the live file degrades to empty/default instead of being silently lost
============================================================
"""
import json
from datetime import datetime

import pytest

from serenity.core import paths
from serenity.core.activity_store import ActivityStore
from serenity.core.models import Todo
from serenity.core.settings import Settings
from serenity.core.todo_store import TodoStore
from serenity.core.voice_clones import CloneRegistry


@pytest.fixture
def arm_torn_write(monkeypatch):
    """Return arm(): once called, the next raw write_text writes partial bytes then
    raises (simulates a torn write / power-loss mid-save). Armed AFTER a healthy file
    is seeded, so the test can prove an atomic save() (write tmp -> os.replace) leaves
    the prior-good target untouched, where a plain write_text would have truncated it."""
    real_write_text = paths.Path.write_text

    def boom(self, text, *a, **kw):
        real_write_text(self, text[: len(text) // 2], *a, **kw)  # half-written tmp
        raise OSError("simulated power-loss mid-write")

    def arm():
        monkeypatch.setattr(paths.Path, "write_text", boom)

    return arm


def _tmp_siblings(path):
    """The .tmp sibling atomic_write_text uses, listed if present."""
    return list(path.parent.glob(path.name + ".tmp"))


def _corrupt_siblings(path):
    return list(path.parent.glob(path.name + ".corrupt-*"))


class TestAtomicSaves:
    def test_todo_save_atomic_no_tmp_complete(self, tmp_path):
        store = TodoStore(tmp_path)
        store.add(Todo(title="alpha"))
        store.add(Todo(title="beta"))
        # No stray temp file left behind by the atomic swap.
        assert _tmp_siblings(store.path) == []
        # File is complete + parseable (a torn write would not round-trip).
        data = json.loads(store.path.read_text(encoding="utf-8"))
        assert {t["title"] for t in data} == {"alpha", "beta"}

    def test_activity_save_atomic_no_tmp_complete(self, tmp_path):
        store = ActivityStore(tmp_path)
        store.start("Deep Work")
        assert _tmp_siblings(store.path) == []
        data = json.loads(store.path.read_text(encoding="utf-8"))
        assert data["entries"][0]["category"] == "Deep Work"

    def test_settings_save_atomic_no_tmp_complete(self, tmp_path):
        p = tmp_path / "settings.json"
        s = Settings.load(p)
        s.accent = "#123456"
        s.save()
        assert _tmp_siblings(p) == []
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["accent"] == "#123456"

    def test_clone_registry_save_atomic_no_tmp_complete(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        clip = tmp_path / "ref.wav"
        clip.write_bytes(b"RIFF....")
        reg.add("Berk", "de", clip)
        assert _tmp_siblings(reg.index_path) == []
        data = json.loads(reg.index_path.read_text(encoding="utf-8"))
        assert data["clones"][0]["name"] == "Berk"

    def test_todo_torn_write_preserves_original(self, tmp_path, arm_torn_write):
        store = TodoStore(tmp_path)
        store.add(Todo(title="alpha"))  # healthy file on disk
        store._todos.append(Todo(title="beta"))
        arm_torn_write()
        with pytest.raises(OSError):
            store.save()  # tmp boom -> no os.replace; original must survive
        assert _tmp_siblings(store.path) == []  # half-written tmp cleaned up
        # Prior-good data intact (NOT truncated to half a doc).
        assert {t.title for t in TodoStore(tmp_path).all()} == {"alpha"}

    def test_activity_torn_write_preserves_original(self, tmp_path, arm_torn_write):
        store = ActivityStore(tmp_path)
        store.start("Deep Work", datetime(2026, 6, 24, 9, 0))  # healthy file
        store.log().start("Reading", datetime(2026, 6, 24, 10, 0))
        arm_torn_write()
        with pytest.raises(OSError):
            store.save()
        assert _tmp_siblings(store.path) == []
        cats = [e.category for e in ActivityStore(tmp_path).log().entries()]
        assert cats == ["Deep Work"]

    def test_settings_torn_write_preserves_original(self, tmp_path, arm_torn_write):
        p = tmp_path / "settings.json"
        s = Settings.load(p)
        s.accent = "#abcdef"
        s.save()  # healthy file
        s.accent = "#000000"
        arm_torn_write()
        with pytest.raises(OSError):
            s.save()
        assert _tmp_siblings(p) == []
        assert Settings.load(p).accent == "#abcdef"

    def test_clone_torn_write_preserves_original(self, tmp_path, arm_torn_write):
        reg = CloneRegistry(tmp_path)
        clip = tmp_path / "ref.wav"
        clip.write_bytes(b"RIFF....")
        reg.add("Berk", "de", clip)  # healthy file
        reg._clones["clone:mum_en"] = reg.get("clone:berk_de")  # pending extra entry
        arm_torn_write()
        with pytest.raises(OSError):
            reg.save()
        assert _tmp_siblings(reg.index_path) == []
        # Original catalog intact: only the persisted "Berk" survives.
        assert [c.name for c in CloneRegistry(tmp_path).all()] == ["Berk"]


class TestCorruptBackup:
    def test_todo_corrupt_backed_up_then_degrades(self, tmp_path):
        path = tmp_path / "todos.json"
        path.write_text("{ this is not valid json", encoding="utf-8")
        store = TodoStore(tmp_path)
        # Degraded to empty in memory ...
        assert store.all() == []
        # ... but the user's data was preserved as a recoverable sibling.
        backups = _corrupt_siblings(path)
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{ this is not valid json"
        # The live file no longer holds the corrupt bytes (it was renamed away),
        # so the next save() can't clobber the only copy.
        assert not path.exists() or path.read_text(encoding="utf-8") != "{ this is not valid json"

    def test_activity_corrupt_backed_up_then_degrades(self, tmp_path):
        path = tmp_path / "activity.json"
        path.write_text("not json at all", encoding="utf-8")
        store = ActivityStore(tmp_path)
        assert store.log().entries() == []
        backups = _corrupt_siblings(path)
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "not json at all"
        assert not path.exists() or path.read_text(encoding="utf-8") != "not json at all"

    def test_settings_corrupt_backed_up_then_degrades(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{ broken", encoding="utf-8")
        s = Settings.load(path)
        # Degraded to defaults (accent is the dataclass default).
        assert s.accent == "#a78bfa"
        backups = _corrupt_siblings(path)
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{ broken"
        assert not path.exists() or path.read_text(encoding="utf-8") != "{ broken"

    def test_valid_file_not_backed_up(self, tmp_path):
        # A well-formed file must NOT be renamed away.
        store = TodoStore(tmp_path)
        store.add(Todo(title="keep me"))
        TodoStore(tmp_path)  # reload a healthy file
        assert _corrupt_siblings(store.path) == []
