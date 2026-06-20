"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The AI weekly digest - Serenity's short, friendly spoken comment on the board.
Role:    Job 6 (break-time / Friday Wochen-Board, spec sec 10). Turns the pure
         core.weekly_board.WeeklyBoard (ranked categories, week-over-week deltas, completed
         count, top category) into ONE short, encouraging paragraph in Serenity's voice for
         the mascot to read aloud. The text generation is the pluggable core.llm.LLMEngine
         seam: tests inject a deterministic StubLLM, the app may inject a LlamaCppLLM, and
         when no engine is wired / it is unavailable / it returns nothing usable this
         DEGRADES to the board's existing deterministic hint(s) - so there is always a
         comment and never a dead end. No Qt, no DB, no heavy deps here: the board is built
         elsewhere and the LLM is injected, so this stays unit-tested headless. Mirrors
         core.phase2_stubs.CaptureRouter's "ask the LLM, validate, else fall back to the
         deterministic baseline" shape. Lazy by construction: nothing runs until a caller
         asks for the digest (the view calls it only when the board is opened, never at idle).

Functions:
- generate_digest(board, llm=None, notes=None) -> str - the spoken weekly comment, in
  Serenity's voice (LLM-authored when available, else the deterministic board hint(s))
- board_facts(board) -> str - the plain-text fact sheet handed to the LLM (also the seam
  tests assert the real board data reaches the prompt)
============================================================
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Optional

from .weekly_board import WeeklyBoard

if TYPE_CHECKING:
    from .llm import LLMEngine
    from .models import Note


# The system instruction handed to the LLM. Constrains it to Serenity's voice: a SHORT,
# friendly, encouraging weekly comment the mascot reads aloud, so plain text only - no
# emojis and a single "-" never an em-dash (CLAUDE.md user-string rules).
_DIGEST_SYSTEM = (
    "You are Serenity, a warm and encouraging personal secretary. Read the user's weekly "
    "activity summary and reply with a short, friendly comment of two or three sentences "
    "in your own voice. Be specific to the numbers you are given and end on an encouraging "
    "note. Plain text only, spoken aloud - no emojis, no lists, no headings, and use a "
    "single hyphen, never a dash."
)

# Coarse token budget for the reply: a few spoken sentences, nothing more. Keeps a real
# model concise and bounds the StubLLM echo too.
_DIGEST_MAX_TOKENS = 120


