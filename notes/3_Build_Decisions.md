# 3 - Build Decisions & Phase-1 Feature List

_Authored 2026-06-19. This is the source of truth for the build agents. Concise on purpose: per feature it lists the realistic options and the choice I made. Decisions are mine to revise when Berk is back._

## Honesty on "final product"
A complete, polished, signed Windows `.exe` is not achievable in one autonomous pass - tray + always-on-top + audio only behave correctly on Windows, and this dev box is WSL2. What you will come back to: a **runnable Phase-1 vertical slice** - a real PySide6 app (app shell, docked always-on-top sidebar, tray, the Serenity stage, todos, notes-as-markdown, trash, settings) that launches and works, with Windows-only behaviors coded but verifiable only on Windows. LLM routing, semantic search, and voice transcription are Phase 2 and ship here as wired-up stubs, not fake demos.

---

## Image -> state mapping (all 14 poses placed)
Each state has multiple poses; the app picks one at random per transition. More can be added per state in Settings.

| State | Poses (random pick) |
|---|---|
| idle (resting, default) | idle_1, idle_2, chilling |
| working (generic on-task / timer running) | work_1, work_2 |
| coding (deep dev focus) | mission, work_2 |
| meeting (calendar event live) | time, aufmerksam |
| planning (thinking it through) | nachdenklich, examining |
| entertainment (off the clock) | chilling, fun |
| alert (reminder / nudge / notice) | hinweis, aufmerksam |
| thinking (AI parsing/generating - Phase 2) | nachdenklich, examining |
| success (task done) | happy, fun |
| error (problem / failed action) | mad |

All 14 used: aufmerksam, chilling, examining, fun, happy, hinweis, idle_1, idle_2, mad, mission, nachdenklich, time, work_1, work_2. Reuse across states is intentional. Assets: `current_Imgs/*.webp` (animated, 14/14).

---

## Resolved interaction decisions (your items 1-4)

**1. Click Serenity to pick current activity.** Today the speech bubble overlaps the category bubbles. New model: the category bubbles are hidden by default (the bubble shows status only). **Click the mascot -> the activity selector pops up** (bubbles arc around her, speech bubble slides up out of the way). Pick one -> sets the current activity, swaps to that state's pose, bubbles collapse. Click her again (or Esc) to reopen/close.

**2. Multiple poses per state, random pick.** State -> list of poses (table above). On each state change a random pose from the list is chosen (no immediate repeat). Settings lets you add/remove images per state and assign one image to several states.

**3. Render scale** = avatar display size in the sidebar (crisp pixel-art, nearest-neighbor): **S ≈ 128px, M ≈ 152px (default), L ≈ 192px**. Does not touch effect intensity.

**4a. Mic -> Intent-Keyword cheatsheet.** Clicking the mic shows a cheatsheet overlay of intent keywords + date/entity grammar (see voice grammar below) before/while recording.

**4b. Conversational slot-filling.** If a captured item is missing fields (e.g. no date, no category), Serenity asks for them one at a time via her speech bubble with an inline answer box. You answer in the bubble; she fills the slot. Confidence < 0.55 or missing required slot -> ask; else just confirm with the 20s undo. (Full NLU is Phase 2; Phase 1 ships the bubble Q&A UI + deterministic keyword parsing.)

**4c. Learning category tags.** Start with a small basic set: **Work, Personal, Meeting, Idea, Errand, Finance, Health, Urgent**. When you type/say a new tag it is added to the arsenal and offered next time. Tags persist in the vault.

