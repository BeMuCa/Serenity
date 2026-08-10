"""
============================================================
Author:  Berk
Created: 2026-08-06
Purpose: Download the model files Serenity never bundles (the LLM GGUF and the Piper
         voices) straight into the per-user model/voice dirs the app already reads.
Role:    Pure core (no Qt, no app state, nothing imported at runtime): the registry of
         downloadable assets + an atomic download helper behind an injectable opener
         seam, mirroring the repo's Protocol/stub pattern so tests never touch the
         network. Driven by the `python -m serenity.fetch_models` CLI.

Models / Functions:
- Asset - one downloadable file: key / url / filename / dest ("models"|"voices") / size
- ASSETS - the registry (Qwen3 GGUFs + the default Piper DE/EN voices, sizes verified)
- DEFAULT_KEYS - what a bare fetch grabs (the lead GGUF + both default voices)
- FetchError - a download that did not arrive intact (nothing is left behind)
- FetchResult - what happened to one asset: "present" | "downloaded" + its final path
- keys() - the selectable asset keys, in registry order
- assets_for(names) - registry rows for the requested keys ("all" -> everything)
- target_dir(asset, models_dir, voices_dir) - route an asset to its per-user dir
- fetch(asset, dest_dir, opener, on_progress) - atomic download; skip when already there
- fetch_all(names, models_dir, voices_dir, opener, on_progress) - fetch a whole key set
============================================================
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.request import urlopen

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Asset:
    """One downloadable file. `size` is the exact upstream byte count: it is the only
    integrity check (no hashes published per-file), and a mismatch fails the fetch."""

    key: str
    url: str
    filename: str
    dest: str          # "models" (GGUF) or "voices" (Piper .onnx + its .onnx.json)
    size: int


# Verified against the upstream HEAD responses on 2026-08-06 (status + content-length).
# The official Qwen/Qwen3-*-GGUF repos do NOT carry these filenames (404) - the unsloth
# mirrors do. Filenames match core.llm's DEFAULT_MODEL_FILE / QWEN3_0_6B_FILE and the
# Settings defaults tts_voice_de / tts_voice_en, so the app finds them with no config.
_HF = "https://huggingface.co"
_PIPER = f"{_HF}/rhasspy/piper-voices/resolve/main"
ASSETS: tuple[Asset, ...] = (
    Asset("llm", f"{_HF}/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf",
          "Qwen3-1.7B-Q4_K_M.gguf", "models", 1107409472),
    Asset("llm-small", f"{_HF}/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf",
          "Qwen3-0.6B-Q4_K_M.gguf", "models", 396705472),
    Asset("voice-de", f"{_PIPER}/de/de_DE/kerstin/low/de_DE-kerstin-low.onnx",
          "de_DE-kerstin-low.onnx", "voices", 63104526),
    Asset("voice-de", f"{_PIPER}/de/de_DE/kerstin/low/de_DE-kerstin-low.onnx.json",
          "de_DE-kerstin-low.onnx.json", "voices", 4158),
    Asset("voice-en", f"{_PIPER}/en/en_US/amy/medium/en_US-amy-medium.onnx",
          "en_US-amy-medium.onnx", "voices", 63201294),
    Asset("voice-en", f"{_PIPER}/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
          "en_US-amy-medium.onnx.json", "voices", 4882),
)

# The lead GGUF + both default voices. "llm-small" is the low-RAM swap, asked for by name.
DEFAULT_KEYS: tuple[str, ...] = ("llm", "voice-de", "voice-en")


class FetchError(RuntimeError):
    """A download did not arrive intact. The partial file is always removed first."""


@dataclass(frozen=True)
class FetchResult:
    asset: Asset
    path: Path
    status: str        # "present" (already complete on disk) or "downloaded"


def keys() -> list[str]:
    """The selectable keys, in registry order, without duplicates (voices have sidecars)."""
    out: list[str] = []
    for a in ASSETS:
        if a.key not in out:
            out.append(a.key)
    return out


def assets_for(names: Iterable[str]) -> list[Asset]:
    """Registry rows for `names`. "all" expands to every asset. Unknown key -> KeyError."""
    wanted = list(names)
    if "all" in wanted:
        return list(ASSETS)
    unknown = [n for n in wanted if n not in keys()]
    if unknown:
        raise KeyError(f"unknown asset key(s): {', '.join(unknown)}")
    return [a for a in ASSETS if a.key in wanted]


def target_dir(asset: Asset, models_dir: Path, voices_dir: Path) -> Path:
    return Path(models_dir) if asset.dest == "models" else Path(voices_dir)


def fetch(asset: Asset, dest_dir: Path, opener: Callable = urlopen,
          on_progress: Optional[Callable[[Asset, int, int], None]] = None) -> FetchResult:
    """Download `asset` into `dest_dir`, atomically and idempotently.

    Already-complete file (exact expected size) -> no network call at all. Anything else is
    streamed to a sibling `.part` and only then os.replace()d into place, so an interrupted
    run never leaves a half file that the app would try to load. A size mismatch removes the
    partial and raises FetchError (upstream re-published the file -> the registry is stale)."""
    dest_dir = Path(dest_dir)
    final = dest_dir / asset.filename
    if final.exists() and final.stat().st_size == asset.size:
        return FetchResult(asset, final, "present")
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    got = 0
    try:
        with opener(asset.url) as response, open(part, "wb") as out:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if on_progress is not None:
                    on_progress(asset, got, asset.size)
    except Exception as exc:                     # network / disk error: leave nothing behind
        part.unlink(missing_ok=True)
        raise FetchError(f"{asset.filename}: download failed ({exc})") from exc
    if got != asset.size:
        part.unlink(missing_ok=True)
        raise FetchError(f"{asset.filename}: expected {asset.size} bytes, got {got}")
    os.replace(part, final)
    return FetchResult(asset, final, "downloaded")


def fetch_all(names: Iterable[str], models_dir: Path, voices_dir: Path,
              opener: Callable = urlopen,
              on_progress: Optional[Callable[[Asset, int, int], None]] = None
              ) -> list[FetchResult]:
    """Fetch every asset behind `names`. Raises FetchError on the first failure - the
    results already returned by then are on disk and a re-run skips them."""
    return [fetch(a, target_dir(a, models_dir, voices_dir), opener, on_progress)
            for a in assets_for(names)]
