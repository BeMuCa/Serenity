# Serenity - Phase 1 Implementation Spec

_Status: implementation-ready, 2026-06-19. Greenfield, no app code yet. This document is the formal Phase-1 specification derived from `notes/3_Build_Decisions.md` (authoritative), `docs/serenity-spec.md`, `notes/2_System_Arch.md`, the canonical voice-lines JSON, and the `settings.html` / `app-ui-v2.html` mockups. Where this spec and the build-decisions doc could diverge, the build-decisions doc wins. Genuine gaps are collected in "Open questions" at the end rather than resolved by invention._

Conventions used throughout: single hyphen "-" only, no em-dashes, no emojis, line icons only, ISO-8601 timestamps in UTC with `Z` suffix, IDs are short random strings.

---

## 1. Overview and Phase-1 scope boundary

Serenity is a privacy-first personal-secretary desktop app for Windows: Python 3.12 + PySide6, a full-height right-edge-docked always-on-top sidebar (~348px) with a system-tray icon, and an animated cyberpunk pixel mascot ("Serenity") at the bottom whose speech bubbles are the app's primary prompt and dialog layer. Everything is local; no network calls at runtime.

Phase 1 delivers a runnable vertical slice: app shell, docked always-on-top sidebar, tray with autostart-to-tray, the Serenity stage with per-state random poses and click-to-select activity, Todos (subtasks, timers, recurring flag, ranking), Notes-as-markdown with keyword ("Text") search and color and pin, a top-level Trash tab, Settings mirroring the settings mockup, and a Voice-capture UI (mic button, cheatsheet overlay, recording state, conversational slot-filling bubble) backed by a deterministic keyword parser. Windows-only behaviors (tray, always-on-top, AppBar, autostart, global hotkey, audio) are coded with platform guards so the app still launches and is developable on Linux/WSL2; they are only fully verifiable on Windows.

### 1.1 In scope (Phase 1)

| Area | Phase-1 deliverable |
|---|---|
| Shell | Frameless docked always-on-top sidebar, custom title bar, tray icon, autostart-to-tray, single-instance |
| Tabs | Todos, Notes, Graph (placeholder canvas), Trash (icon tab) |
| Stage | Animated WebP avatar via QMovie, 10-state machine, multi-pose random pick, click-to-select activity selector, speech bubble |
| Todos | Quick add, subtasks, drag-reorder, per-todo timer, recurring flag, ranking, done -> Trash |
| Notes | One markdown file per note, YAML front-matter, recent-first list with pin, "Text" keyword search, color palette, expand and view-raw |
| Capture | Quick Note + Quick Todo modals, mic button, cheatsheet overlay, slot-filling bubble, deterministic keyword parser, 20s-undo confirm |
| Trash | Top-level tab holding done todos, deleted todos, deleted notes with restore and delete-forever |
| Settings | State->pose editor, image library viewer, render scale, vault path, autostart, hotkey, theme accent, language DE/EN, voice/AI toggles (stubbed), 20s-undo window, voice-commands help, voice-lines editor |
| Voice lines | Load and select from `serenity-voice-lines.json` (20 events, DE+EN) |

### 1.2 Out of scope - Phase-2 seams

These ship in Phase 1 as wired-up entry points (stubbed providers, disabled toggles, placeholder views), never as fake demos. The interfaces below exist so Phase 2 slots in without rework.

| Phase-2 feature | Phase-1 seam |
|---|---|
| LLM capture routing (llama-cpp-python + Qwen3-4B) | `CaptureRouter` interface; Phase 1 uses the deterministic `KeywordParser` behind the same call site |
| Semantic "Meaning" search (configurable fastembed model, default mpnet, + sqlite-vec) | Search mode toggle "Text" (active) / "Meaning" (disabled, present); `IndexService.search(mode=...)` defined, embedding half stubbed |
| Local voice transcription (whisper.cpp) | `TranscriptionService` provider interface; mic button + recording UI present, transcript text comes from manual typing in the slot-filling bubble |
| Ask-Your-Vault RAG | Frage / Was-Wann-Wie intent recognized by the parser, routed to a "Phase 2" notice in the bubble |
| Dependency-graph visualization | Graph tab is a placeholder canvas |
| PyInstaller `.exe` packaging | `python -m serenity` entry point + README; packaging is Phase 2 |

Note: `docs/serenity-spec.md` mentions todo dependencies and a dependency graph. The build-decisions doc scopes Phase 1 to "recurring flag, ranking" and a placeholder Graph canvas; dependencies-as-data may exist in the model but the dependency UI and graph are Phase 2. This spec follows the build-decisions doc.

---

## 2. Vault layout on disk

