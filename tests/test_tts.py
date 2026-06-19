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
    CHATTERBOX,
    KOKORO,
    NOOP,
    PIPER,
    SAPI,
    ChatterboxEngine,
    KokoroEngine,
    NoopEngine,
    cache_voice_id,
    choose_engine,
    clean_for_speech,
    engine_for_lang,
    fixed_voice_lines,
    is_german,
    kokoro_english_voices,
    kokoro_lang,
    kokoro_language_name,
    kokoro_voices,
    kokoro_voices_by_language,
    make_engine,
    pick_voice,
    prewarm,
    synth_cached,
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
    tts_clone_de = ""
    tts_clone_en = ""
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


class TestFullKokoroCatalog:
    def test_ships_all_54_voices(self):
        # Kokoro v1.0 ships 54 voices across nine language variants - surface them all.
        assert len(kokoro_voices()) == 54

    def test_catalog_has_non_english_voices(self):
        voices = set(kokoro_voices())
        # A representative voice from each non-English language must be present.
        for v in ("jf_alpha", "zf_xiaoxiao", "ef_dora", "ff_siwis",
                  "hf_alpha", "if_sara", "pf_dora", "am_santa"):
            assert v in voices

    def test_no_german_voice_exists(self):
        # Kokoro has NO German; no id should map to a German language.
        assert all(kokoro_language_name(v) != "German" for v in kokoro_voices())

    def test_grouped_by_language_covers_all(self):
        grouped = kokoro_voices_by_language()
        flat = [v for ids in grouped.values() for v in ids]
        assert sorted(flat) == kokoro_voices()
        assert "American English" in grouped and "British English" in grouped
        assert "Japanese" in grouped and "Mandarin Chinese" in grouped

    def test_grouped_first_groups_are_english(self):
        # English defaults stay sensible: English groups come first.
        names = list(kokoro_voices_by_language().keys())
        assert names[0] == "American English"
        assert names[1] == "British English"

    def test_lang_code_for_non_english(self):
        assert kokoro_lang("jf_alpha") == "ja"
        assert kokoro_lang("zf_xiaoxiao") == "cmn"
        assert kokoro_lang("ef_dora") == "es"
        assert kokoro_lang("ff_siwis") == "fr-fr"
        # English still maps as before.
        assert kokoro_lang("af_heart") == "en-us"
        assert kokoro_lang("bf_emma") == "en-gb"

    def test_english_subset_still_28(self):
        # The English subset is the American + British voices only.
        en = kokoro_english_voices()
        assert all(v[:1] in ("a", "b") for v in en)
        assert "af_heart" in en and "bm_george" in en
        assert "jf_alpha" not in en


class _CbSettings(_FakeSettings):
    """English + German both on Chatterbox, with per-language clone ids."""
    tts_engine_en = "chatterbox"
    tts_engine_de = "chatterbox"
    tts_clone_de = "clone:mum_de"
    tts_clone_en = "clone:berk_en"