**4d-notes. Notes view + Trash tab.**
- Notes list sorts **most-recent-first**; **pin** floats a note to the top (pinned section above the rest).
- **Keyword vs semantic** relabeled for clarity: "Text" (literal word match, Phase 1) vs "Meaning" (semantic embedding search, Phase 2). Default = Text.
- **Trash/Archive becomes a top-level tab** next to Graph, behind a trash icon. It holds **all finished + deleted items - done todos, deleted todos, and deleted notes** - each with restore / delete-forever. The Notes tab no longer carries its own history/trash sub-tabs.
- **Note colorways:** each note card carries a color. Random from the set if unset, or pick from a small palette that matches the tool + todo chips: violet `#a78bfa`, sky `#7dd3fc`, green `#86efac`, amber `#fbbf24`, rose `#fca5a5`, neutral (default). Neon (cyan/magenta) stays reserved for Serenity only. Color shows as the card's left accent + subtle tint.

---

## Phase-1 feature list (with the choice made)

- **App shell** - right-edge docked, always-on-top, full-height sidebar (~348px), frameless with custom title bar; tray icon + autostart-to-tray. *Choice: PySide6 `Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint`; tray via `QSystemTrayIcon`. Windows-only behaviors guarded so it still runs on Linux for dev.*
- **Tabs** - Todos | Notes | Graph | Trash(icon). *Graph is a placeholder canvas in Phase 1.*
- **Serenity stage** - animated WebP avatar, per-state random pose, click-to-select activity, speech bubble. *Choice: render WebP frames via `QMovie`; tints/glow via stylesheet + overlay, not the full effect pipeline (that lives in the standalone effects-lab).* 
- **Todos** - add via Quick Todo modal, subtasks, drag-reorder, timers, recurring flag, **ranking** (new -> bottom; running timer / nearing deadline floats up; done -> Trash). *Choice: store as a JSON document in the vault; natural-language date parsing via `dateparser` (deterministic), no LLM.*
- **Notes-as-files** - one markdown file per note in the vault, front-matter for title/tags/color/pin/timestamps; **keyword search**; color + pin; expandable read + "view raw .md". *Choice: filesystem is the source of truth; a lightweight index (SQLite) for fast keyword search and listing.*
- **Quick capture** - Quick Note + Quick Todo modals from the bottom bar (as in the mockup).
- **Trash/Archive** - restore + purge for done/deleted todos and deleted notes.
- **Settings** - state->pose mapping editor (multi-image), image library viewer, render scale, vault path, autostart, hotkey, theme accent, language DE/EN, voice/AI toggles (stubbed), 20s-undo window, voice-commands help. *Mirrors the `settings.html` mockup.*
- **Voice capture (Phase 1 = UI only)** - mic button, cheatsheet overlay, recording state, conversational slot-filling bubble. *Actual local STT (whisper.cpp) + LLM routing = Phase 2.*

### Voice grammar (documented, deterministic parser in P1)
Intent keywords (DE/EN, optional, leading): Termin|Meeting -> meeting; Notiz|Note|Merk dir -> note; Todo|Aufgabe|Erledige -> todo; Erinnerung|Reminder -> todo+reminder; Idee|Idea -> note(idea); Frage|Was/Wann/Wie -> Ask-Your-Vault (P2). Dates: "montag 14.7 8:00", "morgen 17 Uhr", "naechste Woche", "in 30 min", "jeden Werktag" (recurring). Entities: "mit <Person>", "#tag", "@kategorie".

---

## Out of scope for Phase 1 (Phase 2)
LLM capture routing (llama-cpp-python + Qwen3-4B), semantic "Meaning" search (e5 + sqlite-vec), local voice transcription, Ask-Your-Vault RAG, dependency-graph visualization, PyInstaller `.exe` packaging. All have wired-up entry points so Phase 2 slots in without rework.

## Tech decisions
Python 3.12, PySide6, `dateparser`, SQLite (stdlib) for the index, markdown files for notes, JSON for todos/settings, vault at `~/SerenityVault/`. Project laid out as an installable package (`serenity/`), runnable via `python -m serenity`, with a README covering Windows run/verify steps. No external network at runtime.

## What the two agents deliver
- **Spec agent ->** `docs/serenity-phase1-spec.md`: formal spec from this doc + the mockups (data models, module map, vault layout, acceptance criteria).
- **Coding agent ->** the runnable Phase-1 app under `serenity/`, assets wired, README with run instructions, local commits (no push).

