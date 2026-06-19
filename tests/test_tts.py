"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for the pure TTS logic (text cleanup, voice + engine selection).
Role:    Guards the framework-free parts of core.tts so they pass headless with no
         Piper / pyttsx3 / audio device present: speech cleanup strips markdown and
         expands "-" pauses, voice picks by language, the engine fallback ladder
         always lands on a safe stub, and make_engine never raises.

Test classes:
- TestCleanForSpeech - markdown / quote / arrow / dash cleanup
- TestPickVoice - de vs en voice selection
- TestChooseEngine - preferred -> kokoro -> piper -> sapi -> noop fallback ladder
- TestMakeEngine - degrades to a working engine, no exceptions, no-op speaks safely
- TestKokoroVoices - the bundled Kokoro voice catalog + English subset + lang code
- TestPerLanguageSelection - per-language engine/voice; German never uses Kokoro
- TestKokoroEngineFallback - KokoroEngine degrades to unavailable, speaks safely
============================================================
"""

from serenity.core import tts
from serenity.core.tts import (
    KOKORO,
    NOOP,
    PIPER,
    SAPI,
    KokoroEngine,
    NoopEngine,
    choose_engine,
    clean_for_speech,
    engine_for_lang,
    is_german,
    kokoro_english_voices,
    kokoro_lang,
    kokoro_voices,
    make_engine,
    pick_voice,
    voice_for_lang,
)


class TestCleanForSpeech:
    def test_empty(self):
        assert clean_for_speech("") == ""
        assert clean_for_speech("   ") == ""

    def test_strips_markdown_emphasis(self):
        assert clean_for_speech("**bold** and *italic* and `code`") == "bold and italic and code"

    def test_strips_quotes_around_titles(self):
        # Serenity wraps todo titles in quotes; spoken, they add nothing.
        out = clean_for_speech('Todo "Call dentist" saved.')
        assert '"' not in out
        assert "Call dentist" in out

    def test_dash_becomes_pause(self):
        # Her single-hyphen pause must not be read as "minus" / "dash".
        out = clean_for_speech("Done - saved.")
        assert "-" not in out
        assert "Done" in out and "saved" in out

    def test_arrow_becomes_pause(self):
        out = clean_for_speech('"Call mum" -> tomorrow, 9am')
        assert "->" not in out
        assert "Call mum" in out and "tomorrow" in out

    def test_link_keeps_text_only(self):
        assert clean_for_speech("see [the vault](file:///x)") == "see the vault"

    def test_heading_marker_dropped(self):
        assert clean_for_speech("# Weekly review") == "Weekly review"

    def test_collapses_whitespace(self):
        assert clean_for_speech("a\n  b\t c") == "a b c"


class TestPickVoice:
    def test_de_picks_de_voice(self):
        assert pick_voice("de", "de_voice", "en_voice") == "de_voice"

    def test_en_picks_en_voice(self):
        assert pick_voice("en", "de_voice", "en_voice") == "en_voice"

    def test_locale_prefix_de(self):
        assert pick_voice("de-DE", "de_voice", "en_voice") == "de_voice"

    def test_unknown_lang_falls_to_en(self):
        assert pick_voice("fr", "de_voice", "en_voice") == "en_voice"

    def test_empty_lang_falls_to_en(self):
        assert pick_voice("", "de_voice", "en_voice") == "en_voice"


class TestChooseEngine:
    def test_preferred_when_installed(self):
        assert choose_engine(PIPER, [PIPER, SAPI, NOOP]) == PIPER
        assert choose_engine(SAPI, [PIPER, SAPI, NOOP]) == SAPI
        assert choose_engine(KOKORO, [KOKORO, PIPER, NOOP]) == KOKORO

    def test_falls_to_kokoro_then_piper_then_sapi(self):
        # preferred missing -> next in ladder (kokoro -> piper -> sapi) that is installed
        assert choose_engine("bogus", [KOKORO, PIPER, SAPI, NOOP]) == KOKORO
        assert choose_engine("piper", [SAPI, NOOP]) == SAPI

    def test_falls_to_noop_when_nothing_real(self):
        assert choose_engine(PIPER, [NOOP]) == NOOP

    def test_unknown_preferred_uses_ladder(self):
        assert choose_engine("bogus", [PIPER, NOOP]) == PIPER
        assert choose_engine("bogus", [NOOP]) == NOOP


class _FakeSettings:
    """Minimal stand-in: make_engine reads attributes, not a real Settings."""
    tts_engine = "piper"
    tts_engine_en = "kokoro"
    tts_engine_de = "piper"
    tts_voice_de = "de_DE-kerstin-low"
    tts_voice_en = "en_US-amy-medium"
    tts_voice_kokoro = "af_heart"
    tts_rate = 1.0
    tts_volume = 1.0
    voices_dir = "/nonexistent/voices"     # forces every real engine unavailable -> stub


class TestMakeEngine:
    def test_degrades_without_raising(self):
        # No voices on disk here, not Windows -> must land on a usable engine.
        eng = make_engine(_FakeSettings(), "en")
        assert eng is not None
        assert eng.available is True            # NoopEngine is always available

    def test_degrades_for_both_languages(self):
        eng_de = make_engine(_FakeSettings(), "de")
        eng_en = make_engine(_FakeSettings(), "en")
        assert eng_de.available is True and eng_en.available is True

    def test_default_lang_is_english(self):
        # make_engine(settings) with no lang must not raise (defaults to English).
        assert make_engine(_FakeSettings()) is not None

    def test_noop_speak_is_silent_and_safe(self):
        eng = NoopEngine()
        # Must never raise even with odd input.
        eng.speak("anything at all", "de")
        eng.speak("", "en")
        eng.stop()

    def test_available_engines_lists_noop_last(self):
        names = tts.available_engines("/nonexistent/voices")
        assert names[-1] == NOOP

    def test_available_engines_omits_kokoro_without_model(self):
        # No kokoro model files at this path -> kokoro is not advertised.
        names = tts.available_engines("/nonexistent/voices")
        assert KOKORO not in names


class TestKokoroVoices:
    def test_catalog_has_known_voices(self):
        voices = kokoro_voices()
        # The flagship + common picks the task names must really be in the catalog.
        for v in ("af_heart", "af_bella", "af_nicole", "af_sarah", "bf_emma",
                  "am_michael", "bm_george"):
            assert v in voices

    def test_voices_are_sorted_and_unique(self):
        voices = kokoro_voices()
        assert voices == sorted(voices)
        assert len(voices) == len(set(voices))

    def test_prefix_filter(self):
        af = kokoro_voices("af")
        assert af and all(v.startswith("af") for v in af)
        assert "af_heart" in af
        assert "am_adam" not in af

    def test_english_subset_is_us_or_gb_only(self):
        en = kokoro_english_voices()
        assert en
        # Every surfaced English voice starts with a (American) or b (British).
        assert all(v[:1] in ("a", "b") for v in en)

    def test_lang_code_maps_us_vs_gb(self):
        assert kokoro_lang("af_heart") == "en-us"
        assert kokoro_lang("am_michael") == "en-us"
        assert kokoro_lang("bf_emma") == "en-gb"
        assert kokoro_lang("bm_george") == "en-gb"


class TestPerLanguageSelection:
    def test_is_german(self):
        assert is_german("de") and is_german("de-DE") and is_german("DE")
        assert not is_german("en") and not is_german("") and not is_german("fr")

    def test_engine_for_lang_english_uses_kokoro(self):
        assert engine_for_lang(_FakeSettings(), "en") == KOKORO

    def test_engine_for_lang_german_uses_piper(self):
        assert engine_for_lang(_FakeSettings(), "de") == PIPER

    def test_german_never_uses_kokoro(self):
        # Even if a (legacy/hand-edited) German setting asks for kokoro, it degrades.
        class S(_FakeSettings):
            tts_engine_de = "kokoro"
        assert engine_for_lang(S(), "de") == PIPER

    def test_engine_for_lang_falls_back_to_global_default(self):
        # No per-language fields set -> the legacy global tts_engine is used.
        class S:
            tts_engine = "sapi"
        assert engine_for_lang(S(), "en") == "sapi"
        assert engine_for_lang(S(), "de") == "sapi"

    def test_voice_for_lang_english_kokoro(self):
        assert voice_for_lang(_FakeSettings(), "en") == "af_heart"

    def test_voice_for_lang_english_piper(self):
        class S(_FakeSettings):
            tts_engine_en = "piper"
        assert voice_for_lang(S(), "en") == "en_US-amy-medium"

    def test_voice_for_lang_german_is_piper_voice(self):
        assert voice_for_lang(_FakeSettings(), "de") == "de_DE-kerstin-low"

    def test_make_engine_german_never_kokoro(self):
        # German must not land on Kokoro even if Kokoro is the only real engine present.
        from serenity.core import tts as _tts

        class S(_FakeSettings):
            tts_engine_de = "kokoro"

        original = _tts.available_engines
        _tts.available_engines = lambda *a, **k: [KOKORO, NOOP]
        try:
            eng = make_engine(S(), "de")
        finally:
            _tts.available_engines = original
        assert eng.name != KOKORO        # degraded away from Kokoro for German


class TestKokoroEngineFallback:
    def test_unavailable_without_model_files(self):
        # No model/voices on disk -> engine reports unavailable, never raises.
        eng = KokoroEngine("/nonexistent/voices", "af_heart")
        assert eng.available is False

    def test_speak_is_safe_when_unavailable(self):
        eng = KokoroEngine("/nonexistent/voices", "af_heart")
        # Must never raise even though there is no model behind it.
        eng.speak("Hello there", "en")
        eng.speak("", "en")
        eng.stop()

    def test_synth_wav_returns_none_when_unavailable(self, tmp_path):
        eng = KokoroEngine("/nonexistent/voices", "af_heart")
        assert eng.synth_wav("Hello", "en", tmp_path / "out.wav") is None

    def test_synth_wav_returns_none_on_empty_text(self, tmp_path):
        eng = KokoroEngine("/nonexistent/voices", "af_heart")
        assert eng.synth_wav("   ", "en", tmp_path / "out.wav") is None
