# Serenity — Design Spec

_Status: design / brainstorm phase, 2026-06-19. No app source code yet. This doc is the consolidated source of truth for the design decisions reached so far._

## 1. Overview
Serenity is a **privacy-first personal secretary** desktop app for Windows. It lives in the system tray as a full-height, right-edge-docked, always-on-top **sidebar**, with an animated cyberpunk pixel mascot ("Serenity") at the bottom whose **speech bubbles ARE the app's prompt/dialog UI**. Goal: capture notes/todos by voice or text into one local place, with smart organization and a charming assistant.

## 2. Platform & stack
- **Python 3.12 + PySide6 (Qt6)**, packaged as a native Windows **`.exe`** (PyInstaller), auto-start to tray on login.
- Dev in WSL2, but it **runs on Windows** — the tray, always-on-top, global hotkey, and audio capture cannot come from WSL2.
- **Data:** local markdown files (notes = source of truth) + **SQLite** (todos, time entries, FTS5 keyword index) + **sqlite-vec** (embeddings) + a bundled GGUF model (Phase 2). Everything on-device.

## 3. App shell & window
- Full-height, **right-edge-docked**, always-on-top sidebar (~330–360px); width adjustable in Settings.
- `QSystemTrayIcon` + menu; `setQuitOnLastWindowClosed(False)`.
- **Presence modes:** (a) docked & visible; (b) **fully hidden** — surfaces only when a todo/timer is due or the tray icon is clicked; (c) **hide-during-meetings**.
- Surfacing must NOT steal focus (`Qt.Tool` + `WA_ShowWithoutActivating` + native `WS_EX_NOACTIVATE`).
- Optional **AppBar** docking (`SHAppBarMessage`) to reserve desktop space; default = plain always-on-top (AppBar must `ABM_REMOVE` on crash/exit or it leaves a dead desktop strip).
- **Single instance** via `QSharedMemory` + `QLocalServer` (second launch focuses the existing one).
- Aesthetic: **shadcn-dark** (zinc near-black, hairline borders, ~10px radii, one restrained violet accent), **line icons only — no emojis**; neon (cyan/magenta) confined to Serenity's stage.

## 4. Serenity (mascot)
- Cyberpunk platinum-bob woman; **animated & reactive**; her speech bubbles are the prompt/dialog layer.
- **Form/expression changes per state/category:** idle, Working (in-progress/coding), analysis/Planning, Entertainment/chilling, Meeting, Claude.
- **Animation states:** idle (breathing/blink), typing, thinking, cheer (todo done), remind (timer due), hidden→appear.
- **Art assets:** `img/` illustrated poses (idle_1/2, work_1/2, aufmerksam, examining, fun, happy, hinweis, mad, mission, nachdenklich, time, chilling) + `img/pixelated/`. Animated assets are baked from the effects pipeline into `current_Imgs/`.
- **Asset format:** animated **WebP preferred over GIF** (~2.5× smaller; per-frame noise defeats GIF compression — full GIF set ~37 MB vs ~15 MB WebP). PySide6 `QMovie` plays animated WebP natively; real app may use QMovie or a sprite-sheet + QTimer.
- **Tuned effect look** (baked into assets): holo 64, aberr osc 0–5px @4.2s, glow 21@175, scan 15/2px, noise 36, poster 16, glitch 12%, bright -4, sat +100.

## 5. Todos
- Quick-add (input at top), complete, **in-progress** (▶ → Serenity switches to "Working").
- **Multi-step subtasks:** expandable; the ticket fills with color left→right by completion; on 100% a "slice" animation + strikethrough.
- **Dependencies** (blocks / waiting-on) + a visual **dependency graph** (QGraphicsView/SVG; nodes ready/in-progress/blocked).
- Per-todo **timer/reminder**; **deadline-proximity** background fill (grows as due time nears); **recurring**; **natural-language dates**.
- **Drag-to-reorder** todos AND subtasks.

## 6. Notes / Vault
- Notes = **local markdown files** in a user-chosen folder (source of truth) + **SQLite FTS5** keyword index + **embeddings** (semantic).
- **Expandable notes** (read full body inline) + **"view raw .md file"** (modal: file path + frontmatter + raw markdown; in the real app = open in editor / reveal in folder).
- **Note↔note linking**; **auto-tag + auto-link** suggestions on save; version history + trash + restore.
- **Structured table / KB format:** a `## Title` block with `- field: value` lines → rendered as a table, parsed into a SQLite table, AND embedded per-block. One reusable format for a people directory or any knowledge base.
- **Chunking:** structure-aware (one heading/block = one chunk) + small overlap + provenance metadata (note title + heading path) — not blind fixed-size.
- **Ask-Your-Vault:** local RAG over notes → answer + **cited top documents** (clickable to open in the side panel).

## 7. Voice / transcription
- **Trigger:** global push-to-talk hotkey + in-window **mic-only button (no label)** + a **Quick Note** button. (No separate global quick-capture hotkey feature.)
- **STT:** local **faster-whisper** (default, private) + a **cloud adapter** behind one switchable provider interface.
- **Smart routing:** local LLM → structured JSON `{kind: todo|note|entry, title, category, due, subtasks[], body, fields{}, confidence}`, schema-constrained + Pydantic-validated + rule-based fallback (see §11).
- **Voice command mode:** spoken commands ("complete the milk todo", "start a 25-min focus").