class TestChatterboxSelection:
    def test_engine_for_lang_german_can_be_chatterbox(self):
        # German may now use Chatterbox (natural + cloneable), unlike Kokoro.
        assert engine_for_lang(_CbSettings(), "de") == CHATTERBOX

    def test_engine_for_lang_english_can_be_chatterbox(self):
        assert engine_for_lang(_CbSettings(), "en") == CHATTERBOX

    def test_german_kokoro_still_degrades_to_piper(self):
        class S(_FakeSettings):
            tts_engine_de = "kokoro"
        assert engine_for_lang(S(), "de") == PIPER

    def test_voice_for_lang_chatterbox_uses_clone(self):
        # When the engine is Chatterbox, the voice is the per-language clone id.
        assert voice_for_lang(_CbSettings(), "de") == "clone:mum_de"
        assert voice_for_lang(_CbSettings(), "en") == "clone:berk_en"

    def test_voice_for_lang_non_chatterbox_unchanged(self):
        # Kokoro English / Piper German still pick their own voice ids.
        assert voice_for_lang(_FakeSettings(), "en") == "af_heart"
        assert voice_for_lang(_FakeSettings(), "de") == "de_DE-kerstin-low"

    def test_choose_engine_ladder_includes_chatterbox(self):
        # preferred missing -> kokoro, then chatterbox, then piper, ...
        assert choose_engine("bogus", [CHATTERBOX, PIPER, NOOP]) == CHATTERBOX
        assert choose_engine("chatterbox", [CHATTERBOX, PIPER, NOOP]) == CHATTERBOX
        assert choose_engine("chatterbox", [PIPER, NOOP]) == PIPER

    def test_make_engine_falls_back_when_chatterbox_absent(self):
        # No torch/chatterbox here -> a Chatterbox request must degrade, never raise.
        eng = make_engine(_CbSettings(), "de")
        assert eng is not None and eng.available is True
        assert eng.name != CHATTERBOX            # degraded away (deps absent)

    def test_make_engine_chatterbox_when_only_installed(self):
        # When Chatterbox is the only real engine, German lands on it (not Kokoro).
        original = tts.available_engines
        tts.available_engines = lambda *a, **k: [CHATTERBOX, NOOP]
        try:
            eng = make_engine(_CbSettings(), "de")
        finally:
            tts.available_engines = original
        assert eng.name == CHATTERBOX


class TestChatterboxEngineFallback:
    def test_unavailable_without_torch(self):
        # No torch/chatterbox installed in the test env -> reports unavailable, no raise.
        eng = ChatterboxEngine("/nonexistent/voices", "clone:x_de")
        assert eng.available is False

    def test_speak_is_safe_when_unavailable(self):
        eng = ChatterboxEngine("/nonexistent/voices")
        eng.speak("Hallo, wie geht es dir?", "de")
        eng.speak("", "en")
        eng.stop()

    def test_synth_wav_returns_none_when_unavailable(self, tmp_path):
        eng = ChatterboxEngine("/nonexistent/voices", "clone:x_en")
        assert eng.synth_wav("Hello", "en", tmp_path / "out.wav") is None

    def test_synth_wav_returns_none_on_empty_text(self, tmp_path):
        eng = ChatterboxEngine("/nonexistent/voices")
        assert eng.synth_wav("   ", "de", tmp_path / "out.wav") is None

    def test_not_in_available_engines_without_deps(self):
        # torch/chatterbox absent -> chatterbox is not advertised.
        assert CHATTERBOX not in tts.available_engines("/nonexistent/voices")


class TestCacheVoiceId:
    def test_chatterbox_uses_clone_id(self):
        eng = ChatterboxEngine("/nonexistent/voices", "clone:berk_de")
        assert cache_voice_id(eng) == "clone:berk_de"

    def test_kokoro_uses_voice_en(self):
        eng = KokoroEngine("/nonexistent/voices", "af_heart")
        assert cache_voice_id(eng) == "af_heart"

    def test_noop_has_empty_voice_id(self):
        assert cache_voice_id(NoopEngine()) == ""


class TestFixedVoiceLines:
    def test_skips_slotted_lines(self):
        data = {
            "greet": {"en": ["Hello there.", "Hi - good to see you."]},
            "routed": {"en": ["Saved \"{title}\".", "Got it."]},
        }
        fixed = fixed_voice_lines(data, "en")
        assert "Hello there." in fixed
        assert "Got it." in fixed
        assert all("{" not in line for line in fixed)
        assert 'Saved "{title}".' not in fixed

    def test_dedupes_repeated_lines(self):
        data = {"a": {"en": ["Same line."]}, "b": {"en": ["Same line."]}}
        assert fixed_voice_lines(data, "en") == ["Same line."]

    def test_falls_back_to_en_bucket(self):
        # A missing German bucket falls back to the English lines for that event.
        data = {"greet": {"en": ["Only English here."]}}
        assert fixed_voice_lines(data, "de") == ["Only English here."]

    def test_real_catalog_has_fixed_lines(self):
        from serenity.core.voice_lines import load_lines
        fixed = fixed_voice_lines(load_lines(), "en")
        assert len(fixed) > 10
        assert all("{" not in line for line in fixed)


