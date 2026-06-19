# Serenity - Phase 1

A privacy-first personal-secretary desktop app. Serenity lives in a full-height,
right-edge-docked, always-on-top sidebar with an animated cyberpunk mascot at the
bottom whose speech bubbles are the app's prompt layer. Everything runs on-device;
no network calls at runtime.

This repository contains the **Phase-1 vertical slice**: a real, runnable PySide6
app - app shell, tray, the Serenity stage, todos, notes-as-markdown, trash/archive,
and settings. LLM routing, semantic search and voice transcription are **Phase 2**
and ship here as wired-up stubs (`serenity/core/phase2_stubs.py`), not fake demos.

The authoritative spec is `notes/3_Build_Decisions.md`.

## Quick start

Requires **Python 3.10+** (developed on 3.12).

```bash
# from the repo root
python -m venv .venv
# Windows:  .venv\Scripts\activate
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
(Windows: `C:\Users\<you>\SerenityVault\`). Change it in Settings -> General.

## What runs in Phase 1

- **App shell** - frameless `Qt.Tool` window, always-on-top, docked to the right
  edge, custom draggable title bar, system-tray icon, close-to-tray (the app stays
  resident), single-instance guard.
- **Tabs** - Todos | Notes | Graph (placeholder) | Trash (icon tab).
- **Serenity stage** - animated WebP avatar (`QMovie`), per-state **random** pose
  (no immediate repeat), speech bubble. **Click the mascot** to open the activity
  selector (bubbles arc around her); pick one to set the activity and swap her pose.
- **Todos** - quick-add with natural-language date parsing (`dateparser`, no LLM),
  subtasks, per-todo timer, recurring flag, drag-to-reorder, and the ranking rule
  (new -> bottom; running timer / nearing deadline floats up; done -> Trash).
  Stored as JSON in the vault (`todos.json`).
- **Notes-as-files** - one markdown file per note with YAML front-matter
  (`~/SerenityVault/notes/*.md`); the filesystem is the source of truth, with a
  small SQLite index for fast listing/search. Keyword ("Text") search, a color
  palette with a left accent, pin-to-top, recent-first, expand-to-read, and a
  "view raw .md" modal.
- **Quick capture** - Quick Note + Quick Todo modals from the bottom bar.
- **Trash / Archive** - done + deleted todos and deleted notes; restore / delete-forever.
- **Settings** - state->pose mapping editor (multi-image per state), image library,
  render scale (S 128 / M 152 / L 192 px), vault path, autostart, global-hotkey field,
  theme accent, language DE/EN, the 20s undo window, voice/AI toggles (Phase-2 stubs),
  and a voice-grammar help page.
- **Capture (UI + deterministic parser)** - the mic opens an intent-keyword
  cheatsheet and a recording state; a conversational slot-filling bubble asks for
  any missing field (e.g. a date) with an inline answer box. The deterministic
  keyword / date / entity parser implements the voice grammar from the decisions
  doc. The category tag arsenal starts with 8 basics and learns new tags (persisted).
- **Voice lines** - the real DE/EN line catalog (`serenity/data/voice_lines.json`),
  picked per event in the active language, slots filled, no immediate repeat,
  single hyphen, no emoji.

## Stubbed for Phase 2 (entry points only)

`serenity/core/phase2_stubs.py` defines the seams:

- `CaptureRouter` - transcript -> structured JSON via in-process
  `llama-cpp-python` + Qwen3-4B (GBNF/json_schema constrained). Phase 1 falls back
  to the deterministic parser.
- `TranscriptionService` - on-device STT (whisper.cpp / faster-whisper). Phase 1
  captures text only; no audio is recorded.
- `SemanticIndex` - "Meaning" search via multilingual-e5-base + sqlite-vec.
  Selecting "Meaning" in the Notes tab shows a notice and uses keyword "Text" search.

## Running the tests

Pure logic (ranking, date parsing, keyword search, voice parser, pose selection,
voice-line selection, stores) is unit-tested and passes headless:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

`QT_QPA_PLATFORM=offscreen` lets it run on a machine without a display (CI / WSL).

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
3. Confirm:
   - The sidebar **docks to the right edge**, full height, **stays on top** of
     other windows.
   - A **tray icon** appears; closing the dock hides it to the tray; the tray menu
     restores / hides / opens Settings / quits.
   - The **mascot animates** (WebP via QMovie). **Click her** -> activity bubbles
     arc around her; pick one -> her pose swaps and her bubble reacts.
   - Add a todo like `call Tom tomorrow 5pm #work` -> it parses the date and tag;
     start its timer -> it floats up and Serenity goes to "Working".
   - Quick Note writes a real `.md` file under `C:\Users\<you>\SerenityVault\notes\`;
     "view raw .md" shows the file with front-matter.
   - In Settings, set **Autostart** -> a `Serenity` entry is written to
     `HKCU\...\Run` (run-on-login). Render scale S/M/L resizes the avatar.
4. Launch it a second time -> it reports "already running" and exits (single instance).

## Layout

```
serenity/
  __main__.py            # python -m serenity entry point (single instance, tray-resident)
  core/                  # framework-free logic (unit-tested, no Qt)
    paths.py             #   vault / config / asset locations (cross-platform)
    models.py            #   Todo, SubTask, Note dataclasses + JSON serialization
    poses.py             #   state->pose map + random-no-repeat PoseSelector
    voice_lines.py       #   load + pick voice lines (lang, EN fallback, slots)
    parser.py            #   deterministic capture parser (intent/date/entity)
    ranking.py           #   todo display ordering
    search.py            #   keyword note search + ordering; semantic = Phase-2 stub
    settings.py          #   Settings + learning tag arsenal
    todo_store.py        #   todos.json persistence + lifecycle
    note_store.py        #   notes-as-md + SQLite index
    phase2_stubs.py      #   CaptureRouter / TranscriptionService / SemanticIndex
  ui/                    # PySide6 widgets
    shell.py             #   the docked window, title bar, tabs, tray, event wiring
    mascot_stage.py      #   avatar + speech bubble + activity selector
    todos_view.py notes_view.py trash_view.py graph_view.py
    capture_bar.py modals.py settings_window.py
    theme.py icons.py platform_win.py
  assets/poses/          # 14 animated WebP poses
  data/voice_lines.json  # DE/EN line catalog
tests/                   # pytest suite (66 tests)
```
