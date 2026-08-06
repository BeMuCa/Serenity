# 2 — System Architecture

_Updated 2026-07-02. Serenity is a single-user, fully LOCAL desktop app — there is no server/deployment tier; everything runs on-device for privacy. Phase-1 base + Stage-1 + Stage-2 AI are all built, plus the States & Contexts foundation (Phase A registry + Phase B global context toggle); this doc now reflects the real subsystems._

## Two layers: pure core vs. PySide6 UI
- `serenity/core/*` — framework-free logic, **no Qt**, unit-tested headless. All the stores, the parser/ranking/recurrence, and ALL the Stage-2 AI logic live here.
- `serenity/ui/*` — PySide6 widgets that render what core hands them and forward user actions back. The Stage-2 dialogs (`ask_dialog`, `duplicates_dialog`, `tag_consolidation_dialog`) are on-demand modals built lazily by `NotesView`.
- Everything runs in ONE local process on-device. There is no daemon and no port; no network at runtime except a one-time per-user model download on first use of an AI/voice backend (e5/Whisper/Kokoro/Chatterbox), offline thereafter — plus the EXPLICIT, user-invoked model downloader (`python -m serenity.fetch_models` / `Serenity.exe --fetch-models`), which is a separate setup step and never runs from the app's UI.

## High-level diagram

```
                         ┌─────────────────────────────────────────┐
  Windows tray  ───────► │  ShellController (PySide6)               │
  (click / hotkey)       │  tray • dock/always-on-top • presence    │
                         │  • single-instance • Full/Mini/Hidden    │
                         └───────────────┬─────────────────────────┘
                                         │ hosts
   ┌──────────────┬──────────────┬───────┼────────────┬─────────────┬──────────────┐
   ▼              ▼              ▼        ▼            ▼             ▼              ▼
 MascotStage   TodoStore     NoteStore  ActivityStore Pomodoro   WeeklyBoard   Settings
 (anim +       (JSON;        (markdown  (time log,    (focus      (Fri 17-18h   (config /
  bubble =     subtasks,     files;     running       25/5)       board +       per-user
  the prompt)  deps,         the source chip)                     AI digest)    state)
               recurring,    of truth)      │
               ranking)                      ▼
                                   note vault (the .md files)
                                              │
   ┌──────────────────────────────────────────┴──────────────────────────────────────┐
   │                          Stage-2 on-device AI (all degrade)                       │
   │   SemanticIndex ── e5 (fastembed/ONNX) → VectorStore (sqlite-vec | py-cosine)     │
   │      │                ▲ no embedder → keyword "Text" search                        │
   │      ├──► search: Meaning search + related_notes                                  │
   │      ├──► dedup: duplicates (cosine) + fragments (token-containment) → safe merge │
   │      └──► rag: Ask-Your-Vault (retrieve → ground → answer + cite) + WarmCache     │
   │   tagsync: deterministic tag consolidation (string-similarity, model-free)        │
   │   digest: weekly board comment in Serenity's voice                                │
   └────────────────────────────────────┬─────────────────────────────────────────────┘
                                         │ injected LLMEngine
   TranscriptionService ──► CaptureRouter ──► structured Capture ──► confirm + 20s undo
   (faster-whisper,         (parse_capture baseline + LLM refinement,    → commit
    on-device)               via llama-cpp-python in-process)
        ▲                         (LLM never writes directly)
        │ push-to-talk
      mic / hotkey

   BreakScheduler (framework): registry + tier-gated job runner; LIGHT on a break,
   HEAVY only on AC + idle (lazy psutil probe, fail-safe to "not on AC").
```

## Per-module breakdown

