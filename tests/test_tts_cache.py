"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the TTS render cache (key/hash, lookup, store, LRU prune).
Role:    Guards core.tts_cache so repeat lines replay instantly: the cache key is a
         stable sha256 over (engine, voice id, exact final text), get/put/has behave,
         and the size cap evicts least-recently-used renders. All headless, no audio.

Test classes:
- TestCacheKey - the key is stable, order-sensitive, and collision-resistant
- TestTtsCache - path_for / put / get / has round-trip + LRU prune + clear
============================================================
"""

from serenity.core.tts_cache import TtsCache, cache_key


def _write(path, n=1024):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * n)
    return path


class TestCacheKey:
    def test_is_stable(self):
        assert cache_key("kokoro", "af_heart", "Hello there.") == \
            cache_key("kokoro", "af_heart", "Hello there.")

    def test_is_64_hex_chars(self):
        k = cache_key("kokoro", "af_heart", "Hi")
        assert len(k) == 64 and all(c in "0123456789abcdef" for c in k)

    def test_differs_on_engine(self):
        assert cache_key("kokoro", "v", "t") != cache_key("piper", "v", "t")

    def test_differs_on_voice(self):
        assert cache_key("kokoro", "af_heart", "t") != cache_key("kokoro", "af_bella", "t")

    def test_differs_on_text(self):
        assert cache_key("kokoro", "v", "one") != cache_key("kokoro", "v", "two")

    def test_no_field_bleed(self):
        # Concatenation must not let field boundaries collide ("a"+"b" vs "ab").
        assert cache_key("a", "b", "c") != cache_key("ab", "", "c")

    def test_handles_empty_and_unicode(self):
        assert cache_key("", "", "") == cache_key("", "", "")
        assert cache_key("e", "v", "schoen, gruen") != cache_key("e", "v", "schon, grun")


class TestTtsCache:
    def test_miss_returns_none(self, tmp_path):
        c = TtsCache(tmp_path)
        assert c.get("kokoro", "af_heart", "Hi") is None
        assert c.has("kokoro", "af_heart", "Hi") is False

    def test_path_for_is_keyed(self, tmp_path):
        c = TtsCache(tmp_path)
        p = c.path_for("kokoro", "af_heart", "Hi")
        assert p.name == cache_key("kokoro", "af_heart", "Hi") + ".wav"
        assert p.parent.name == "cache"

    def test_put_then_get(self, tmp_path):
        c = TtsCache(tmp_path)
        src = _write(tmp_path / "render.wav")
        cached = c.put("kokoro", "af_heart", "Hello there.", src)
        assert cached is not None and cached.exists()
        assert c.has("kokoro", "af_heart", "Hello there.")
        hit = c.get("kokoro", "af_heart", "Hello there.")
        assert hit is not None and hit == cached

    def test_put_missing_source_returns_none(self, tmp_path):
        c = TtsCache(tmp_path)
        assert c.put("kokoro", "v", "t", tmp_path / "nope.wav") is None

    def test_put_empty_source_returns_none(self, tmp_path):
        c = TtsCache(tmp_path)
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")
        assert c.put("kokoro", "v", "t", empty) is None

    def test_distinct_voices_do_not_collide(self, tmp_path):
        c = TtsCache(tmp_path)
        c.put("kokoro", "af_heart", "Same words.", _write(tmp_path / "a.wav"))
        # A different voice for the same text is a cache miss until rendered.
        assert c.has("kokoro", "af_bella", "Same words.") is False

    def test_prune_evicts_lru(self, tmp_path):
        # Cap allows ~2 of the 1 KB files; the oldest must be evicted by prune().
        import os
        c = TtsCache(tmp_path, max_bytes=2200)
        # Lay down three cached renders directly with staggered mtimes (oldest = "one").
        for i, text in enumerate(["one", "two", "three"]):
            cached = c.path_for("kokoro", "v", text)
            _write(cached, n=1024)
            os.utime(cached, (1000 + i, 1000 + i))
        assert c.total_bytes() == 3072
        freed = c.prune()
        assert freed >= 1024
        assert c.total_bytes() <= 2200
        # The oldest ("one") should have been evicted; the newest ("three") kept.
        assert c.has("kokoro", "v", "three")
        assert not c.has("kokoro", "v", "one")

    def test_clear_removes_all(self, tmp_path):
        c = TtsCache(tmp_path)
        c.put("kokoro", "v", "t", _write(tmp_path / "x.wav"))
        assert c.total_bytes() > 0
        c.clear()
        assert c.total_bytes() == 0

    def test_get_touches_for_lru(self, tmp_path):
        # get() must bump mtime so a freshly-played line is treated as recently used.
        import os
        c = TtsCache(tmp_path)
        cached = c.put("kokoro", "v", "t", _write(tmp_path / "x.wav"))
        old = cached.stat().st_mtime
        os.utime(cached, (old - 1000, old - 1000))
        c.get("kokoro", "v", "t")
        assert cached.stat().st_mtime > old - 1000
