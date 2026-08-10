<div align="center">

<img src="current_Imgs/serenity_idle_1.webp" width="190" alt="Serenity" />

# Serenity

**A privacy-first desktop secretary with a soul.**

She lives in a docked sidebar, talks to you through speech bubbles, and runs entirely
on your machine - no cloud, no account, no tracking.

<img src="current_Imgs/serenity_work_1.webp" width="92" alt="working" />
<img src="current_Imgs/serenity_mission.webp" width="92" alt="coding" />
<img src="current_Imgs/serenity_nachdenklich.webp" width="92" alt="thinking" />
<img src="current_Imgs/serenity_happy.webp" width="92" alt="success" />
<img src="current_Imgs/serenity_chilling.webp" width="92" alt="break" />

![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-a78bfa)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)
![UI: PySide6](https://img.shields.io/badge/UI-PySide6-41cd52)
![Privacy: 100%25 local](https://img.shields.io/badge/privacy-100%25%20local-19e3ff)

</div>

## Meet Serenity

Serenity is not a to-do list with a face bolted on - the mascot *is* the interface.
Her speech bubble is the app's prompt layer: she greets you, confirms what she
captured, and asks follow-up questions in character. Click her to pick what you are
working on and she changes pose to match. She speaks German and English.

## Features

**A companion, not just chrome**
- Full-height, right-edge-docked, always-on-top sidebar; lives in the system tray.
- 14 hand-tuned animated poses across 10 states (idle, working, coding, meeting,
  planning, break, alert, thinking, success, error), picked at random so she never
  feels canned.
- Click the mascot to open the activity selector; her bubble reacts.
- Three window modes: Full, a compact always-on-top Mini-dock (Serenity + the single
  most-actionable todo), and Hidden-to-tray.

**Todos that understand you**
- Quick-add with natural-language dates and tags: `call Tom tomorrow 5pm #work`.
- Subtasks, per-todo timers, recurring rules, drag-to-reorder.
- Smart ranking - new todos sink to the bottom; a running timer or a nearing deadline
  floats up; finished ones move to Trash.
- A read-only dependency-graph tab: todos drawn as ready / in-progress / blocked nodes
  with their "blocks" edges.

**Notes that are just files**
- One Markdown file per note in your vault - the filesystem is the source of truth,
  so your notes outlive the app.
- Fast keyword search, color-coded cards, pin-to-top, recent-first, view-raw-.md.
- Quick-Note tags + a meeting-protocol template.

**Capture by voice or by typing**
- A mic with an intent-keyword cheatsheet.
- If a capture is missing a detail, Serenity asks for it in her bubble.
- A category-tag arsenal that starts small and learns the tags you use.
- Optional local voice output - Serenity can read her lines aloud (Kokoro for natural
  English, Piper for German, Chatterbox for cloned voices, or the Windows SAPI5
  baseline), fully on-device, off by default until you pick a voice. A render cache
  makes repeat lines instant.
- An ever-evolving voice: a built-in DE/EN catalog of in-character lines (random
  variant per event, never the same one twice in a row) is, when the local LLM is
  present, topped up with personalized, per-task one-liners - while you are on a break
  Serenity quietly authors a short, warm line for each of your top active todos, so the
  moment you start one she greets it by name. The lines regenerate every break and fall
  back to the catalog when no model is installed.

**Stay on track**
- A running-activity chip + an append-only time log.
- A Focus / Pomodoro strip (25/5) when you pick the Focus activity.
- A Weekly Performance Board tab (time per activity this week vs last, trend arrows,
  completed-todo count, plain optimization hints) that auto-opens Friday 17-18h.

**On-device AI that earns its keep** (each feature degrades gracefully when its
optional backend is absent - the app runs fully with NONE installed)
- "Meaning" (semantic) search over your notes, alongside literal "Text" search.
- Related-notes / note-linking - the nearest notes to the one you are reading.
- Near-duplicate / fragment detection with a safe, recoverable merge (the dropped note
  goes to Trash, never purged).
- Tag consolidation - fold spelling variants of a tag into one canonical name across
  the vault.
- Ask-Your-Vault - ask a question and get an answer grounded only in your own notes,
  with cited source notes, plus a warm-cache so repeat questions answer instantly.
- An AI weekly digest - a short friendly spoken comment on the Weekly Board.
- LLM-assisted capture routing - a small local model refines a typed/spoken capture,
  always validated against and merged onto the deterministic parser (the model never
  writes directly).
- On-device speech-to-text (Whisper) so a spoken capture flows into the same confirm +
  undo path as typed text.

**Yours, and private**
- 100% on-device. No network calls at runtime. Your vault is plain files you own.
- Every heavy backend is optional, lazy-loaded, and degrades to a built-in fallback -
  so a fresh base install is light at idle and still does something useful for every
  feature. Weights are never bundled: you place the LLM GGUF (and the Piper voices);
  e5, Whisper, Kokoro and Chatterbox each download their model once on first use into the
  per-user cache, then run offline.

## Status

The full feature set above is built and on `main`, covered by 635 headless tests. The
on-device AI backends (local LLM, Whisper, sqlite-vec, e5 embeddings) are exercised
through deterministic stubs in the suite; verifying the real backends, and building +
native-verifying the Windows `.exe`, are the remaining steps (both Windows-only). See
`notes/1_Planning.md` for the source-of-truth "what's next" and `notes/4_Packaging.md`
for the packaging steps.

## Quick start

Requires **Python 3.10+** (developed on 3.12).

```bash
# from the repo root
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

python -m serenity
```

Or install as a package (gives you a `serenity` command):

```bash
pip install -e .
serenity
```

On first launch Serenity creates the vault at `~/SerenityVault/`
(Windows: `C:\Users\<you>\SerenityVault\`). Change it in Settings -> General. Per-user
config/state lives in `%APPDATA%/Serenity` (Windows) or `~/.config/serenity`.

## Optional extras

The base install is intentionally light. Each AI / voice feature ships as an optional
extra (most also as a matching `requirements-*.txt` - see below); install only what you
want. With none installed, every feature degrades to a built-in fallback and the app still runs.

| Extra | Install | Adds | Degrades to |
|-------|---------|------|-------------|
| `voice` | `pip install "serenity[voice]"` | Kokoro (EN), Piper (DE), SAPI5 voice output | silent no-op |
| `clone` | `pip install "serenity[clone]"` | Chatterbox zero-shot voice cloning (heavy, PyTorch) | cloned-voice unavailable |
| `semantic` | `pip install "serenity[semantic]"` | e5 embeddings + sqlite-vec for "Meaning" search, related notes, dedup | keyword "Text" search / token methods |
| `llm` | `pip install "serenity[llm]"` | in-process llama-cpp GGUF for capture routing, RAG answers, the digest | deterministic parser / board hints / sources-only |
| `stt` | `pip install "serenity[stt]"` | faster-whisper on-device speech-to-text | STT seam reports unavailable |
| `power` | `pip install "serenity[power]"` | psutil AC-power probe for the break-time heavy-job guard | heavy jobs conservatively skipped |
| `dev` | `pip install "serenity[dev]"` | pytest | - |

Equivalently: `pip install -r requirements-voice.txt` - the `voice` / `semantic` / `llm` /
`stt` / `power` extras each also ship a matching `requirements-*.txt` (there is no
`requirements-clone.txt` or `requirements-dev.txt`: `clone` installs via the `[clone]`
extra only, and `dev` is just pytest).

Model weights are never bundled. You place the LLM GGUF (and the Piper voices, documented in
`docs/serenity-voices.md`) yourself; e5, Whisper, Kokoro and Chatterbox each download their
model once on first use into the per-user cache and then run offline.

## Installing & updating

**Today (any OS, incl. WSL):** install from source - see [Quick start](#quick-start) above
(`python -m venv` -> `pip install -r requirements.txt` -> `python -m serenity`), then add any
[optional extras](#optional-extras) for voice / AI.

**Windows (planned):** a signed one-click installer built with
[Inno Setup](https://jrsoftware.org/isinfo.php) from the PyInstaller `onedir` build
(`serenity.exe` + its `_internal/` folder, which must stay together). It installs per-user (no
admin prompt), adds a Start-menu shortcut, and registers an uninstaller. Until it ships, use the
from-source route.

### First-run setup
On first launch Serenity creates two locations and needs no configuration:
- **`~/SerenityVault/`** (Windows: `C:\Users\<you>\SerenityVault\`) - your notes (plain `.md`
  files, the source of truth), todos, and activity log. User-facing and safe to back up or sync.
  Change the location in **Settings -> General**.
- **`%APPDATA%/Serenity`** (Windows) or **`~/.config/serenity`** - app-managed state: settings,
  the search index / embeddings, and any downloaded models. Hidden plumbing.

To enable voice or on-device AI, install the matching [extra](#optional-extras) and put the model
files in place (the LLM GGUF + Piper voices; e5 / Whisper / Kokoro self-download on first use).
See what is Active in **Settings -> AI and voice**.

### Updating
Updates **never touch your data** - the vault and `%APPDATA%/Serenity` live outside the app
folder, so settings, notes, and models are preserved. An update only replaces the app itself.
- **Installer (Windows):** download and run the newer `Serenity-x.y.z-Setup.exe`; same app id, so
  it upgrades in place.
- **From source:** `git pull`, then re-run.

Your current version and a link to the latest release are under **Settings -> About**
(**Check for updates** opens the releases page - Serenity never checks on its own). On launch the
app safely evolves its on-device databases when needed (a `PRAGMA user_version` migration step),
and your `.md` notes always remain the source of truth.

## Verifying on Windows

WSL2 cannot show the tray, true always-on-top, or audio, so verify on Windows:

1. Install Python 3.12 from python.org (tick "Add to PATH").
2. In a fresh PowerShell, from the repo root:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m serenity
   ```
3. Confirm the sidebar docks to the right edge and stays on top; a tray icon appears and
   closing the dock hides it to the tray; the mascot animates and clicking her opens the
   activity bubbles; a todo like `call Tom tomorrow 5pm #work` parses the date and tag;
   Quick Note writes a real `.md` under `SerenityVault\notes\`; Autostart writes an
   `HKCU\...\Run` entry; a second launch reports "already running" and exits.

## Running the tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

`QT_QPA_PLATFORM=offscreen` lets the suite run on a machine without a display (CI / WSL).
635 tests pass; the AI backends are exercised through deterministic stubs.

## Packaging

The app ships as a Windows `.exe` via PyInstaller (`serenity.spec`, onedir / windowed,
pointed at the top-level `serenity_launch.py` runner). The build steps and a Windows-only
native-verification checklist live in `notes/4_Packaging.md`. The exe build + native
checks are Windows-only.

## Tech stack

Python 3.12, PySide6 (Qt), dateparser, PyYAML, SQLite. Vault is Markdown + JSON on disk.
The optional on-device model stack is Apache/MIT-licensed (Qwen3 GGUF via llama-cpp,
multilingual-e5 via fastembed/ONNX + sqlite-vec, Whisper via faster-whisper/CTranslate2,
Kokoro/Piper/Chatterbox for voice) and runs in-process - no daemon, no network.

## Project layout

```
serenity/
  __main__.py            # python -m serenity entry point (single instance, tray-resident)
  core/                  # framework-free logic (unit-tested, no Qt)
    paths.py models.py poses.py voice_lines.py parser.py ranking.py recurrence.py
    search.py settings.py todo_store.py note_store.py depgraph.py
    activity.py activity_store.py weekly_board.py pomodoro.py window_mode.py
    tts.py tts_cache.py voice_clones.py            # voice output + render cache
    semantic.py dedup.py tagsync.py rag.py digest.py   # Stage-2 AI (notes/vault)
    llm.py stt.py breaktime.py phase2_stubs.py     # LLM seam, STT seam, break-time framework
  ui/                    # PySide6 widgets
    shell.py mascot_stage.py todos_view.py notes_view.py trash_view.py graph_view.py
    capture_bar.py modals.py settings_window.py theme.py icons.py platform_win.py
    activity_chip.py focus_widget.py mini_window.py weekly_board_view.py
    ask_dialog.py duplicates_dialog.py tag_consolidation_dialog.py   # Stage-2 dialogs
  assets/poses/          # 14 animated WebP poses
  data/voice_lines.json  # DE/EN line catalog
tests/                   # pytest suite (635 tests)
serenity.spec            # PyInstaller spec (onedir, windowed)
serenity_launch.py       # frozen-exe entry runner
notes/3_Build_Decisions.md     # authoritative build decisions
notes/4_Packaging.md           # Windows build + native-verification checklist
```

## License

Serenity is **free for noncommercial use** under the
[PolyForm Noncommercial License 1.0.0](LICENSE) - personal projects, study, research,
education, and nonprofit or government use.

**Commercial use requires a paid license** - see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

Third-party components and the mascot-art provenance are documented in
[NOTICE.md](NOTICE.md); PySide6/Qt is used under the LGPLv3.

Copyright 2026 BeMuCa.