### Host + base (Phase-1, all local)
- **ShellController** (`ui.shell`) — tray icon + menu, frameless docked always-on-top window, the Full / Mini / Hidden window modes, single-instance (QSharedMemory + QLocalServer). *Indispensable:* it's the host everything else renders inside; defines the always-on-top docked behavior that makes this a "secretary".
- **States registry** (`core.states`) — the single editable source of truth for every activity + reaction: a frozen `ActivityState{key,label,color,poses,category,context}` dataclass + the `DEFAULT_STATES` seed (15 activities — 6 Business + 8 Private + a context-neutral Idle — plus 4 reactions) + `CONTEXT_DEFAULT_POSE`. The three formerly hand-synced hardcoded tables are now **projections** of it: the mascot's activity selector (`selector_rows`, context-filtered), the running-chip color (`color_for_label`), and the state→pose map (`core.poses.DEFAULT_STATE_MAP` = `{s.key: list(s.poses)}`; the shipped pose library grew to 41 WebPs in Phase A). Pure / Qt-free, headless-tested. *Indispensable:* one edit point instead of three that always agree, and the foundation of the States & Contexts milestone.
- **Context toggle** (`Shell.set_context` / `toggle_context` / `_sync_context`) — a global **Private↔Business** switch reachable from **three entry points** kept in sync: the title-bar button, an in-ring selector bubble (`MascotStage.context_toggle_requested`), and a tray-menu item. A flip re-syncs BOTH mascots (the shell's + the Mini window's), swaps the offered activity set, and — only when nothing is being tracked — shows the per-context "mood" idle pose (`CONTEXT_DEFAULT_POSE`: Business→`idle`, Private→`chilling`). A running activity span is intentionally **KEPT** on a flip (context is a property of the activity, not the moment); the activity LOG is unchanged (`ActivityEntry.category` stays the display label — no migration). *Indispensable:* one global mode that reshapes the whole selector without touching stored data.
- **MascotStage** (`ui.mascot_stage`) — renders/animates Serenity (QMovie animated WebP + QTimer), maps app events → animation state + a speech-bubble dialog layer that serves as the app's prompts (activity pick, confirmations, reminders, slot-filling). Its selector arc, bubble colors and pose pools are **projections of the `core.states` registry**, filtered by the active Private/Business context. *Indispensable:* the bubble layer IS the app's primary UI affordance.
- **TodoStore** (`core.todo_store`) — JSON-backed todos: subtasks, dependencies, timers, recurring rules (`core.recurrence`), ordering (`core.ranking`). `core.depgraph` classifies each todo ready / in-progress / blocked from its DIRECT dependencies (dangling/self/cyclic deps are tolerated; nothing enforces an acyclic graph). Feeds the dependency-graph tab and the Mini window's most-actionable pick (`core.window_mode`).
- **Reminders** (`core.reminders`, Phase H) — the pure, clock-injected reminder engine (mirrors `core.breaktime`: no Qt, no wall clock, `now` always injected → fully headless-testable). Opt-in due-relative ladder (`RUNG_MINUTES` 1w/1d/1h/30m/5m) armed per todo; `tick(todo, now)` (guard→nudge→collapse) decides what rings; `acknowledge_snooze`/`acknowledge_dismiss`/`silence`/`arm` (delta semantics that never resurrect a dismissed rung) + `pre_mark_past` mutate four tolerant `Todo` fields (`reminder_offsets`/`reminder_fired`/`reminder_active`/`reminder_nudge_at`). The Shell drives it with a 60 s QTimer + immediate cold-launch + `_on_resume` catch-up, and `_route_fire`/`_reminder_msg` render each fire to the mascot bubble + tray toast + a card banner — cross-context rings staying privacy-blurred (title-less voice bucket, single copy rule). Snooze defers the REMINDER down the ladder, never the todo's `due`. *Indispensable:* the deadline-nudge layer; the pure seam keeps all ring/snooze/catch-up logic unit-tested off the event loop.
- **NoteStore** (`core.note_store`) — notes as markdown files in the user's vault (source of truth) + trash/restore; the `## Title` + `- field: value` structured blocks.
- **Activity / TimeTracker** (`core.activity` + `activity_store`) — single-active-category append-only event log persisted to `<vault>/activity.json` + the running chip; feeds the Weekly Board and owns the Fri 17-18h auto-open trigger. **Pomodoro** (`core.pomodoro`) is the 25/5 focus state machine.
- **WeeklyBoard** (`core.weekly_board`) — this-week-vs-last category stats + deltas + plain hints; the AI digest sits on top (below).
- **Settings** (`core.settings`) — persisted per-user config (dock side/size, vault folder, autostart, DE/EN, voice + AI options), plus the States & Contexts fields: the editable registry override `activity_states` and the global `current_context` (schema below).

### Voice (optional `[voice]`/`[clone]`, all on-device)
- **TtsEngine** (`core.tts` + `tts_cache` + `voice_clones`) — reads Serenity's bubble lines aloud, off by default. Engine per language: Kokoro (natural English), Piper (German), Chatterbox (natural + zero-shot cloning), Windows SAPI5 baseline, Noop stub. A render cache replays identical lines instantly; pure selection/cleanup logic is unit-tested headless.

