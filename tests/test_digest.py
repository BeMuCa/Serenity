"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Headless unit tests for the AI weekly digest (core.digest.generate_digest).
Role:    Guards Job 6: Serenity's short spoken weekly comment built from a REAL
         core.weekly_board.WeeklyBoard, via the pluggable core.llm.LLMEngine seam. Asserts
         that with a deterministic StubLLM the digest is the stub's text over the real board
         fact sheet, that it DEGRADES to the board's deterministic hint when no engine /
         an unavailable engine is wired, and that the spoken output honours Serenity's voice
         rules (no emojis, single hyphen). No llama-cpp / no model file - StubLLM only.

Test classes:
- TestGenerateDigest - StubLLM path (real board data reaches the prompt), degrade-to-hint
  for None / unavailable / empty-reply / raising engines, and the voice rules
- TestBoardFacts - the fact sheet carries the real board numbers handed to the LLM
============================================================
"""

from datetime import datetime, timedelta

from serenity.core import digest as digest_mod
from serenity.core.activity import ActivityEntry
from serenity.core.digest import board_facts, generate_digest
from serenity.core.llm import StubLLM
from serenity.core.weekly_board import build_board

# A Friday "now" (mirrors test_weekly_board): this-week = Mon 2026-06-15 ..
NOW = datetime(2026, 6, 19, 17, 30)
THIS_MON = datetime(2026, 6, 15, 9, 0)
LAST_MON = datetime(2026, 6, 8, 9, 0)


def hrs(n):
    return timedelta(hours=n)


def _busy_board():
    """A non-trivial board: Coding dominant + rising, plus completed todos."""
    entries = [
        ActivityEntry("Coding", THIS_MON, THIS_MON + hrs(5)),
        ActivityEntry("Meeting", THIS_MON, THIS_MON + hrs(1)),
        ActivityEntry("Coding", LAST_MON, LAST_MON + hrs(1)),
    ]
    return build_board(entries, NOW, completed_this_week=3)


class _UnavailableLLM:
    """A wired-but-unavailable engine - generate() must never be called by the digest."""

    name = "down"
    available = False

    def generate(self, prompt, system=None, max_tokens=256):  # pragma: no cover
        raise AssertionError("generate() must not be called when available is False")


class _EmptyLLM:
    """An available engine that returns nothing usable - digest must fall back to the hint."""

    name = "empty"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        return "   "


class _RaisingLLM:
    """An available engine whose generate() raises - digest must not propagate, falls back."""

    name = "boom"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        raise RuntimeError("inference failed")


class _DirtyLLM:
    """An available engine that VIOLATES the voice rules (emoji + em-dash + en-dash).

    A real model (Qwen3) routinely does this despite the system instruction, so the digest
    must sanitize the reply rather than trust the prompt."""

    name = "dirty"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        return "Great week \U0001f389 - Coding was strong — keep going – nicely \U0001f600"


class _VarSelLLM:
    """An available engine that emits an emoji WITH a U+FE0F variation selector.

    A real model often writes 'check-mark' as the base glyph U+2705 (cat So) followed by the
    emoji variation selector U+FE0F (cat Mn). Stripping only So leaves an orphan, invisible,
    non-spoken FE0F - so the mascot's TTS / board text must drop the Mn selector too."""

    name = "varsel"
    available = True

    def generate(self, prompt, system=None, max_tokens=256):
        return "Coding was strong ✅️ keep it up"


class TestGenerateDigest:
    def test_uses_stub_llm_over_real_board_data(self):
        board = _busy_board()
        out = generate_digest(board, StubLLM())
        # The digest is EXACTLY the stub's text for the digest prompt: the real board fact
        # sheet as the user prompt, under the digest system instruction, at the digest budget.
        expected = StubLLM().generate(
            board_facts(board),
            system=digest_mod._DIGEST_SYSTEM,
            max_tokens=digest_mod._DIGEST_MAX_TOKENS,
        )
        assert out == expected
        assert "stub-llm:" in out
        # Real board numbers flow through the stub echo (Coding is the top activity).
        assert "Coding" in out

    def test_stub_digest_is_deterministic(self):
        board = _busy_board()
        assert generate_digest(board, StubLLM()) == generate_digest(board, StubLLM())

    def test_degrades_to_hint_when_llm_is_none(self):
        board = _busy_board()
        out = generate_digest(board, None)
        # No engine -> the board's own deterministic hint(s), never a stub echo.
        assert "stub-llm:" not in out
        assert out
        assert any(h in out for h in board.hints)

    def test_degrades_to_hint_when_llm_unavailable(self):
        board = _busy_board()
        out = generate_digest(board, _UnavailableLLM())
        assert "stub-llm:" not in out
        assert any(h in out for h in board.hints)

    def test_degrades_to_hint_on_empty_reply(self):
        board = _busy_board()
        out = generate_digest(board, _EmptyLLM())
        assert out
        assert any(h in out for h in board.hints)

    def test_degrades_to_hint_when_engine_raises(self):
        board = _busy_board()
        out = generate_digest(board, _RaisingLLM())
        assert out
        assert any(h in out for h in board.hints)

    def test_empty_week_still_has_a_comment(self):
        # An empty week with no hints must still yield a non-empty, encouraging fallback.
        board = build_board([], NOW)
        out = generate_digest(board, None)
        assert out.strip()

    def test_empty_week_with_stub_llm(self):
        board = build_board([], NOW)
        out = generate_digest(board, StubLLM())
        assert "stub-llm:" in out

    def test_voice_rules_no_emoji_single_hyphen(self):
        # Both paths (LLM + fallback) must stay plain-text / single-hyphen for the mascot.
        for llm in (None, StubLLM()):
            out = generate_digest(_busy_board(), llm)
            assert "—" not in out and "–" not in out
            assert not any(ord(ch) > 0x2190 for ch in out)  # no arrows / emoji range

    def test_sanitizes_dirty_model_reply(self):
        # A model that emits emoji + em/en dashes must be cleaned before the mascot speaks it:
        # no emoji glyphs, no dash variants, only single hyphens, and still non-empty.
        out = generate_digest(_busy_board(), _DirtyLLM())
        assert out and "stub-llm:" not in out
        assert "—" not in out and "–" not in out          # dashes folded to " - "
        assert "\U0001f389" not in out and "\U0001f600" not in out  # emoji stripped
        assert not any(ord(ch) > 0x2190 for ch in out)     # no arrows / emoji range at all
        assert "Coding" in out                              # real content survived

    def test_strips_orphan_emoji_variation_selector(self):
        # A model that writes an emoji as base-glyph + U+FE0F (cat Mn) must have BOTH dropped:
        # stripping only the So base glyph leaves an invisible, non-spoken orphan selector,
        # which _sanitize's docstring already promises to remove.
        out = generate_digest(_busy_board(), _VarSelLLM())
        assert out and "stub-llm:" not in out
        assert "✅" not in out                          # base check-mark glyph stripped
        assert "️" not in out                          # orphan variation selector gone
        assert not any(ord(ch) > 0x2190 for ch in out)     # no emoji-range codepoint at all
        assert "Coding" in out                              # real content survived


class TestBoardFacts:
    def test_carries_top_category_and_completed_count(self):
        facts = board_facts(_busy_board())
        assert "Coding" in facts
        assert "Todos completed this week: 3" in facts

    def test_empty_week_says_no_time_tracked(self):
        facts = board_facts(build_board([], NOW))
        assert "No activity time was tracked" in facts
