# 2 — System Architecture

_Updated 2026-06-19. Serenity is a single-user, fully LOCAL desktop app — there is no server/deployment tier; everything runs on-device for privacy._

## High-level diagram

```
                         ┌─────────────────────────────────────────┐
  Windows tray  ───────► │  ShellController (PySide6)               │
  (click / hotkey)       │  tray • dock/always-on-top • presence    │
                         │  • single-instance                       │
                         └───────────────┬─────────────────────────┘
                                         │ hosts
        ┌────────────────────────────────┼─────────────────────────────────┐
        ▼                ▼                ▼                ▼                 ▼
 MascotController   TodoStore        NoteStore        TimeTracker      Settings
 (animation +       (SQLite)         (markdown files  (SQLite          (config)
  speech-bubble                       + watcher)       time_entries)
  dialog UI)                              │
                                          ▼
                                   IndexService
                                   (FTS5 keyword +
                                    embeddings → sqlite-vec)
        ▲                                                  ▲
        │                                                  │
   TranscriptionService ──► CaptureRouter ────────────────►│ (writes via confirm/undo)
   (faster-whisper +        (local LLM via llama-cpp-python
    cloud adapter)           + rule fallback → structured JSON)     [Phase 2]
        ▲
        │ push-to-talk
      mic / hotkey
```

## Per-module breakdown
- **ShellController** — tray icon + menu, frameless docked always-on-top window, presence-mode state machine (docked / hidden-until-due / meeting-hide), optional Windows AppBar, single-instance (QSharedMemory + QLocalServer). *Indispensable:* it's the host everything else renders inside; defines the always-on-top docked behavior that makes this a "secretary".
- **MascotController** — renders/animates Serenity (QMovie animated WebP or sprite-sheet + QTimer), maps app events → animation state + a speech-bubble dialog layer that serves as the app's prompts (folder pick, confirmations, reminders). *Indispensable:* the bubble layer IS the app's primary UI affordance.
- **TodoStore** — SQLite: todos, subtasks (DAG dependencies w/ cycle prevention), timers/reminders, recurring rules, ordering. Emits due events to the presence/reminder layer.
- **NoteStore** — notes as markdown files in a user folder (source of truth) + a file watcher; parses the `## Title` + `- field: value` structured/KB blocks; version history + trash.
- **IndexService** — keeps a rebuildable index of the notes: SQLite FTS5 (keyword) + embeddings (multilingual-e5-base via fastembed) stored in sqlite-vec; structure-aware chunking; powers search + Ask-Your-Vault. *(Phase 2 for the embedding half.)*
- **TranscriptionService** — push-to-talk → faster-whisper (local default) or a cloud adapter, behind one provider interface.
- **CaptureRouter** *(Phase 2)* — turns a transcript into structured JSON (todo/note/entry) via in-process llama-cpp-python with GBNF/json_schema constraint + Pydantic + rule fallback; the result goes through the **confirm + 20s undo** flow before commit (the LLM never writes directly).
- **TimeTracker** — single-active-category event log (SQLite) + aggregation for the Heute/Woche/Monat dashboards, Wochen-Board, focus sessions.
- **Settings** — persisted config (dock side/size, presence default, STT provider, vault folder, model paths).

## Data layout
- Notes: `~/SerenityVault/notes/*.md` (user-chosen folder) — source of truth, portable.
- App DB: SQLite (todos, time_entries, FTS5 index) in app data dir; `sqlite-vec` vectors alongside.
- Models (Phase 2): GGUF generation model + ONNX embedding model shipped beside the `.exe` (not embedded in the binary).