### Stage-2 on-device AI (each degrades gracefully when its backend/model is absent)
- **SemanticIndex** (`core.semantic` + `phase2_stubs.SemanticIndex`) — note embeddings → "Meaning" search. The `Embedder` seam is a Protocol: tests/default use `StubEmbedder`; the real `FastEmbedBackend` lazily loads a configurable fastembed/ONNX model (no PyTorch) — default `paraphrase-multilingual-mpnet-base-v2` (768d), switchable via Settings to a curated preset (MiniLM / multilingual-e5-large) or any fastembed model id. e5's `query:`/`passage:` prefixes are applied inside the backend ONLY for e5-family models (`needs_e5_prefix`); non-e5 models (the default mpnet, MiniLM) get raw text. The `VectorStore` keys vectors on `(note_id, content_hash)` and picks a `sqlite-vec` native KNN fast path OR a pure-Python cosine fallback at open time; a `store_meta` row records the active model id + dim and wipes + rebuilds the store on a model/dim mismatch. *Degrade:* no embedder → keyword "Text" search (`core.search`). Optional `[semantic]`.
- **search** (`core.search`) — keyword ("Text") search + ordering, and `related_notes` (note-linking) which uses the index when present and degrades to a shared-tag + token-overlap ranking.
- **dedup** (`core.dedup` + `ui.duplicates_dialog`) — near-duplicate (embedding cosine, degrading to token Jaccard) + fragment (always token-containment) detection; safe `merge_notes` (union tags, append body, soft-delete the dropped note to Trash - the undo).
- **tagsync** (`core.tagsync` + `ui.tag_consolidation_dialog`) — deterministic, MODEL-FREE tag consolidation by string-similarity (normalize key + guarded difflib), with over-merge guards. Rewrites only `.tags`, idempotent.
- **rag** (`core.rag` + `ui.ask_dialog`) — Ask-Your-Vault: retrieve top_k (SemanticIndex, else keyword) → ground → ask the injected LLM → answer + cited source ids. Degrades on both axes (no index → keyword; no LLM → sources-only, `answer=None`). A `WarmCache` precomputes answers and self-invalidates on a source-content-hash drift.
- **digest** (`core.digest` + `ui.weekly_board_view`) — the weekly board comment in Serenity's voice via the injected LLM; degrades to the board's deterministic hint.
- **LLMEngine** (`core.llm`) — the pluggable local text-generation seam shared by the digest + RAG + capture router. Protocol with `StubLLM` (default) and a lazy `LlamaCppLLM` that loads a small Qwen3 GGUF in-process (no daemon) and is shared per process. Model file placed by the user in `<config>/models/`. Optional `[llm]`.
- **CaptureRouter** (`core.phase2_stubs.CaptureRouter`) — runs the deterministic `parse_capture` baseline, asks the LLM for a JSON refinement, validates and MERGES it onto the baseline (any failure → pure parser). The result goes through the **confirm + undo** flow before commit; the LLM never writes directly.
- **TranscriptionService** (`core.phase2_stubs.TranscriptionService` + `core.stt`) — audio FILE → text. `Transcriber` Protocol: `StubTranscriber` default; lazy `WhisperTranscriber` (faster-whisper / CTranslate2, no PyTorch, tiny/base for low-RAM). `transcribe_to_capture` feeds the same CaptureRouter path. Recording UI is platform-specific and lives in the app layer. Optional `[stt]`.
- **BreakScheduler** (`core.breaktime`) — the framework half of break-time deep-work: a job registry + a scheduler that runs only ELIGIBLE jobs per tick, gated by on-break/idle, an AC-power guard, and a LIGHT/HEAVY model-tier policy. The clock, break/idle and power providers are injected (deterministic, unit-tested). `detect_on_ac()` is the one optional/heavy seam (lazy psutil, tri-state, fail-safe to "not on AC"). Optional `[power]`. *NOT yet wired into the Qt event loop.*