class _FakeCache:
    """In-memory stand-in for TtsCache: records put/get without touching disk."""
    def __init__(self):
        self.store = {}
        self.puts = []

    def get(self, engine, voice_id, text):
        return self.store.get((engine, voice_id, text))

    def has(self, engine, voice_id, text):
        return (engine, voice_id, text) in self.store

    def put(self, engine, voice_id, text, wav_path):
        self.puts.append((engine, voice_id, text))
        self.store[(engine, voice_id, text)] = wav_path
        return wav_path


class _FakeEngine:
    """A synth-capable engine that 'renders' by writing a stub WAV to out_path."""
    name = "fake"
    available = True
    voice_id = "fake_voice"

    def __init__(self):
        self.calls = []

    def synth_wav(self, text, lang, out_path):
        from pathlib import Path
        p = Path(out_path)
        p.write_bytes(b"RIFFfake")
        self.calls.append(text)
        return p


class TestSynthCachedAndPrewarm:
    def test_miss_then_hit(self, tmp_path):
        eng, cache = _FakeEngine(), _FakeCache()
        first = synth_cached(eng, cache, "Hello there.", "en")
        assert first is not None
        assert len(eng.calls) == 1            # synthesized once
        second = synth_cached(eng, cache, "Hello there.", "en")
        assert second is not None
        assert len(eng.calls) == 1            # served from cache, not re-synthesized

    def test_cleaned_text_is_the_cache_key(self, tmp_path):
        eng, cache = _FakeEngine(), _FakeCache()
        synth_cached(eng, cache, "Done - saved.", "en")
        # The cleaned spoken form ("Done... saved.") is what got cached.
        assert ("fake", "fake_voice", "Done... saved.") in cache.store

    def test_empty_text_returns_none(self):
        eng, cache = _FakeEngine(), _FakeCache()
        assert synth_cached(eng, cache, "   ", "en") is None
        assert eng.calls == []

    def test_no_cache_still_synthesizes(self, tmp_path):
        eng = _FakeEngine()
        out = synth_cached(eng, None, "No cache here.", "en")
        assert out is not None and len(eng.calls) == 1

    def test_prewarm_renders_fixed_lines(self, tmp_path):
        eng, cache = _FakeEngine(), _FakeCache()
        warmed = prewarm(eng, cache, ["One.", "Two.", "Three."], "en")
        assert warmed == 3
        assert len(eng.calls) == 3

    def test_prewarm_skips_already_cached(self, tmp_path):
        eng, cache = _FakeEngine(), _FakeCache()
        prewarm(eng, cache, ["One."], "en")
        eng.calls.clear()
        # Second pre-warm with the same line should not re-render it.
        warmed = prewarm(eng, cache, ["One.", "Two."], "en")
        assert warmed == 1 and eng.calls == ["Two."]

    def test_prewarm_honors_should_stop(self, tmp_path):
        eng, cache = _FakeEngine(), _FakeCache()
        # should_stop fires immediately -> nothing rendered.
        warmed = prewarm(eng, cache, ["A.", "B."], "en", should_stop=lambda: True)
        assert warmed == 0 and eng.calls == []

    def test_prewarm_noop_with_unavailable_engine(self):
        class Dead(_FakeEngine):
            available = False
        assert prewarm(Dead(), _FakeCache(), ["X."], "en") == 0

    def test_prewarm_noop_without_cache(self):
        assert prewarm(_FakeEngine(), None, ["X."], "en") == 0
