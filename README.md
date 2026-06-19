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

**Todos that understand you**
- Quick-add with natural-language dates and tags: `call Tom tomorrow 5pm #work`.
- Subtasks, per-todo timers, recurring rules, drag-to-reorder.
- Smart ranking - new todos sink to the bottom; a running timer or a nearing deadline
  floats up; finished ones move to Trash.

**Notes that are just files**
- One Markdown file per note in your vault - the filesystem is the source of truth,
  so your notes outlive the app.
- Fast keyword search, color-coded cards, pin-to-top, recent-first, view-raw-.md.

**Capture by voice or by typing**
- A mic with an intent-keyword cheatsheet.
- If a capture is missing a detail, Serenity asks for it in her bubble.
- A category-tag arsenal that starts small and learns the tags you use.
- Optional local voice output - Serenity can read her lines aloud (Piper TTS, fully
  on-device, off by default until you pick a voice).

**Yours, and private**
- 100% on-device. No network calls at runtime. Your vault is plain files you own.

> Heavy AI (local LLM routing, semantic search, on-device voice transcription) is the
> Phase-2 roadmap and ships today as clean, wired-up stubs, never fake demos.

## Status

**Phase 1 (this release) - runnable:** app shell + tray, the mascot stage, todos with
ranking, notes-as-markdown, trash/archive, quick capture, settings, the deterministic
voice parser. 97 passing tests.

**Phase 2 (roadmap):** local LLM capture routing (Qwen3-4B via llama-cpp), semantic
"Meaning" search (multilingual-e5 + sqlite-vec), on-device speech-to-text (whisper),
the dependency graph, and a packaged Windows installer.

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
(Windows: `C:\Users\<you>\SerenityVault\`). Change it in Settings -> General.

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

## Tech stack

Python 3.12, PySide6 (Qt), dateparser, PyYAML, SQLite. Vault is Markdown + JSON on disk.
The Phase-2 model stack is Apache/MIT-licensed (Qwen3, e5, Piper) and runs in-process.

## Project layout

```
serenity/
  __main__.py            # python -m serenity entry point (single instance, tray-resident)
  core/                  # framework-free logic (unit-tested, no Qt)
    paths.py models.py poses.py voice_lines.py parser.py ranking.py
    search.py settings.py todo_store.py note_store.py recurrence.py phase2_stubs.py
  ui/                    # PySide6 widgets
    shell.py mascot_stage.py todos_view.py notes_view.py trash_view.py graph_view.py
    capture_bar.py modals.py settings_window.py theme.py icons.py platform_win.py
  assets/poses/          # 14 animated WebP poses
  data/voice_lines.json  # DE/EN line catalog
tests/                   # pytest suite (97 tests)
docs/serenity-phase1-spec.md   # the formal Phase-1 spec
notes/3_Build_Decisions.md     # authoritative build decisions
```

## License

Serenity is **free for noncommercial use** under the
[PolyForm Noncommercial License 1.0.0](LICENSE) - personal projects, study, research,
education, and nonprofit or government use.

**Commercial use requires a paid license** - see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

Third-party components and the mascot-art provenance are documented in
[NOTICE.md](NOTICE.md); PySide6/Qt is used under the LGPLv3.

Copyright 2026 BeMuCa.
