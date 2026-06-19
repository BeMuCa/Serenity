"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for the voice-line selector (lang pick, EN fallback, slots).
Role:    Guards what Serenity says: no emoji, single hyphen, slots filled, no
         immediate repeat, German falls back to English when a bucket is empty.

Test classes:
- TestVoiceLineData - shipped JSON loads, style rules (no emoji / no em-dash)
- TestVoiceLineSelection - lang pick, slot fill, EN fallback, no repeat
============================================================
"""

import random

from serenity.core.voice_lines import VoiceLines, load_lines


class TestVoiceLineData:
    def test_loads_shipped_json(self):
        data = load_lines()
        assert "app_opened_greeting" in data
        assert data["app_opened_greeting"]["de"]
        assert data["app_opened_greeting"]["en"]

    def test_no_emoji_and_single_hyphen(self):
        data = load_lines()
        for event, buckets in data.items():
            for lang, lines in buckets.items():
                for line in lines:
                    assert "--" not in line, f"em-dash style in {event}/{lang}: {line}"
                    assert "—" not in line, f"em-dash char in {event}/{lang}"
                    # no emoji / pictographs (basic range check)
                    for ch in line:
                        assert ord(ch) < 0x2190 or ch in "„“”", (
                            f"non-text glyph in {event}/{lang}: {line!r}"
                        )


class TestVoiceLineSelection:
    def test_slot_fill(self):
        vl = VoiceLines(rng=random.Random(0))
        out = vl.say("voice_routed_todo", "en", title="Call dentist", date="tomorrow", time="9am")
        assert "Call dentist" in out
        assert "{title}" not in out

    def test_language_pick(self):
        data = {"ev": {"de": ["hallo {x}"], "en": ["hello {x}"]}}
        vl = VoiceLines(data=data)
        assert vl.say("ev", "de", x="welt") == "hallo welt"
        assert vl.say("ev", "en", x="world") == "hello world"

    def test_en_fallback_when_de_missing(self):
        data = {"ev": {"de": [], "en": ["only english"]}}
        vl = VoiceLines(data=data)
        assert vl.say("ev", "de") == "only english"

    def test_no_immediate_repeat(self):
        data = {"ev": {"en": ["a", "b", "c"]}}
        vl = VoiceLines(data=data, rng=random.Random(7))
        last = None
        for _ in range(30):
            cur = vl.say("ev", "en")
            if last is not None:
                assert cur != last
            last = cur

    def test_unknown_event_returns_empty(self):
        vl = VoiceLines(data={})
        assert vl.say("nope", "en") == ""
