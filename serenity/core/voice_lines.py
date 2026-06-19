"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Load Serenity's predefined speech lines and pick one per event/language.
Role:    The mascot's speech bubble asks this for what to say on each app event
         (todo done, timer due, capture routed, ...). Deterministic, on-device,
         no LLM. Mirrors the selection logic from serenity-voice-lines.html.

Functions:
- load_lines(path=None) -> dict - parse the shipped voice_lines.json
- VoiceLines.say(event, lang, **slots) -> str - random variant, EN fallback, slots filled
============================================================
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from . import paths


def load_lines(path: Optional[Path] = None) -> dict:
    p = path or paths.voice_lines_path()
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


class VoiceLines:
    """Picks an in-character line for an event in the active language.

    Selection (per serenity-voice-lines.html):
      1. look up the event,
      2. choose the bucket for `lang` (de/en),
      3. pick a random variant, avoiding the immediately previous one,
      4. fill {slots},
      5. fall back to `en` if the requested bucket is missing/empty.
    """

    def __init__(self, data: Optional[dict] = None, rng: Optional[random.Random] = None) -> None:
        self._data = data if data is not None else load_lines()
        self._rng = rng or random.Random()
        self._last: dict[str, int] = {}

    def events(self) -> list[str]:
        return list(self._data.keys())

    def _bucket(self, event: str, lang: str) -> tuple[list[str], str]:
        entry = self._data.get(event)
        if not entry:
            return [], lang
        arr = entry.get(lang)
        if arr:
            return arr, lang
        return entry.get("en", []), "en"

    def say(self, event: str, lang: str = "en", **slots) -> str:
        arr, real_lang = self._bucket(event, lang)
        if not arr:
            return ""
        if len(arr) == 1:
            idx = 0
        else:
            key = event + real_lang
            prev = self._last.get(key)
            choices = [i for i in range(len(arr)) if i != prev]
            idx = self._rng.choice(choices)
            self._last[key] = idx
        text = arr[idx]
        return self._fill(text, slots)

    @staticmethod
    def _fill(text: str, slots: dict) -> str:
        out = text
        for name, value in slots.items():
            out = out.replace("{" + name + "}", str(value))
        return out.strip()
