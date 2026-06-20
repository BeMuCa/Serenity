# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

`Serenity` (a.k.a. ProjectSerenity) is a privacy-first personal-secretary desktop app — Python 3.12 + PySide6, local-first, a tray-resident always-on-top dock with an animated pixel mascot whose speech bubbles ARE the prompts. It ships as a Windows `.exe` (PyInstaller).

The codebase is real and on `main`: the Phase-1 base (todos with subtasks/dependencies/recurring/NL-dates/ranking, notes-as-markdown, quick-capture, deterministic voice parser, mascot stage + tray + settings, single-instance), the Stage-1 features (activity timer + chip, Weekly Performance Board, Focus Pomodoro, three window modes, dependency-graph tab, voice output), and the Stage-2 on-device AI (semantic search, related notes, dedup + merge, tag consolidation, Ask-Your-Vault RAG, AI weekly digest, LLM capture routing, Whisper STT seam, break-time framework). 635 headless tests pass. Remaining work is Windows-only: the exe build + native verification, and verifying the real AI backends (currently stub-tested). See `notes/1_Planning.md`.

## Build / test / run

```bash
# run the app (single-instance, tray-resident)
python -m serenity

# run the suite headless (no display needed; CI / WSL). 635 tests pass.
QT_QPA_PLATFORM=offscreen python -m pytest -q

# base install is light; each AI/voice feature is an OPTIONAL extra (degrades when absent):
pip install "serenity[voice]"      # Kokoro(EN)/Piper(DE)/SAPI5 voice output
pip install "serenity[clone]"      # Chatterbox zero-shot voice cloning (heavy, PyTorch)
pip install "serenity[semantic]"   # e5 + sqlite-vec for Meaning search / related / dedup
pip install "serenity[llm]"        # in-process llama-cpp GGUF (capture routing, RAG, digest)
pip install "serenity[stt]"        # faster-whisper on-device speech-to-text
pip install "serenity[power]"      # psutil AC-power probe for the break-time guard
# (voice/semantic/llm/stt/power also have a matching requirements-*.txt; clone and dev
# do not). Model weights are never bundled. The LLM GGUF (and Piper voices) are user-placed;
# e5/Whisper/Kokoro/Chatterbox download their model once on first use into the per-user cache.

# Windows-only: build the .exe (onedir, windowed). See notes/4_Packaging.md.
pyinstaller serenity.spec
```

## Architecture / layout

- `serenity/core/` — pure, framework-free logic (no Qt), unit-tested headless. Models, paths, the deterministic parser, ranking/recurrence, the stores, plus all Stage-2 AI logic (`semantic.py`, `dedup.py`, `tagsync.py`, `rag.py`, `digest.py`, `llm.py`, `stt.py`, `breaktime.py`).
- `serenity/ui/` — PySide6 widgets: the shell (frameless docked always-on-top + tray + single-instance), mascot stage, the tab views, and the Stage-2 dialogs (`ask_dialog.py`, `duplicates_dialog.py`, `tag_consolidation_dialog.py`).
- Per-user state lives in `config_dir()` — `%APPDATA%/Serenity` (Windows) or `~/.config/serenity`; notes are Markdown files in the user's vault (`~/SerenityVault` by default), the source of truth.
- The degrade / lazy pattern: every heavy backend sits behind a `Protocol` seam with a deterministic stub default and a real lazy backend that exposes an `available` flag; nothing heavy is resident at idle (the model loads on first use and is shared per process), and when a backend/its model is absent the feature falls back to a built-in path. This is the low-RAM-at-idle principle — the suite runs fully with NO extras installed.

## Communication

- When reporting information, be extremely concise — sacrifice grammar for concision.
- After each new script/function or code change, ask if I want an explanation. For small changes, just tell me about it. When I want one, explain the code and how it fits into the whole software. I want to understand and learn from everything written.

## Editing discipline

- Don't change or overwrite comments I add — only do so when a code change makes the comment obsolete or false.
- Touch only what the request requires. Don't "improve" adjacent code, refactor things that aren't broken, or reformat. Match existing style even if you'd do it differently.
- Remove imports/variables/functions that *your* changes orphaned. Don't delete pre-existing dead code — mention it instead.
- Minimum code that solves the problem. No speculative features, abstractions for single-use code, or error handling for impossible scenarios.

## Required: header comment on every Python script

Every Python script starts with this block:

```
============================================================
Author:  Berk
Created: <YYYY-MM-DD>
Purpose: One-line description of what the script does.
Role:    1-3 lines describing where this script fits in the larger codebase.

Functions:           ← (or Models / Fields / Test classes — pick the right label)
- func_name(args) — one-liner explanation
============================================================
```

## Required: maintain `notes/`

- `notes/0_Learnings.md` — record learnings I have while coding. Identify them from my questions, advanced code concepts, library mentions, etc. Include a table of contents.
- `notes/1_Planning.md` — track planning across sessions: mental notes, next steps, follow-up tasks, important considerations. This is the source of truth when I ask "what's next?". Update after each milestone.
- `notes/2_System_Arch.md` — system architecture overview, local use vs. deployment. Include a diagram showing what goes to which service, and a per-service breakdown of its function and why it's indispensable.

## Working approach

- Don't assume; don't hide confusion. If something is unclear, stop and name it. If multiple interpretations exist, present them rather than picking silently. If a simpler approach exists, say so.
- Transform tasks into verifiable goals and loop until verified (e.g. "fix the bug" → write a test that reproduces it, then make it pass). State a brief step→verify plan for multi-step work.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.