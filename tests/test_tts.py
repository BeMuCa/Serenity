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
- TestChooseEngine - preferred -> piper -> sapi -> noop fallback ladder
- TestMakeEngine - degrades to a working engine, no exceptions, no-op speaks safely
============================================================
"""

from serenity.core import tts
from serenity.core.tts import (
    NOOP,
    PIPER,
    SAPI,
    NoopEngine,
    choose_engine,
    clean_for_speech,
    make_engine,
    pick_voice,
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

    def test_falls_to_piper_then_sapi(self):
        # preferred missing -> next in ladder that is installed
        assert choose_engine("piper", [SAPI, NOOP]) == SAPI

    def test_falls_to_noop_when_nothing_real(self):
        assert choose_engine(PIPER, [NOOP]) == NOOP

    def test_unknown_preferred_uses_ladder(self):
        assert choose_engine("bogus", [PIPER, NOOP]) == PIPER
        assert choose_engine("bogus", [NOOP]) == NOOP


class _FakeSettings:
    """Minimal stand-in: make_engine reads attributes, not a real Settings."""
    tts_engine = "piper"
    tts_voice_de = "de_DE-kerstin-low"
    tts_voice_en = "en_US-amy-medium"
    tts_rate = 1.0
    tts_volume = 1.0
    voices_dir = "/nonexistent/voices"     # forces piper unavailable -> stub


class TestMakeEngine:
    def test_degrades_without_raising(self):
        # No Piper voices on disk here, not Windows -> must land on a usable engine.
        eng = make_engine(_FakeSettings())
        assert eng is not None
        assert eng.available is True            # NoopEngine is always available

    def test_noop_speak_is_silent_and_safe(self):
        eng = NoopEngine()
        # Must never raise even with odd input.
        eng.speak("anything at all", "de")
        eng.speak("", "en")
        eng.stop()

    def test_available_engines_lists_noop_last(self):
        names = tts.available_engines("/nonexistent/voices")
        assert names[-1] == NOOP