### Setup path: the model downloader (`core.model_fetch` + `serenity.fetch_models`)
- **What it does:** pulls the two model families Serenity refuses to bundle — the LLM GGUF and the Piper voices — from Hugging Face into `<config>/models` and `<config>/voices`, the exact dirs `core.llm._discover_gguf` and `PiperEngine.voice_path` read.
- **Which service it talks to:** `huggingface.co` only, and ONLY the pinned URLs in the registry (the `unsloth/Qwen3-*-GGUF` and `rhasspy/piper-voices` repos). It sends nothing but the GET — no telemetry, no account, no token; nothing about the user's vault, todos or notes ever leaves the machine here.
- **Why it is indispensable:** without it, "install Serenity" ends with a README instruction to go find a 1.1 GB quantized GGUF and name it correctly, and every AI/voice feature stays in its degraded path. It is also the only way an INSTALLED (frozen, windowed) copy can get models, via the pre-Qt `--fetch-models` branch in `__main__`.
- **Why it is NOT in the app process:** a run is minutes long and >1 GB; keeping it a separate invocation (CLI, or the installer's optional post-install step) means the tray app never blocks on it and nothing heavy is resident at idle — the same principle as the lazy backends below.
- **Integrity:** exact expected byte size per file (no upstream per-file hashes exist), streamed to `<name>.part` and `os.replace`d only when complete, so a partial download can never be discovered as a usable model.

### The degrade / lazy pattern (applies to every AI/voice service above)
Each heavy service is a **Protocol seam** with a **deterministic Stub default** + a **lazy real backend** exposing an `available` flag. Heavy imports + model loads happen on FIRST use and the loaded model is shared per process (`_shared`), so nothing heavy is resident at idle. When a backend or its model is absent the feature falls back to a built-in path - so the app and the full 635-test suite run with NO optional extras installed.

## Data layout
- Notes: `~/SerenityVault/notes/*.md` (user-chosen vault) — source of truth, portable.
- Per-user state: `config_dir()` = `%APPDATA%/Serenity` (Windows) or `~/.config/serenity`. Holds settings, the `voices/` folder (TTS models + `clones/`), and `models/` (the GGUF). The activity log is `<vault>/activity.json`; todos are JSON in the vault.
- Embedding vectors: a small SQLite DB via `sqlite-vec` when present, else the pure-Python store over the same vectors.
- Models are NEVER bundled in the binary. Split by backend: the LLM GGUF and the Piper voice `.onnx` are fetched into the per-user folders by the downloader (`core.model_fetch`) or dropped in by hand; e5 (fastembed), Whisper (faster-whisper), Kokoro and Chatterbox (huggingface_hub) each DOWNLOAD their model ONCE into a per-user cache on first use and run offline thereafter. The frozen exe resolves bundled assets/data under `sys._MEIPASS` while config stays per-user (see `core.paths`).

## Schema — States & Contexts fields in `settings.json` (Phase A/B)
Two fields were added to the `Settings` dataclass persisted at `config_dir()/settings.json`:

- `current_context: "business" | "private"` (default `"business"`) — the global context. `Settings.context()` read-guards it and `load()` HEALS any other value back to `"business"`, so a bad hand-edit is never re-persisted.
- `activity_states: []` — the editable registry override, a list of serialized `ActivityState` row dicts. `[]` (the default) means "use the code registry" — nothing is written to disk until a user edits it (Phase E). It is treated as **fully untrusted**: `Settings.states()` discards the WHOLE override (→ code default) on ANY malformed row (not a dict, unknown/missing key, non-str `key`/`label`, bad `poses`, duplicate key) — never a partial registry.
- `state_map()` (state key → pose keys) = the registry-derived base `{s.key: list(s.poses)}` with the legacy `state_pose_map` applied as a per-KEY overlay (never a whole-dict replace), so newly-seeded keys always resolve.

### Item stamps (Phase C)
Every Note (front-matter) and Todo (`todos.json`) carries optional `state_tag` (activity registry
KEY at creation, `null` when idle) + `context` (`business|private`, always set by the app). Loaders
coerce anything invalid to `null` (= shown in both contexts); the note SQLite index is untouched
(write-only cache — all filtering is in-memory via `core/states.visible()`). The stamp source is
`Shell.stamp()` (running span label → key via `states.key_for_label` + `Settings.context()`),
threaded into every creation funnel; derived items inherit their parent's stamp.

### Reminder fields (Phase H)
Every Todo (`todos.json`) also carries four reminder fields, all JSON-additive (no migration — old
todos load to the defaults; the note SQLite index is untouched): `reminder_offsets: list[int]` (armed
rungs in minutes before `due`, subset of `{10080,1440,60,30,5}`), `reminder_fired: list[int]` (consumed
rungs, sentinel `0` = a fired nudge), `reminder_active: Optional[int]` (the rung currently ringing;
`0` = an active +5 min nudge; drives the durable banner), `reminder_nudge_at: Optional[datetime]`.
`from_dict` coerces each tolerantly (unknown rung dropped, bad `active`→`None`, bad datetime→`None`) via
the same `_clean_*` pattern as the Phase C stamps. All reminder logic reads/mutates these through
`core.reminders`; the fields are the single persisted source of truth for a todo's reminder state.

Each `ActivityState` row (serialized shape):

| field | type | default | meaning |
|-------|------|---------|---------|
| `key` | str | — (required) | stable id; drives pose lookup |
| `label` | str | — (required) | display name; what the activity log stores (`ActivityEntry.category`) |
| `color` | str | `"#a78bfa"` | neon hex (selector bubble + running chip) |
| `poses` | tuple[str, …] | `IDLE_POSES` | pose-image KEYS (resolved via `core.poses.POSE_FILES`); JSON round-trips as a list, coerced back to a tuple on load |
| `category` | str | `"activity"` | `"activity"` (trackable, enters the log) \| `"reaction"` (pose-only) |
| `context` | str | `"any"` | `"business"` \| `"private"` \| `"any"` (Idle; shows in both selectors) |
