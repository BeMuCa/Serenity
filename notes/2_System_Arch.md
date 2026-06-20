# 2 — System Architecture

_Updated 2026-06-20. Serenity is a single-user, fully LOCAL desktop app — there is no server/deployment tier; everything runs on-device for privacy. Phase-1 base + Stage-1 + Stage-2 AI are all built; this doc now reflects the real subsystems._

## Two layers: pure core vs. PySide6 UI
- `serenity/core/*` — framework-free logic, **no Qt**, unit-tested headless. All the stores, the parser/ranking/recurrence, and ALL the Stage-2 AI logic live here.
- `serenity/ui/*` — PySide6 widgets that render what core hands them and forward user actions back. The Stage-2 dialogs (`ask_dialog`, `duplicates_dialog`, `tag_consolidation_dialog`) are on-demand modals built lazily by `NotesView`.
- Everything runs in ONE local process on-device. There is no daemon, no port, no network at runtime.

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
- **MascotStage** (`ui.mascot_stage`) — renders/animates Serenity (QMovie animated WebP + QTimer), maps app events → animation state + a speech-bubble dialog layer that serves as the app's prompts (activity pick, confirmations, reminders, slot-filling). *Indispensable:* the bubble layer IS the app's primary UI affordance.
- **TodoStore** (`core.todo_store`) — JSON-backed todos: subtasks, DAG dependencies (cycle-tolerant, see `core.depgraph`), timers, recurring rules (`core.recurrence`), ordering (`core.ranking`). Feeds the dependency-graph tab and the Mini window's most-actionable pick (`core.window_mode`).
- **NoteStore** (`core.note_store`) — notes as markdown files in the user's vault (source of truth) + trash/restore; the `## Title` + `- field: value` structured blocks.
- **Activity / TimeTracker** (`core.activity` + `activity_store`) — single-active-category append-only event log persisted to `<vault>/activity.json` + the running chip; feeds the Weekly Board and owns the Fri 17-18h auto-open trigger. **Pomodoro** (`core.pomodoro`) is the 25/5 focus state machine.
- **WeeklyBoard** (`core.weekly_board`) — this-week-vs-last category stats + deltas + plain hints; the AI digest sits on top (below).
- **Settings** (`core.settings`) — persisted per-user config (dock side/size, vault folder, autostart, DE/EN, voice + AI options).

### Voice (optional `[voice]`/`[clone]`, all on-device)
- **TtsEngine** (`core.tts` + `tts_cache` + `voice_clones`) — reads Serenity's bubble lines aloud, off by default. Engine per language: Kokoro (natural English), Piper (German), Chatterbox (natural + zero-shot cloning), Windows SAPI5 baseline, Noop stub. A render cache replays identical lines instantly; pure selection/cleanup logic is unit-tested headless.

### Stage-2 on-device AI (each degrades gracefully when its backend/model is absent)
- **SemanticIndex** (`core.semantic` + `phase2_stubs.SemanticIndex`) — note embeddings → "Meaning" search. The `Embedder` seam is a Protocol: tests/default use `StubEmbedder`; the real `E5Embedder` lazily loads multilingual-e5 via fastembed/ONNX (no PyTorch), applying e5's `query:`/`passage:` prefixes inside the backend. The `VectorStore` keys vectors on `(note_id, content_hash)` and picks a `sqlite-vec` native KNN fast path OR a pure-Python cosine fallback at open time. *Degrade:* no embedder → keyword "Text" search (`core.search`). Optional `[semantic]`.
- **search** (`core.search`) — keyword ("Text") search + ordering, and `related_notes` (note-linking) which uses the index when present and degrades to a shared-tag + token-overlap ranking.
- **dedup** (`core.dedup` + `ui.duplicates_dialog`) — near-duplicate (embedding cosine, degrading to token Jaccard) + fragment (always token-containment) detection; safe `merge_notes` (union tags, append body, soft-delete the dropped note to Trash - the undo).
- **tagsync** (`core.tagsync` + `ui.tag_consolidation_dialog`) — deterministic, MODEL-FREE tag consolidation by string-similarity (normalize key + guarded difflib), with over-merge guards. Rewrites only `.tags`, idempotent.
- **rag** (`core.rag` + `ui.ask_dialog`) — Ask-Your-Vault: retrieve top_k (SemanticIndex, else keyword) → ground → ask the injected LLM → answer + cited source ids. Degrades on both axes (no index → keyword; no LLM → sources-only, `answer=None`). A `WarmCache` precomputes answers and self-invalidates on a source-content-hash drift.
- **digest** (`core.digest` + `ui.weekly_board_view`) — the weekly board comment in Serenity's voice via the injected LLM; degrades to the board's deterministic hint.
- **LLMEngine** (`core.llm`) — the pluggable local text-generation seam shared by the digest + RAG + capture router. Protocol with `StubLLM` (default) and a lazy `LlamaCppLLM` that loads a small Qwen3 GGUF in-process (no daemon) and is shared per process. Model file placed by the user in `<config>/models/`. Optional `[llm]`.
- **CaptureRouter** (`core.phase2_stubs.CaptureRouter`) — runs the deterministic `parse_capture` baseline, asks the LLM for a JSON refinement, validates and MERGES it onto the baseline (any failure → pure parser). The result goes through the **confirm + undo** flow before commit; the LLM never writes directly.
- **TranscriptionService** (`core.phase2_stubs.TranscriptionService` + `core.stt`) — audio FILE → text. `Transcriber` Protocol: `StubTranscriber` default; lazy `WhisperTranscriber` (faster-whisper / CTranslate2, no PyTorch, tiny/base for low-RAM). `transcribe_to_capture` feeds the same CaptureRouter path. Recording UI is platform-specific and lives in the app layer. Optional `[stt]`.
- **BreakScheduler** (`core.breaktime`) — the framework half of break-time deep-work: a job registry + a scheduler that runs only ELIGIBLE jobs per tick, gated by on-break/idle, an AC-power guard, and a LIGHT/HEAVY model-tier policy. The clock, break/idle and power providers are injected (deterministic, unit-tested). `detect_on_ac()` is the one optional/heavy seam (lazy psutil, tri-state, fail-safe to "not on AC"). Optional `[power]`. *NOT yet wired into the Qt event loop.*

### The degrade / lazy pattern (applies to every AI/voice service above)
Each heavy service is a **Protocol seam** with a **deterministic Stub default** + a **lazy real backend** exposing an `available` flag. Heavy imports + model loads happen on FIRST use and the loaded model is shared per process (`_shared`), so nothing heavy is resident at idle. When a backend or its model is absent the feature falls back to a built-in path - so the app and the full 635-test suite run with NO optional extras installed.

## Data layout
- Notes: `~/SerenityVault/notes/*.md` (user-chosen vault) — source of truth, portable.
- Per-user state: `config_dir()` = `%APPDATA%/Serenity` (Windows) or `~/.config/serenity`. Holds settings, the `voices/` folder (TTS models + `clones/`), and `models/` (the GGUF). The activity log is `<vault>/activity.json`; todos are JSON in the vault.
- Embedding vectors: a small SQLite DB via `sqlite-vec` when present, else the pure-Python store over the same vectors.
- Models are NEVER bundled in the binary and NEVER auto-downloaded — the user places the GGUF generation model, the ONNX e5 embedding model, the Whisper model, and the Kokoro/Piper voice files into the per-user folders. The frozen exe resolves bundled assets/data under `sys._MEIPASS` while config stays per-user (see `core.paths`).
