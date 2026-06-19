"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the cloned-voice registry ("drop a clip, pick the language").
Role:    Guards core.voice_clones: clone ids are stable + language-tagged, the registry
         copies reference clips into app-data, persists/reloads metadata, lists clones
         per language, and removes them (and their copied clips). Headless, no audio.

Test classes:
- TestCloneIds - slug + voice-id derivation, is_clone_voice
- TestCloneRegistry - add (copy clip) / persist / reload / for_lang / get / remove
============================================================
"""

import pytest

from serenity.core.voice_clones import (
    CloneRegistry,
    VoiceClone,
    clone_slug,
    clone_voice_id,
    is_clone_voice,
)


def _clip(tmp_path, name="ref.wav"):
    p = tmp_path / name
    p.write_bytes(b"RIFFfakeWAVE")
    return p


class TestCloneIds:
    def test_slug_is_filesystem_safe(self):
        assert clone_slug("Berk") == "berk"
        assert clone_slug("My Mum!") == "my_mum"
        assert clone_slug("  Anna-Lena  ") == "anna_lena"
        assert clone_slug("") == ""

    def test_voice_id_is_language_tagged(self):
        assert clone_voice_id("Berk", "de") == "clone:berk_de"
        assert clone_voice_id("Berk", "en") == "clone:berk_en"

    def test_same_name_different_lang_distinct(self):
        assert clone_voice_id("Mum", "de") != clone_voice_id("Mum", "en")

    def test_is_clone_voice(self):
        assert is_clone_voice("clone:berk_de")
        assert not is_clone_voice("af_heart")
        assert not is_clone_voice("")
        assert not is_clone_voice("de_DE-kerstin-low")


class TestCloneRegistry:
    def test_empty_registry(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        assert reg.all() == []
        assert reg.for_lang("de") == []

    def test_add_copies_clip_and_persists(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        clone = reg.add("Berk", "de", _clip(tmp_path))
        assert clone.voice_id == "clone:berk_de"
        assert clone.lang == "de"
        assert clone.exists()
        # The clip was copied into the registry's own clones dir (not left in place).
        assert clone.clip != str(tmp_path / "ref.wav")
        assert reg.index_path.exists()

    def test_reload_from_disk(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        reg.add("Mum", "en", _clip(tmp_path))
        # A fresh registry over the same dir sees the persisted clone.
        reloaded = CloneRegistry(tmp_path)
        clone = reloaded.get("clone:mum_en")
        assert clone is not None and clone.name == "Mum" and clone.lang == "en"

    def test_lang_normalized(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        clone = reg.add("Anna", "de-DE", _clip(tmp_path))
        assert clone.lang == "de"
        assert clone.voice_id == "clone:anna_de"

    def test_for_lang_filters(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        reg.add("Berk", "de", _clip(tmp_path, "a.wav"))
        reg.add("Sam", "en", _clip(tmp_path, "b.wav"))
        de = reg.for_lang("de")
        en = reg.for_lang("en")
        assert [c.name for c in de] == ["Berk"]
        assert [c.name for c in en] == ["Sam"]

    def test_readd_replaces(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        reg.add("Berk", "de", _clip(tmp_path, "old.wav"))
        reg.add("Berk", "de", _clip(tmp_path, "new.wav"))
        # Same name + language -> single clone (replaced, not duplicated).
        assert len(reg.for_lang("de")) == 1

    def test_add_missing_clip_raises(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        with pytest.raises(FileNotFoundError):
            reg.add("Ghost", "en", tmp_path / "nope.wav")

    def test_remove_deletes_clip(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        clone = reg.add("Berk", "de", _clip(tmp_path))
        clip_path = clone.clip
        from pathlib import Path
        assert Path(clip_path).exists()
        assert reg.remove("clone:berk_de") is True
        assert not Path(clip_path).exists()
        assert reg.get("clone:berk_de") is None
        # Persisted away too.
        assert CloneRegistry(tmp_path).get("clone:berk_de") is None

    def test_remove_unknown_is_false(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        assert reg.remove("clone:nobody_en") is False

    def test_label_names_language(self):
        c = VoiceClone("clone:berk_de", "Berk", "de", "/x.wav")
        assert "Berk" in c.label() and "German" in c.label()
        c2 = VoiceClone("clone:sam_en", "Sam", "en", "/x.wav")
        assert "English" in c2.label()

    def test_missing_clip_reported(self, tmp_path):
        # A clone whose clip vanished must report exists() False (picker shows a warning).
        c = VoiceClone("clone:x_de", "X", "de", str(tmp_path / "gone.wav"))
        assert c.exists() is False

    def test_corrupt_index_is_ignored(self, tmp_path):
        reg = CloneRegistry(tmp_path)
        reg.dir.mkdir(parents=True, exist_ok=True)
        reg.index_path.write_text("{not valid json", encoding="utf-8")
        # Loading a corrupt index degrades to an empty registry, never raises.
        assert CloneRegistry(tmp_path).all() == []
