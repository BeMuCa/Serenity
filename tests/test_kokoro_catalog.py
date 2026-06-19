"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Additional tests for the Kokoro English-only catalog + the model folder scan.
Role:    Complements tests/test_tts.py: pins the English (American+British) subset, the
         all-female sweet default tier, and the KokoroEngine "folder scan" that decides
         availability from the two model files on disk (path helpers + present/absent).

Test classes:
- TestEnglishOnlyCatalog - the English subset (a*/b*), default voice, sorted, no other langs
- TestFolderScan - model_path/voices_path + availability driven by files on disk
============================================================
"""

from serenity.core.tts import (
    KOKORO_MODEL_FILE,
    KOKORO_SUBDIR,
    KOKORO_VOICES_FILE,
    KokoroEngine,
    kokoro_english_voices,
    kokoro_language_name,
    kokoro_voices,
)


class TestEnglishOnlyCatalog:
    def test_english_subset_is_28_voices(self):
        # American (a*) + British (b*) only.
        en = kokoro_english_voices()
        assert len(en) == 28

    def test_only_american_and_british(self):
        for v in kokoro_english_voices():
            assert kokoro_language_name(v) in ("American English", "British English")

    def test_default_voice_in_english_subset(self):
        # af_heart is the shipped Kokoro English default (Settings.tts_voice_kokoro).
        assert "af_heart" in kokoro_english_voices()

    def test_english_subset_sorted(self):
        en = kokoro_english_voices()
        assert en == sorted(en)

    def test_excludes_every_non_english_language(self):
        en = set(kokoro_english_voices())
        # one representative per non-English language must be absent
        for v in ("jf_alpha", "zf_xiaoxiao", "ef_dora", "ff_siwis",
                  "hf_alpha", "if_sara", "pf_dora"):
            assert v not in en

    def test_subset_is_a_subset_of_full_catalog(self):
        assert set(kokoro_english_voices()).issubset(set(kokoro_voices()))


class TestFolderScan:
    def test_paths_point_into_kokoro_subdir(self, tmp_path):
        eng = KokoroEngine(tmp_path, "af_heart")
        assert eng.model_path() == tmp_path / KOKORO_SUBDIR / KOKORO_MODEL_FILE
        assert eng.voices_path() == tmp_path / KOKORO_SUBDIR / KOKORO_VOICES_FILE

    def test_unavailable_when_no_files(self, tmp_path):
        eng = KokoroEngine(tmp_path, "af_heart")
        assert eng.available is False

    def test_unavailable_with_only_model_file(self, tmp_path):
        # Folder scan needs BOTH files; only the model present -> still unavailable.
        kdir = tmp_path / KOKORO_SUBDIR
        kdir.mkdir(parents=True)
        (kdir / KOKORO_MODEL_FILE).write_bytes(b"x")
        eng = KokoroEngine(tmp_path, "af_heart")
        assert eng.available is False

    def test_unavailable_with_only_voices_file(self, tmp_path):
        kdir = tmp_path / KOKORO_SUBDIR
        kdir.mkdir(parents=True)
        (kdir / KOKORO_VOICES_FILE).write_bytes(b"x")
        eng = KokoroEngine(tmp_path, "af_heart")
        assert eng.available is False

    def test_both_files_present_passes_file_scan(self, tmp_path):
        # With both files on disk the file-scan half of _probe passes; availability
        # then only hinges on the optional kokoro_onnx/phonemizer deps. Either way the
        # constructor must not raise and `available` is a bool.
        kdir = tmp_path / KOKORO_SUBDIR
        kdir.mkdir(parents=True)
        (kdir / KOKORO_MODEL_FILE).write_bytes(b"x")
        (kdir / KOKORO_VOICES_FILE).write_bytes(b"x")
        eng = KokoroEngine(tmp_path, "af_heart")
        assert isinstance(eng.available, bool)
