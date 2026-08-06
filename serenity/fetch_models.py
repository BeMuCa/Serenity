"""
============================================================
Author:  Berk
Created: 2026-08-06
Purpose: CLI that downloads Serenity's user-placed models (LLM GGUF + Piper voices)
         into %APPDATA%/Serenity (or ~/.config/serenity) - `python -m serenity.fetch_models`.
Role:    The one-command first-run setup step. A thin argv/printing shell over
         core.model_fetch (which holds the registry and does the atomic downloads);
         never imported by the app itself, so nothing heavy is added at runtime.

Functions:
- _human(n) - byte count as a short KB/MB/GB string for the progress line
- _tty() - whether stdout is a real terminal (False in the windowed frozen exe)
- _say(line, err) - print (stdout/stderr), or append to <config>/fetch-models.log
- _progress(asset, got, total) - overwriting line on a TTY, one line per 10% otherwise
- main(argv, opener) - parse args, fetch, report a per-asset summary; 0 ok / 1 failed
============================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen

from .core import paths
from .core.llm import MODELS_SUBDIR
from .core.model_fetch import DEFAULT_KEYS, ASSETS, FetchError, assets_for, fetch_all, keys


LOG_NAME = "fetch-models.log"


def _tty() -> bool:
    """A windowed PyInstaller exe has sys.stdout None - isatty() there would crash."""
    return sys.stdout is not None and bool(getattr(sys.stdout, "isatty", None)) \
        and sys.stdout.isatty()


def _say(line: str, err: bool = False) -> None:
    """Emit one line (errors on stderr, as a CLI should). print() is a silent no-op when the
    process has no such stream (the windowed exe the installer launches), so fall back to a
    log file the user can actually read."""
    stream = sys.stderr if err else sys.stdout
    if stream is not None:
        print(line, file=stream)
        return
    try:
        with open(paths.config_dir() / LOG_NAME, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _human(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


_printed: dict[str, int] = {}


def _progress(asset, got: int, total: int) -> None:
    """One overwriting line per file on a TTY; every 10% on its own line otherwise, so a
    piped install log stays a handful of lines instead of one per MB chunk."""
    tty = _tty()
    pct = int(100 * got / total) if total else 100
    bucket = pct if tty else pct - pct % 10
    done = got >= total
    if not done and _printed.get(asset.filename) == bucket:
        return
    _printed[asset.filename] = bucket
    line = f"  {asset.filename}: {pct:3d}%  ({_human(got)} / {_human(total)})"
    if tty and not done:
        print(line, end="\r")
    else:
        _say(line)


def main(argv: Optional[list[str]] = None, opener: Callable = urlopen) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m serenity.fetch_models",
        description="Download the model files Serenity does not bundle. Re-running is safe: "
                    "files already complete on disk are skipped without a network call.")
    ap.add_argument("keys", nargs="*", default=list(DEFAULT_KEYS),
                    help=f"assets to fetch (default: {' '.join(DEFAULT_KEYS)}); "
                         f"choose from: {', '.join(keys())}, all")
    ap.add_argument("--list", action="store_true", help="list the assets and exit")
    ap.add_argument("--models-dir", type=Path, default=None,
                    help="override the GGUF destination (default <config>/models)")
    ap.add_argument("--voices-dir", type=Path, default=None,
                    help="override the Piper voice destination (default <config>/voices)")
    args = ap.parse_args(argv)

    if args.list:
        for a in ASSETS:
            _say(f"{a.key:11} {a.filename:32} {_human(a.size):>8}  -> <config>/{a.dest}")
        return 0

    models_dir = args.models_dir or paths.config_dir() / MODELS_SUBDIR
    voices_dir = args.voices_dir or paths.voices_dir()
    try:
        wanted = assets_for(args.keys)
    except KeyError as exc:
        _say(f"error: {exc}", err=True)
        return 1

    _say(f"Fetching {len(wanted)} file(s), {_human(sum(a.size for a in wanted))} total")
    _say(f"  models -> {models_dir}")
    _say(f"  voices -> {voices_dir}")
    try:
        results = fetch_all(args.keys, models_dir, voices_dir, opener, _progress)
    except FetchError as exc:
        _say(f"error: {exc}", err=True)
        return 1
    for r in results:
        _say(f"  [{'skip' if r.status == 'present' else ' ok '}] {r.path}")
    _say("Done. Serenity picks these up on its next start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