def _fmt_hms(seconds: int) -> str:
    """Whole seconds -> a compact 'Xh Ym' / 'Ym' label (mirrors the board view)."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _trend_phrase(delta: int) -> str:
    """A plain week-over-week phrase for a delta (no glyphs, spoken-friendly)."""
    if delta > 0:
        return f"up {_fmt_hms(delta)} vs last week"
    if delta < 0:
        return f"down {_fmt_hms(-delta)} vs last week"
    return "level with last week"


def board_facts(board: WeeklyBoard) -> str:
    """A compact plain-text fact sheet of the board, the user-prompt body for the LLM.

    Lists total tracked time and its week-over-week trend, the completed-todo count, and
    each ranked category with its time and delta. Single-hyphen, no emojis, so the model's
    input already matches Serenity's voice rules. Kept its own function so a test can assert
    the REAL board data (top category, completed count, deltas) reaches the prompt."""
    lines: list[str] = []
    lines.append(
        f"Total time tracked this week: {_fmt_hms(board.total_seconds)} "
        f"({_trend_phrase(board.total_delta)})."
    )
    lines.append(f"Todos completed this week: {board.completed}.")
    if board.categories:
        lines.append(f"Top activity: {board.top_category}.")
        lines.append("Time per activity:")
        for c in board.categories:
            lines.append(
                f"- {c.category}: {_fmt_hms(c.seconds)} ({_trend_phrase(c.delta)})"
            )
    else:
        lines.append("No activity time was tracked this week.")
    return "\n".join(lines)


def _fallback_comment(board: WeeklyBoard) -> str:
    """The always-available deterministic comment: the board's own hint(s), joined.

    This is the degrade path for every LLM failure (no engine / unavailable / empty reply),
    so the Friday review always has something to say. build_board already produced these
    plain, single-hyphen hints; we join them into one spoken line, falling back to a neutral
    encouragement when the board produced none (e.g. an empty, hint-less week)."""
    hints = [h for h in (board.hints or []) if h and h.strip()]
    if hints:
        return " ".join(h.strip() for h in hints)
    return "Nothing to report yet - keep tracking your activities and you will see trends here."


# Dash glyphs a model may emit that violate the single-hyphen house style. Each is folded
# to " - " (the spoken pause), mirroring tts.py's collapse and phase2_stubs.py's rule.
_DASHES = ("—", "–", "―", "‒", "−")  # em / en / horiz-bar / fig / minus


def _sanitize(text: str) -> str:
    """Force a raw LLM reply onto Serenity's voice rules: no emojis, single hyphen, no dash.

    The _DIGEST_SYSTEM instruction ASKS the model for plain text, but a real model can and
    does emit em-dashes and emoji anyway - and the digest is read aloud by the mascot and is
    a locked UX decision (no emojis, single "-" never a dash). So we ENFORCE it here rather
    than hope: fold every dash variant to " - ", then drop emoji / symbol / pictograph
    codepoints (Unicode category So / Sk and the variation selectors), and tidy whitespace.
    Plain ASCII text and normal punctuation pass through untouched."""
    if not text:
        return ""
    for d in _DASHES:
        text = text.replace(d, " - ")
    out_chars: list[str] = []
    for ch in text:
        # Keep ordinary whitespace as-is.
        if ch in "\t\n\r ":
            out_chars.append(ch)
            continue
        cat = unicodedata.category(ch)
        # Drop emoji / pictographs / symbol-modifiers (So, Sk) and variation selectors (Mn
        # high range / Cf), which is where emoji and their skin-tone joiners live. Letters,
        # digits, normal punctuation (P*), currency/math symbols (Sc, Sm) are kept.
        if cat in ("So", "Sk", "Cf", "Mn"):
            continue
        out_chars.append(ch)
    cleaned = "".join(out_chars)
    # Collapse any runs of spaces introduced by removals / dash folding (but keep newlines).
    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    return "\n".join(line for line in lines).strip()


def generate_digest(
    board: WeeklyBoard,
    llm: "Optional[LLMEngine]" = None,
    notes: "Optional[list[Note]]" = None,
) -> str:
    """Serenity's short weekly comment on `board`, LLM-authored when one is wired.

    Asks the injected LLMEngine to author a few friendly sentences from the board fact sheet
    (board_facts); on ANY failure - no engine, engine unavailable, inference error, or an
    empty reply - DEGRADES to the board's deterministic hint(s) (_fallback_comment), so the
    mascot always has a comment to read. Never raises into the caller.

    `notes` is accepted for forward-compatibility (a future digest may weave in note themes
    from the semantic index) but is not required today; the comment is grounded in the board
    so it stays meaningful with no notes. The reply is run through _sanitize before returning,
    so the voice rules (no emojis, single hyphen, no dash) are ENFORCED on the model's text -
    _DIGEST_SYSTEM only asks for them, a real model can violate them. The fallback hints are
    already house-style, so they pass through sanitisation unchanged."""
    # Always-correct baseline + the fallback for every LLM failure path below.
    fallback = _fallback_comment(board)
    if llm is None or not getattr(llm, "available", False):
        return fallback
    try:
        reply = llm.generate(
            board_facts(board), system=_DIGEST_SYSTEM, max_tokens=_DIGEST_MAX_TOKENS
        )
    except Exception:
        return fallback
    reply = _sanitize((reply or "").strip())
    return reply if reply else fallback