---

## Phase-2 idea: "Break-time Deep Work" (two-tier model)
While you relax, Serenity works. Two model tiers instead of one:
- **Resident (minimal):** small model always warm for instant capture routing + slot-filling (Qwen3-4B from the AI stack).
- **Heavy (break worker):** a larger model loaded ONLY during a break to chew through queued batch jobs.

**Lifecycle.** Press Entertainment / Break (or auto-detect idle: screen locked / no input N min) -> Serenity asks in her bubble: "Pause? I have N tasks saved - want me to get to work?" [Yes / Not now]. On Yes she shows a working pose, **unloads the small model and loads the heavy one** (required - 16 GB RAM can't hold both), drains the task queue, and reports progress ("2 of 5 done"). 

**Cancelable.** If you come back and pick another state, she **finishes the current task** (no half-done output), then **unloads heavy -> reloads small** and returns to your chosen state ("finishing up, back in a moment"). Guards: AC-power only (no heavy model on battery), all local, heavy-task outputs are DRAFTS you approve - never silent writes.

**Model choice (16 GB reality):** heavy default = **Qwen3-14B Q4_K_M (~9 GB)** - only fits because the small one is unloaded first; **Qwen3-32B needs 32 GB+** so it is opt-in on bigger machines. Persist the task queue so it survives restarts.

**Brainstormed heavy tasks (good fit for downtime + a bigger model):**
1. Daily/weekly **vault digest** + review draft.
2. **Note enrichment:** auto-title untitled notes, suggest tags, extract action items into draft todos, flag near-duplicates.
3. **Semantic re-index** (builds the Phase-2 "Meaning" search) + propose links between related notes.
4. **Meeting recap** (recorded/transcribed meeting -> structured action items) - covers the open Meeting-Recap decision.
5. **Todo grooming:** split big todos into subtasks, estimate effort, detect stale items, draft tomorrow's plan, infer dependencies.
6. **Resurfacer:** surface old/orphan notes worth revisiting - covers the open Resurfacer decision.
7. **Tag/vault cleanup:** merge fragments, consolidate the learned tag arsenal, propose archives.
8. **Draft generation:** expand bullet notes, draft the "reply to X" messages referenced in todos.
9. **Ask-Your-Vault warm cache:** precompute answers to recurring questions.

This neatly absorbs the two open roadmap decisions (Resurfacer, Meeting Recap) as break-time jobs. Phase-1 seam: the model-manager stub should expose a tier swap (load/unload + queue) so Phase 2 slots in without rework.

---

## Rulings on the spec agent's 7 open questions
1. **Vault path:** `~/SerenityVault/` via `Path.home()` on every OS (resolves to `%USERPROFILE%\SerenityVault\` on Windows). The mockup's `C:\Users\you\Serenity\Vault` was illustrative; ignore it.
2. **Todo dependencies:** Phase 2 (the dependency graph is out of P1 scope). The Todo model may carry a `blocks`/`depends_on` field now, unused in P1.
3. **SQLite index location:** in app-data/cache (`%LOCALAPPDATA%\Serenity\` or `~/.cache/serenity/`), NOT in the vault. The vault stays portable user content; the index is a rebuildable cache.
4. **Meetings:** no separate store in P1. A meeting is a Todo with `kind:"meeting"` + a calendar due. (Meeting Recap is Phase 2.)
5. **Confidence (deterministic P1):** per kind, define required slots (todo: title; meeting: title+date; note: body). `confidence = filled_required / total_required`, +0.2 if an explicit intent keyword was used, capped at 1.0. `< 0.55` or any missing required slot -> slot-filling bubble. Phase-2 LLM replaces this.
6. **Effect preset:** in-app shows the active preset name + values READ-ONLY plus a "Tune effects" button that launches the standalone effects lab. No effect editing inside the app in P1.
7. **Custom activity "+":** a user-created activity defaults to the `working` pose set until the user assigns poses to it in Settings.