## 8. Capture confirm / undo UX
1. A captured item **animates into the list** with a **"NEW" banner/glow**.
2. Serenity's bubble asks a **multiple-choice confirmation**: `[Ja/Yes] [Nein–ändern/No–change]` with slot-filled text ("Added '…' for tomorrow, 09:00. Correct?").
3. A **20-second undo window** runs (visible countdown) with inline **Approve · Change · Decline**:
   - Approve/Yes → finalize (banner fades).
   - Decline → item animates out / removed.
   - Change/No → inline editor (title + date/time chips Heute/Morgen/Übermorgen/Nächste Woche + inputs) → re-confirm.
   - Timeout → **auto-save**.
4. Each item runs its window independently.

## 9. Serenity's predefined answer catalog
- 20 events, **DE + EN** variants (3–4 each), slot templates `{title} {date} {time} {category} {count}`.
- Shipped as JSON: `{ "<event>": { "de": [...], "en": [...] } }`. Selector: random variant for the matched event in the detected input language; EN fallback.
- **Tone:** warm, playful, concise, lightly cyberpunk. **NO emojis; single hyphen "-"** (no em-dashes).
- Reference + JSON: `serenity-voice-lines.html`.

## 10. Time-tracking & analytics
- **Category bubbles around Serenity** (speech-bubble style): Meeting, Planning, Coding, Claude, Entertainment, Working, + custom "+". Single active at a time; clicking switches; a timer logs it.
- Data: SQLite `time_entries(category, start, end)` append-only log. **Focus sessions** tie to a todo (auto-set category).
- Dashboards: **Heute / Woche / Monat**; a Friday **Wochen-Board** (top categories, Δ vs last week, optimization hints).
- Plus **topic clusters** (from note embeddings) and **graph-health** (orphan notes, most-linked, dependency bottlenecks, dead links).

## 11. AI stack (verified 2026-06) — Phase 2
- **Runtime:** in-process **`llama-cpp-python`** (NOT Ollama; no daemon; same GBNF/json_schema constrained-decoding engine). One warm `Llama()` loaded at startup, single-shot stateless calls off the Qt thread.
- **Generation model:** **Qwen3-4B-Instruct-2507** (Q4_K_M, ~2.5–3 GB, Apache-2.0); alt **Gemma 3 4B-IT** if German prose disappoints. Validate German on a ~30-utterance golden set first.
- **Embeddings:** default **paraphrase-multilingual-mpnet-base-v2** (768d, Apache-2.0, best DE+EN) via **fastembed (ONNX, no PyTorch)** + **sqlite-vec**; configurable via Settings (a curated preset - mpnet / MiniLM / multilingual-e5-large - or any fastembed-supported model id). e5's `query:`/`passage:` prefixes apply ONLY to e5-family models; non-e5 models get raw text. Avoid jina-v3 (non-commercial license).
- **Guaranteed JSON:** GBNF / json_schema constrained decoding + Pydantic validate; rule-based fallback (confidence < 0.55 or LLM down). Validate the grammar at init and fail closed.
- **Risk:** PyInstaller + native `llama.dll` bundling — smoke-test the frozen `.exe` on a clean Windows machine in week 1.

## 12. Phasing
- **Phase 1 (core, NO LLM):** shell/tray/dock + presence modes; todos (subtasks, in-progress, timer, dependencies + graph); notes-as-files + keyword (FTS5) search + expand/view-file/history/trash; voice → faster-whisper transcription → note/todo; Serenity mascot + speech-bubble dialogs; category time-tracking log; add-todo / quick-note.
- **Phase 2 (smart):** embeddings + semantic search + Ask-Your-Vault; LLM smart-routing + confirm/undo flow; auto-tag/auto-link; analytics dashboard + Wochen-Board; topic clusters; voice-command mode; screenshot-OCR; animation polish; cloud-STT adapter.
- **Phase 3 (external):** Microsoft Teams meeting sync; meeting recap (local recorded audio → summary + action items).

## 13. Open decisions
- Confirm **WebP** for all animated assets (vs GIF) — render in progress.
- Finalize Serenity's look + pose-per-state mapping + exact effect preset.
- Validate German: **Qwen3-4B-Instruct-2507** vs **Gemma 3 4B-IT** on a real golden set.
- Backlog / your call: **Meeting Recap** (#9 of the feature research). Smart Capture clipboard-hotkey was declined (Quick-Note button instead). Resurfacer was dropped (2026-06-20) - a **Weekly Performance Board** is the preferred direction instead.

## 14. Mockups (in `C:\Users\8417\Downloads\Serenity_Mockups\`, also under `.superpowers/brainstorm/.../content/`)
- `app-ui-v2.html` — **main sidebar** (current): bubbles around Serenity, multi-step todos w/ progress fill + slice, drag-reorder, deadline fill, expandable notes + view-file modal, mic-only capture + quick note, Todos/Notes/Graph tabs, history/trash.
- `stats-pro.html` — analytics dashboard (shadcn-dark).
- `serenity-look.html` — pixel look gallery.
- `serenity-effects.html` — effects playground (14 images; animated chromatic-aberration + glitch-speed controls).
- `serenity-confirm-flow.html` — capture confirm/undo demo.
- `serenity-voice-lines.html` — answer catalog (DE+EN, JSON, no emojis / single hyphen).
- `current_imgs_preview.html` — animated assets gallery (GIF vs WebP).
- `voice-llm-flow.html` — voice→LLM routing design demo.

## 15. Cleanup TODO
Render agents left build artifacts in the project root — move out of the repo / add to `.gitignore`: `node_modules/`, `render_frames.js`, `encode_webp.py`, `package.json`, `package-lock.json`.