The vault is the portable, user-chosen source of truth. Default location `~/SerenityVault/` (on Windows typically `C:\Users\<you>\SerenityVault\`; the settings mockup shows a configurable path). Notes are markdown files; todos, settings, tags, and trash metadata are JSON. A SQLite index is a rebuildable cache, not source of truth, and lives in the app-data directory, not the vault.

```
~/SerenityVault/
  notes/
    <slug>-<id>.md          # one markdown file per note, YAML front-matter + body
  todos/
    todos.json              # all active todos (single JSON document, list of Todo)
  trash/
    trash.json              # tombstone records for done/deleted todos and deleted notes
    notes/
      <slug>-<id>.md        # deleted note files moved here (body preserved for restore)
  tags/
    tags.json               # the learning category-tag arsenal
  settings.json             # app + appearance + voice settings (see 4.3)
  voice-lines.json          # canonical answer catalog (seeded from serenity-voice-lines.json)
  .serenity/
    index.sqlite            # FTS-style keyword index over notes (rebuildable cache)
    version                 # vault schema version marker, e.g. "1"
```

Rules:

- The app-data directory (`%APPDATA%\Serenity\` on Windows, `~/.local/share/serenity/` on Linux) holds runtime state that is not vault content: window geometry, the single-instance lock, logs, and a copy of `index.sqlite` if the user prefers to keep the cache out of the vault. Default keeps the index under `~/SerenityVault/.serenity/`; vault path change moves or rebuilds it.
- Notes filenames: `<slug>-<id>.md`, where `slug` is a lowercased, hyphenated, ASCII-folded prefix of the title (max ~40 chars) and `id` is the 8-char note id. The id guarantees uniqueness; the slug is for human browsing.
- Deleting a note moves its `.md` file from `notes/` to `trash/notes/` and writes a tombstone in `trash.json`. Restoring moves it back and rewrites front-matter `deleted: false`.
- Todos never live as individual files; they are entries inside `todos/todos.json`. A done or deleted todo is moved to `trash.json` (full record copied), removed from `todos.json`.
- If the vault folder is missing on startup, the app creates the full tree above and seeds `tags.json`, `settings.json`, and `voice-lines.json` from bundled defaults.

---

## 3. Data models

All schemas are JSON unless noted. Field types: `str`, `int`, `bool`, `float`, ISO datetime `str` (`"2026-06-19T08:00:00Z"`), `null` for absent optional values.

### 3.1 Todo

Stored in `todos/todos.json` as `{"version": 1, "todos": [Todo, ...]}`.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | str | yes | 8-char unique id |
| `title` | str | yes | Todo text |
| `done` | bool | yes | Completed. Done todos are moved to trash (kept here only transiently for the slice animation) |
| `inprog` | bool | yes | In-progress / "Working". Drives the `working` mascot state and timer |
| `open` | bool | yes | Disclosure expanded in UI (subtasks visible). Persisted so expansion survives restart |
| `due` | object or null | no | Deadline descriptor, see 3.1.1 |
| `meta` | object | no | Free-form chips: `{ "tags": [str], "category": str or null, "people": [str] }` |
| `steps` | array | no | Subtasks, see 3.1.2 |
| `created` | str | yes | ISO creation timestamp |
| `updated` | str | yes | ISO last-modified timestamp |
| `recurring` | object or null | no | Recurrence rule, see 3.1.3 |
| `timer` | object or null | no | Active or configured timer, see 3.1.4 |
| `order` | float | yes | Manual sort key for drag-reorder; lower = higher in list |

#### 3.1.1 `due` object

Mirrors the deadline chip in `app-ui-v2.html` (`.chip.due`, `.warn`, `.soon`).

| Field | Type | Description |
|---|---|---|
| `label` | str | Human display, e.g. "Tomorrow 09:00", "Morgen 17 Uhr" |
| `at` | str | Resolved absolute ISO datetime the deadline falls on |
| `left` | str | Human time-remaining, e.g. "in 3h", "in 2 Tagen" |
| `total` | int | Total seconds in the proximity window used to scale the heat fill |
| `soon` | bool | True when within the "soon" threshold; drives `.duesoon` pulse and `alert` nudges |

Proximity classification for the heat fill and chip color: `warn` when within 24h, `soon` when within 2h. Thresholds live in settings; defaults stated here.

#### 3.1.2 `steps[]` (subtask)

| Field | Type | Description |
|---|---|---|
| `id` | str | 6-char unique id within the todo |
| `text` | str | Subtask text |
| `done` | bool | Completed |
| `order` | float | Manual sort key for subtask drag-reorder |

The todo's progress fill width = done steps / total steps. When all steps reach done, the UI plays the slice animation and the parent todo is marked `done`.

#### 3.1.3 `recurring` object

| Field | Type | Description |
|---|---|---|
| `rule` | str | One of `daily`, `weekdays`, `weekly`, `monthly` |
| `weekday` | int or null | 0-6 (Mon-Sun) for `weekly` |
| `next` | str | ISO datetime of the next occurrence |

On completing a recurring todo, a fresh instance is created with `due.at` advanced to `next`, and the completed instance moves to trash.

#### 3.1.4 `timer` object

| Field | Type | Description |
|---|---|---|
| `running` | bool | Timer counting |
| `started_at` | str or null | ISO start of the current run |
| `elapsed` | int | Accumulated seconds from prior runs |
| `target` | int or null | Optional countdown target in seconds (focus session) |

A running timer sets `inprog = true` and surfaces the `working` mascot state. Timer expiry fires the `timer_due` voice event.

### 3.2 Note (markdown + YAML front-matter)

One file per note: `notes/<slug>-<id>.md`. Front-matter is the single source of metadata; the body below is markdown. The SQLite index is derived from these files.

```markdown
---
id: a1b2c3d4
title: Standup notes
tags: [Work, Meeting]
color: sky
pinned: true
created: 2026-06-19T08:12:00Z
updated: 2026-06-19T09:00:00Z
deleted: false
---

Body markdown here. Supports headings, lists, code, and the
"## Title + - field: value" structured-block convention from the design spec
(parsed in Phase 2; stored verbatim in Phase 1).
```

| Front-matter key | Type | Required | Description |
|---|---|---|---|
| `id` | str | yes | 8-char unique id (matches filename id) |
| `title` | str | yes | Note title (first heading fallback if empty) |
| `tags` | list[str] | yes | Category/free tags drawn from and added to the tag arsenal |
| `color` | str | yes | One of `violet`, `sky`, `green`, `amber`, `rose`, `neutral` (see 3.4). Random from the set if unset on create |
| `pinned` | bool | yes | Floats the note above the rest in the list |
| `created` | str | yes | ISO creation timestamp |
| `updated` | str | yes | ISO last-modified timestamp |
| `deleted` | bool | yes | Soft-delete marker; `true` notes live under `trash/notes/` |

### 3.3 Settings JSON (`settings.json`)

Mirrors the controls in `settings.html`. Stubbed Phase-2 controls are persisted but inert in Phase 1.

```json
{
  "version": 1,
  "vault_path": "~/SerenityVault",
  "appearance": {
    "render_scale": "M",
    "animation_speed": 100,
    "idle_bobbing": true,
    "theme_accent": "#a78bfa",
    "state_poses": {
      "idle":          ["idle_1", "idle_2", "chilling"],
      "working":       ["work_1", "work_2"],
      "coding":        ["mission", "work_2"],
      "meeting":       ["time", "aufmerksam"],
      "planning":      ["nachdenklich", "examining"],
      "entertainment": ["chilling", "fun"],
      "alert":         ["hinweis", "aufmerksam"],
      "thinking":      ["nachdenklich", "examining"],
      "success":       ["happy", "fun"],
      "error":         ["mad"]
    },
    "effect_preset": "Neon Drift"
  },
  "shell": {
    "dock_side": "right",
    "dock_width": 348,
    "autostart_to_tray": true,
    "always_on_top": true,
    "appbar_reserve": false,
    "global_hotkey": "Ctrl+Shift+Space"
  },
  "language": "de",
  "capture": {
    "confirm_before_save": true,
    "undo_window_seconds": 20,
    "confidence_threshold": 0.55
  },
  "ai_voice": {
    "llm_model": "Qwen3-4B-Instruct",
    "llm_enabled": false,
    "stt_enabled": false,
    "search_mode_default": "text"
  }
}
```

| Key | Type | Notes |
|---|---|---|
| `appearance.render_scale` | str | `S`/`M`/`L` -> 128/152/192 px (see 5.4) |
| `appearance.animation_speed` | int | 50-150 percent of QMovie playback speed |
| `appearance.state_poses` | object | state -> list of pose keys (see state machine, editable in Settings) |
| `appearance.theme_accent` | str | Hex accent from the swatch set; neon cyan/magenta reserved for the stage |
| `shell.global_hotkey` | str | Rebindable; Windows-only effect |
| `capture.undo_window_seconds` | int | 5-40, default 20 |
| `capture.confidence_threshold` | float | Below this -> slot-filling questions (default 0.55) |
| `ai_voice.llm_enabled` / `stt_enabled` | bool | Stubbed toggles, default off in Phase 1 |
| `ai_voice.search_mode_default` | str | `text` (Phase 1) or `meaning` (Phase 2) |

### 3.4 Tags arsenal (`tags/tags.json`)

The learning category-tag set. Seeds with the basic set from the decisions doc and grows as the user introduces new tags.

```json
{
  "version": 1,
  "tags": [
    "Work", "Personal", "Meeting", "Idea",
    "Errand", "Finance", "Health", "Urgent"
  ]
}
```

Rules: a typed or spoken `#tag` / `@category` not already present is appended (case-insensitive de-dupe, original casing preserved) and offered in future suggestions. Tags persist across sessions in the vault.

### 3.5 Color palette

The note-color and todo-chip palette. Neon (cyan/magenta) is reserved for Serenity's stage and is not selectable here.

| Key | Hex | Use |
|---|---|---|
| `violet` | `#a78bfa` | Default accent family |
| `sky` | `#7dd3fc` | |
| `green` | `#86efac` | |
| `amber` | `#fbbf24` | |
| `rose` | `#fca5a5` | |
| `neutral` | inherits panel | Default-no-color |

A note's color shows as the card's left accent bar plus a subtle background tint.

### 3.6 Trash / Archive records (`trash/trash.json`)

One unified store for all finished and deleted items, matching the top-level Trash tab.

```json
{
  "version": 1,
  "items": [
    {
      "id": "t-7f3a9c1d",
      "kind": "todo_done",
      "ref_id": "9k2m4p1q",
      "title": "Send invoice",
      "deleted_at": "2026-06-19T10:30:00Z",
      "payload": { "...": "full original Todo record for restore" }
    },
    {
      "id": "t-2b8e0a55",
      "kind": "note_deleted",
      "ref_id": "a1b2c3d4",
      "title": "Old draft",
      "deleted_at": "2026-06-19T11:00:00Z",
      "file": "trash/notes/old-draft-a1b2c3d4.md"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `id` | str | Trash record id (`t-` prefix) |
| `kind` | str | One of `todo_done`, `todo_deleted`, `note_deleted` |
| `ref_id` | str | Original item id |
| `title` | str | Display title in the trash list |
| `deleted_at` | str | ISO timestamp when it entered trash |
| `payload` | object | Full original record (todos) for restore |
| `file` | str | Relative path to the moved markdown (notes only) |

Actions: **Restore** rebuilds the item in its live store (todo back into `todos.json` with `done=false`/`inprog=false`; note file moved back to `notes/`, `deleted: false`). **Delete forever** removes the record and, for notes, deletes the file under `trash/notes/`.

---

## 4. Serenity state machine

Ten states from the build-decisions doc. Each state maps to a list of poses; on every transition the controller picks one pose at random with no immediate repeat. The avatar is rendered crisply (nearest-neighbor) at the configured render scale.

### 4.1 States, triggers, poses

| State | Trigger | Poses (random pick, no immediate repeat) |
|---|---|---|
| `idle` | Default / resting; no active todo or timer; selector closed | `idle_1`, `idle_2`, `chilling` |
| `working` | Generic on-task: a todo is `inprog` or a timer is running; or activity "Working" selected | `work_1`, `work_2` |
| `coding` | Deep-dev focus activity selected ("Coding") | `mission`, `work_2` |
| `meeting` | A calendar/meeting event is live, or activity "Meeting" selected | `time`, `aufmerksam` |
| `planning` | Thinking-it-through activity selected ("Planning") | `nachdenklich`, `examining` |
| `entertainment` | Off-the-clock activity selected ("Entertainment") | `chilling`, `fun` |
| `alert` | Reminder / nudge / deadline-near notice fires | `hinweis`, `aufmerksam` |
| `thinking` | AI parsing/generating (Phase 2); Phase 1 used briefly during parse | `nachdenklich`, `examining` |
| `success` | A task is marked done | `happy`, `fun` |
| `error` | A problem / failed action | `mad` |

Pose keys map to assets `current_Imgs/serenity_<pose>.webp`. All 14 assets are placed: aufmerksam, chilling, examining, fun, happy, hinweis, idle_1, idle_2, mad, mission, nachdenklich, time, work_1, work_2. Reuse across states is intentional.

### 4.2 Transition and pose-selection rules

- On a state change, read `settings.appearance.state_poses[state]`, pick a random pose, excluding the pose used in the immediately previous render for that avatar (if the list length is 1, repeat is allowed).
- Transient states (`success`, `error`, `alert`, `thinking`) auto-return to the resting state after their cue. Resting state = the current selected activity, or `idle` if none.
- `success`/`error`/`alert` hold for a short cue window (success and alert tie to a voice line; default ~2.5s) then revert.
- State changes also fire the matching voice event (see 6 and the catalog) and may show a speech bubble.

### 4.3 Click-to-select interaction (decision 1)

The category bubbles are hidden by default; the stage shows status only. The interaction:

1. Click the mascot -> the activity selector pops up: category bubbles arc around her (Meeting, Planning, Coding, Entertainment, Working, plus custom "+"), and the speech bubble slides up out of the way.
2. Click a category -> sets the current activity, swaps to that state's randomly chosen pose, logs the activity switch (time-tracking append-only log is Phase 2; Phase 1 records only the current selection), and the bubbles collapse.
3. Click the mascot again, or press Esc, to reopen or close the selector.
4. The selected activity is the resting state until changed or cleared.

---

## 5. Interaction specs (decisions 1-4)

### 5.1 Click-mascot activity selector (decision 1)

See 4.3 for behavior. UI basis from `app-ui-v2.html`: `.arena` holds the avatar centered at the bottom; `.cat` bubbles are absolutely placed in an arc; the stage is the only neon zone (cyan/magenta). Default state: bubbles hidden, only the speech bubble (status) shows. The selector is a focus-trapping overlay within the stage; Esc and outside-click close it.

Acceptance: clicking the avatar toggles the arc of category bubbles; selecting one changes the mascot state and pose and persists the current activity; Esc closes without changing selection.

### 5.2 Multi-pose random selection + Settings editor (decision 2)

- Runtime: per 4.2, each transition picks a random pose for the state, no immediate repeat.
- Settings (Appearance view, "Pose for each state"): a `.maprow` per state lets the user view the assigned pose thumbnail and reassign via a select of available images. The Images library view (`.imggrid`) lists all 14 poses; each tile can be assigned to one or more states (multi-image per state, one image to several states) and shows an "assigned" badge. Uploading custom images adds to the library (`.uploadtile`).
- The `state_poses` map (3.3) is the persisted form; the editor reads and writes it.

Acceptance: changing a state's pose list in Settings changes which poses appear at runtime; an image can be assigned to multiple states; a state can hold multiple images and the runtime randomizes among them.

### 5.3 Render scale S/M/L (decision 3)

Render scale is the avatar display size in the sidebar, rendered with nearest-neighbor (`image-rendering: pixelated`) for crisp pixel art. It does not change effect intensity.

| Scale | Avatar size |
|---|---|
| S | 128 px |
| M (default) | 152 px |
| L | 192 px |

Settings exposes a segmented S/M/L control (`appearance.render_scale`). The stage layout reserves space for the largest (L) so switching does not reflow neighboring controls.

Acceptance: selecting S/M/L resizes the avatar to 128/152/192 px respectively; pixels stay crisp; effect look is unchanged.

### 5.4 Mic cheatsheet + slot-filling bubble + learning tags (decision 4)

- **4a Mic cheatsheet.** Clicking the mic (circular `.micbtn`, bottom capture bar) shows a cheatsheet overlay listing intent keywords and date/entity grammar (mirrors the "Voice commands - keywords" settings view: intent keywords, natural-language dates, entities) before and during recording. The mic enters a recording visual state (`.micbtn.rec` pulse).
- **4b Conversational slot-filling.** After capture, if the parsed item is missing a required field (no date for a meeting, no category for an entry) or confidence < `capture.confidence_threshold` (0.55), Serenity asks for one slot at a time via her speech bubble with an inline answer box. The user answers in the bubble; she fills the slot and re-checks. When required slots are filled and confidence is sufficient, she shows the confirm bubble with the 20s-undo flow (see 6.4). Phase 1 ships the bubble Q&A UI plus deterministic keyword parsing; full NLU is Phase 2.
- **4c Learning tags.** A typed or spoken new `#tag` or `@category` is added to the tag arsenal (3.4) and offered next time.

Acceptance: clicking the mic shows the cheatsheet and enters recording state; a capture missing a required slot triggers a bubble question; answering fills the slot and proceeds to confirm; a new tag persists in `tags.json` and is suggested later.

### 5.5 Notes view (decision 4d-notes)

- **Sort:** most-recent-first by `updated`. **Pinned** notes float into a pinned section above the rest. A pin toggle on each card sets front-matter `pinned`.
- **Search modes:** a toggle labeled "Text" (literal word match over title, tags, and body; backed by the SQLite keyword index; Phase 1, default) vs "Meaning" (semantic embedding search; Phase 2; present but disabled).
- **Color:** each note card carries a color from the palette (3.5), shown as the left accent bar plus a subtle tint. Random from the set on create if unset; user can pick from the palette.
- **Expand and raw:** the card expands inline to read the full body (`.note.open .nb`); a "view raw .md" action opens the file-view modal showing the file path, front-matter, and raw markdown (in the real app, reveal-in-folder / open-in-editor).

Acceptance: notes list newest-first with pinned notes on top; pin toggles persist; Text search filters by literal match; the Meaning toggle is visible but inert; each card shows its color accent; expand shows the body; view-raw shows path + front-matter + markdown.

### 5.6 Trash top-level tab (decision 4d-notes)

Trash is a top-level tab next to Graph, behind a trash icon. It holds all finished and deleted items: done todos, deleted todos, and deleted notes (3.6). The Notes tab no longer carries its own history or trash sub-tabs. Each row offers Restore and Delete forever.

Acceptance: completing a todo moves it to Trash; deleting a todo or note moves it to Trash; Restore returns the item live; Delete forever purges it (and removes the note file). Notes tab has no separate trash sub-tab.

---

## 6. Voice-capture grammar (deterministic Phase-1 parser)

Phase 1 has no STT and no LLM. The parser is deterministic and keyword-based, operating on text the user typed (or, in Phase 2, on a Whisper transcript). It produces a structured capture, then the confirm/undo flow commits it. The parser detects input language (DE/EN) for the answer language.

### 6.1 Intent keywords (leading, optional; DE / EN)

Matching is case-insensitive on the leading token(s); the first match wins. If no intent word is found, kind defaults to `todo` and the confirm bubble offers a type switch.

| Intent keywords (DE / EN) | Routed kind |
|---|---|
| `Termin`, `Besprechung` / `Meeting`, `call` | `meeting` (a todo flagged as a meeting event) |
| `Notiz`, `Merk dir`, `merk dir` / `Note`, `note that` | `note` |
| `Todo`, `Aufgabe`, `Erledige` / `Todo`, `task` | `todo` |
| `Erinnerung`, `erinnere mich` / `Reminder`, `remind me` | `todo` with reminder |
| `Idee` / `Idea` | `note` tagged `Idea` |
| `Frage`, `Was`, `Wann`, `Wie` / `Question`, `What`, `When`, `How` | Ask-Your-Vault (Phase 2): bubble shows a "coming in Phase 2" notice |

### 6.2 Date grammar

Resolved deterministically (the build-decisions doc specifies `dateparser`, no LLM). Supported forms:

| Form | Examples |
|---|---|
| Weekday + date + time | `montag 14.7 8:00`, `friday 9am`, `am 3. Juli` |
| Relative days | `morgen 17 Uhr`, `heute Abend`, `uebermorgen`, `tomorrow` |
| Relative weeks | `naechste Woche`, `in 2 Wochen`, `next week` |
| Durations | `in 30 min`, `in 2 Stunden`, `in an hour` |
| Recurring | `jeden Werktag` (weekdays), `jeden Montag` (weekly Monday), `every weekday`, `weekly` |

A recurring phrase sets the `recurring` rule (3.1.3). A resolved date produces a `due` object (3.1.1). Times without an explicit date attach to the nearest sensible day (today if still future, else tomorrow); if no time is given, the slot-filling bubble may ask.

### 6.3 Entity grammar

| Entity | Form | Effect |
|---|---|---|
| Person | `mit <Person>` / `with <Person>` | Added to `meta.people`; links to a contact in Phase 2 |
| Tag | `#tag` | Added to `meta.tags` and to the tag arsenal if new |
| Category | `@kategorie` | Sets `meta.category` (the vault folder/category) and to the arsenal if new |

Title rule: anything after the intent word and the parsed date/entities becomes the `title` (or the body for a `note`).

### 6.4 Confidence and 20s-undo confirm flow

Confidence is a deterministic heuristic in Phase 1 (e.g. fraction of recognized structure: intent found, date resolved, title non-empty). Flow:

1. Parse -> compute confidence.
2. If confidence < 0.55 or a required slot is missing (a meeting with no date; an entry with no category), enter slot-filling: ask one slot at a time in the bubble (5.4b). Re-check after each answer.
3. Otherwise show the confirm bubble using the matching voice event (`voice_routed_todo`, `voice_routed_note`, `voice_routed_entry`) with filled slots, plus the 20s-undo control: Approve / Change / Decline and a visible countdown.
   - Approve -> finalize (commit to the vault), fire `confirm_accepted`.
   - Change -> inline editor (title + date/time chips Heute/Morgen/Uebermorgen/Naechste Woche + inputs), then re-confirm; date edits fire `datetime_changed`.
   - Decline -> discard, fire `item_declined`.
   - Timeout (20s, configurable) -> auto-save, fire `item_autosaved_timeout`.
4. Each captured item runs its undo window independently.

The 20s-undo window is honored only when `capture.confirm_before_save` is true; the window length is `capture.undo_window_seconds`.

### 6.5 Three worked parse examples

**Example 1 - todo with relative date (DE)**

Input: `Erledige Steuerunterlagen sortieren morgen 17 Uhr #steuer`

```
intent:   Erledige  -> kind = todo
date:     "morgen 17 Uhr" -> due.at = <tomorrow>T17:00, due.label = "Morgen 17:00"
entities: #steuer -> meta.tags = ["steuer"] (added to arsenal if new)
title:    "Steuerunterlagen sortieren"
confidence: high (intent + date + title)
flow:     confirm bubble (voice_routed_todo) + 20s undo
```

**Example 2 - meeting missing time, slot-filling (EN)**

Input: `Meeting with Tom next week @work`

```
intent:   Meeting -> kind = meeting
date:     "next week" -> resolves to a day but no time -> required slot missing
entities: with Tom -> meta.people = ["Tom"]; @work -> meta.category = "work"
title:    (empty after stripping) -> required slot missing
confidence: < 0.55 (no time, empty title)
flow:     slot-filling -> bubble asks "What time?" then "Title for this meeting?"
          -> on answers, confirm bubble (voice_routed_entry/todo) + 20s undo
```

**Example 3 - note as idea (DE)**

Input: `Idee Serenity koennte Notizen automatisch verschlagworten`

```
intent:   Idee -> kind = note, tag "Idea"
date:     none
entities: none
title/body: "Serenity koennte Notizen automatisch verschlagworten"
            (title = first line; full text becomes the note body)
confidence: medium-high (intent + body; no date needed for a note)
flow:     confirm bubble (voice_routed_note) + 20s undo; on approve writes
          notes/<slug>-<id>.md with front-matter tags: [Idea], random color
```

---

## 7. Module map (`serenity/` package)

Installable package, runnable via `python -m serenity`. Consistent with the system-architecture doc and the tech decisions (PySide6, `dateparser`, stdlib SQLite for the index, markdown for notes, JSON for todos/settings, vault at `~/SerenityVault/`). No network at runtime.

```
serenity/
  __init__.py
  __main__.py              # python -m serenity entry point; builds QApplication, ShellController
  app.py                   # QApplication setup, single-instance (QSharedMemory + QLocalServer), theme
  shell/
    __init__.py
    shell_controller.py    # frameless docked always-on-top window, custom title bar, tabs host
    tray.py                # QSystemTrayIcon + menu, autostart-to-tray, setQuitOnLastWindowClosed(False)
    dock.py                # right-edge dock, always-on-top, optional Windows AppBar (guarded)
    platform_win.py        # Windows-only: WS_EX_NOACTIVATE, AppBar, autostart, global hotkey (guarded)
  stage/
    __init__.py
    mascot_controller.py   # state machine, pose pick (random, no-repeat), QMovie playback, render scale
    stage_widget.py        # the neon stage, avatar, arc activity selector (click-to-select)
    speech_bubble.py       # bubble dialog layer: status, confirm/undo, slot-filling Q&A
    voice_lines.py         # loads voice-lines.json, event -> language -> random variant (no-repeat), slot fill
  todos/
    __init__.py
    todo_store.py          # load/save todos.json, ranking, recurring rollover, move-to-trash
    todo_view.py           # Todos tab: add input, cards, subtasks, drag-reorder, timer, chips
    timer.py               # per-todo timer / focus session
  notes/
    __init__.py
    note_store.py          # markdown files + front-matter read/write, soft-delete to trash
    note_view.py           # Notes tab: recent-first + pin, Text/Meaning toggle, color, expand, view-raw
    frontmatter.py         # YAML front-matter parse/serialize
  trash/
    __init__.py
    trash_store.py         # trash.json, restore + delete-forever for todos and notes
    trash_view.py          # Trash tab (icon)
  graph/
    __init__.py
    graph_view.py          # Graph tab placeholder canvas (Phase 2 dependency graph)
  settings/
    __init__.py
    settings_store.py      # settings.json load/save/defaults
    settings_view.py       # mirrors settings.html: appearance/images/voice-lines/commands/general
  capture/
    __init__.py
    keyword_parser.py      # deterministic intent/date/entity parser (dateparser), confidence
    capture_router.py      # Phase-1: routes to keyword_parser; Phase-2 seam for LLM routing
    capture_flow.py        # slot-filling + 20s-undo confirm orchestration
    transcription.py       # TranscriptionService provider interface (stub; whisper.cpp in Phase 2)
    cheatsheet.py          # mic cheatsheet overlay (intent/date/entity grammar)
  vault/
    __init__.py
    vault.py               # vault path, tree creation, seeding defaults, tags arsenal
    index_service.py       # SQLite keyword index over notes; search(mode="text"|"meaning")
    storage.py             # JSON read/write helpers, atomic writes, id generation
  models/
    __init__.py
    todo.py                # Todo, Step, Due, Recurring, Timer dataclasses/Pydantic
    note.py                # Note + front-matter model
    settings.py            # Settings model
    trash.py               # TrashItem model
    tags.py                # tag arsenal model
  assets/
    current_Imgs/          # 14 animated WebP poses (bundled)
    voice-lines.default.json
    icons/                 # line icons for tray, tabs, controls
README.md                  # Windows run/verify steps, python -m serenity
```

Notes on consistency:

- `capture_router.py` is the Phase-2 seam: Phase 1 calls `keyword_parser`; Phase 2 swaps in llama-cpp-python routing behind the same interface, output still passing through `capture_flow` (the model never writes directly).
- `transcription.py` defines one provider interface so faster-whisper/whisper.cpp (and a cloud adapter) slot in later; Phase-1 transcript text comes from typing in the bubble.
- `index_service.search(mode=...)` accepts `text` (Phase 1) and `meaning` (Phase 2, sqlite-vec + a configurable fastembed model, default paraphrase-multilingual-mpnet-base-v2).
- Windows-only calls are isolated in `platform_win.py` and guarded so the app launches on Linux/WSL2 for development.

---

## 8. Acceptance criteria per feature

**App shell**
- Launches via `python -m serenity` on both Windows and Linux without error.
- On Windows: docks to the right edge, stays always-on-top, surfaces without stealing focus; tray icon present; autostart-to-tray honored; second launch focuses the existing instance.
- On Linux: launches as a normal window; Windows-only behaviors are no-ops, not crashes.

**Tabs**
- Four tabs present: Todos, Notes, Graph (placeholder canvas), Trash (icon). Switching tabs preserves per-tab state.

**Serenity stage**
- Avatar plays the animated WebP for the current state via QMovie.
- Each state transition picks a random pose from `state_poses[state]` with no immediate repeat.
- Clicking the avatar toggles the activity selector; picking a category changes state and pose and persists the activity; Esc closes.
- Render scale S/M/L sets the avatar to 128/152/192 px, nearest-neighbor, no reflow of neighbors.

**Todos**
- Quick-add creates a todo at the bottom (`order` greatest); subtasks add, toggle, and drag-reorder; parent progress fill reflects step completion; all steps done triggers slice + parent done.
- A running timer or `inprog` sets the `working` state; recurring completion rolls a new instance to `due.next`.
- Ranking: new -> bottom; running timer or near deadline floats up; done -> Trash.
- Drag-reorder persists `order`.

**Notes**
- Creating a note writes `notes/<slug>-<id>.md` with valid YAML front-matter and a chosen or random color.
- List is newest-first; pinned notes appear in a pinned section on top; pin persists.
- Text search filters by literal match over title/tags/body via the SQLite index; Meaning toggle is visible but inert.
- Expand shows the body; view-raw shows file path + front-matter + raw markdown.

**Quick capture**
- Quick Note and Quick Todo modals open from the bottom bar and write to the vault.

**Voice capture (UI + deterministic parser)**
- Mic click shows the cheatsheet and enters recording visual state.
- Typed/captured text is parsed into kind/title/date/entities; the three worked examples in 6.5 parse as described.
- Missing required slot or confidence < 0.55 triggers slot-filling questions one at a time.
- Confirm bubble shows the correct voice event with filled slots and a 20s countdown; Approve/Change/Decline/Timeout behave per 6.4 and fire the matching voice events.
- A new `#tag`/`@category` persists to `tags.json` and is later suggested.

**Trash**
- Done todos, deleted todos, and deleted notes all appear in the Trash tab with Restore and Delete forever; Restore returns the item live; Delete forever purges (and removes the note file). Notes tab has no own trash sub-tab.

**Settings**
- Appearance: live preview, per-state pose mapping editor, render scale, animation speed, idle bobbing persist to `settings.json`.
- Images library lists all 14 poses; assign-to-state and multi-assignment work; upload adds an image.
- Voice lines: load from `voice-lines.json`, view/edit/add/delete per event DE/EN.
- Voice commands: shows intent keywords, date grammar, entities, and worked examples.
- General: vault path change relocates/rebuilds the index; autostart, hotkey rebind, theme accent, language DE/EN, undo-window slider, voice/AI toggles (stubbed) all persist; no network call is made anywhere.

**Voice lines**
- For a fired event, the catalog returns a random variant in the active language, avoiding the immediately previous one, with EN fallback when the DE bucket is empty; slots `{title} {date} {time} {category} {count}` are filled at runtime.

---

## 9. Open questions

These are genuine gaps or mild tensions between the sources; they are listed rather than resolved by invention.

1. **Vault path default.** The build-decisions doc and arch doc state `~/SerenityVault/`; the `settings.html` mockup shows `C:\Users\you\Serenity\Vault`. This spec uses `~/SerenityVault/` per the authoritative docs and treats the mockup string as illustrative. Confirm the exact default folder name.
2. **Index location.** The arch doc says the SQLite index lives in the app-data dir; portability argues for keeping it inside the vault. This spec defaults it to `~/SerenityVault/.serenity/index.sqlite` (rebuildable cache) with an app-data fallback. Confirm preference.
3. **Todo dependencies.** `serenity-spec.md` includes dependencies (blocks/waiting-on) and a dependency graph; the build-decisions doc scopes Phase 1 to recurring + ranking and a placeholder Graph. This spec keeps dependency UI/graph in Phase 2. Confirm whether a `deps` field should still be reserved on the Todo model now.
4. **Meeting as a kind.** The intent grammar routes `Termin`/`Meeting` to a "meeting" capture, but Phase-1 has no calendar store; this spec treats a meeting capture as a todo flagged as a meeting event (drives the `meeting` mascot state when live). Confirm whether meetings need a distinct store in Phase 1.
5. **Confidence heuristic.** Phase 1 has no LLM, so confidence is a deterministic structure-completeness heuristic; the exact formula is left to implementation. Confirm acceptable.
6. **Effect preset.** Settings shows an "Active effect preset" (Neon Drift) and a "Tune effects" link to the standalone effects lab. The build-decisions doc keeps the full effect pipeline out of the app (tints/glow via stylesheet only). This spec persists `effect_preset` as a label but does not implement the lab in-app. Confirm.
7. **Custom activity "+".** The activity selector includes a custom "+" bubble; how a custom activity maps to a mascot state (and whether it persists) is unspecified. This spec leaves custom activities defaulting to the `working` state until configured. Confirm.
