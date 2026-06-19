# 1 — Planning (source of truth for "what's next")

_Updated 2026-06-19. Full design: `../docs/serenity-spec.md`. Build spec: `3_Build_Decisions.md`._

## Where we are
- **Phase-1 vertical slice BUILT** — runnable PySide6 app in `serenity/`, `python -m serenity`.
  Shell (frameless docked always-on-top + tray + single-instance), mascot stage (WebP via
  QMovie, random pose, click-to-pick activity, slot-filling bubble), Todos (NL dates,
  subtasks, timers, recurring, ranking, drag-reorder), Notes-as-md (+ SQLite index, keyword
  search, color/pin/expand/view-raw), Trash, Settings (state->pose editor, render scale,
  vault, autostart, DE/EN, AI/voice stubs), capture bar + quick modals. 70 unit tests pass
  headless (`QT_QPA_PLATFORM=offscreen pytest`). Local git commits, no push.
- Phase-2 seams stubbed in `serenity/core/phase2_stubs.py` (CaptureRouter / TranscriptionService
  / SemanticIndex) — real interfaces, no fake demos.
- All visual direction explored via interactive mockups (see spec §14). Main sidebar = `app-ui-v2.html`.
- AI stack decided & verified (spec §11). Phase plan locked (spec §12).

## Voice output / TTS (2026-06-19)
- Serenity now reads her bubble lines aloud (opt-in). `core/tts.py` = TtsEngine + Piper
  (local, recommended) / Sapi5 (Windows pyttsx3 baseline) / Noop stub. Pure helpers
  (clean_for_speech, pick_voice, choose_engine ladder, make_engine) unit-tested headless
  (tests/test_tts.py, 20 tests). Settings: tts_enabled (default off), tts_engine,
  tts_voice_de=de_DE-kerstin-low, tts_voice_en=en_US-amy-medium, tts_rate, tts_volume -
  surfaced in Settings window "Voice output" section. Wired in MascotStage.says/ask ->
  speaks matching language when enabled. Heavy deps optional (requirements-voice.txt +
  [voice] extra); degrades to silent Noop if absent. NOT cloud by default.
- Voice research + recommendation: `docs/serenity-voices.md`. Pick: Piper amy(EN)+kerstin(DE),
  both local, kerstin CC0. Kokoro/MeloTTS have NO German; edge-tts is cloud (privacy caveat).
- Samples (offline Piper) + player page: `Serenity_Mockups/voices/` + `voices.html`.
- Voice models (.onnx) are NOT in the repo - user drops them in the per-user voices folder
  (`%APPDATA%/Serenity/voices` or `~/.config/serenity/voices`). URLs in serenity-voices.md.
- Test count: 117 pass headless (was 97).
- TODO/decide: bundle the two default .onnx with the installer vs first-run download prompt;
  add edge-tts opt-in online voice later if the user wants the very-sweet Ana/Jenny/Katja.

## Verify next (needs a real Windows box — WSL can't show tray/always-on-top)
- Run `python -m serenity` on Windows; confirm right-edge dock, always-on-top, tray,
  WebP animation, autostart HKCU Run entry, single-instance. See README "Verifying on Windows".
- TTS: install `pip install -r requirements-voice.txt`, drop amy + kerstin .onnx into the
  voices folder, enable in Settings, confirm she speaks EN/DE and degrades to silent without
  the models.

## Phase-1 follow-ups
- DONE (review pass 2026-06-19): Recurring todo now computes the next due date on
  complete - core/recurrence.py (daily / weekdays / weekly / monthly), unit-tested.
- DONE (review pass 2026-06-19): Live timer tick + deadline "heat" fill are now animated
  in the todo card UI (1s QTimer in TodosView, runs only while something needs animating).
- Note version history (mockup had it) not implemented in Phase 1; trash/restore is.

## Correctness fixes (review pass 2026-06-19)
- Parser "NN Uhr" / "um NN Uhr" German clock forms now apply to the date and are
  stripped from the title ("morgen 17 Uhr" -> tomorrow 17:00). Was dropped before.
- TodoStore.reload tolerates the documented {"version","todos"} doc shape + malformed
  JSON instead of crashing on startup.
- Settings.undo_seconds coerced to int on load (a stringy hand-edit would crash the
  Settings dialog's QSlider).
- Single-instance guard clears a stale QSharedMemory segment left by a crashed process
  (Unix), so the app stays launchable after a crash.
- Test count: 97 pass headless (was 70).

## In-flight at last save (check these on resume)
- **WebP render** (background agent): rendering all 14 mascot poses as animated WebP into `current_Imgs/`. Verify `ls current_Imgs/*.webp` = 14. The 14 GIFs are already there.
- **Expandable notes + view-file**: DONE in `app-ui-v2.html` (reload to see).

## Immediate next steps
1. Decide **WebP vs GIF** for the animated mascot set (recommend WebP) — see `current_imgs_preview.html`.
2. Lock Serenity's **final look**: pose-per-state mapping + the effect preset (already tuned: holo 64 / aberr 0–5px@4.2s / glow 21@175 / scan 15/2px / noise 36 / poster 16 / glitch 12% / bright -4 / sat +100).
3. Run **writing-plans** to turn the spec into a Phase-1 implementation plan.
4. **Start coding Phase 1** — begin with the **app shell** (tray + docked always-on-top window) so Serenity is on screen early, then todos, then notes-as-files + keyword search, then voice transcription.
5. Before any AI feature: smoke-test **PyInstaller + llama-cpp-python** bundling on a clean Windows box (top risk).
6. Validate the German model (Qwen3-4B vs Gemma 3 4B) on a ~30-utterance DE+EN golden set.

## Open decisions (need user input)
- Resurfacer (resurface old/orphan notes) — in Phase 2 or backlog?
- Meeting Recap (local recorded meeting → action items) — Phase 3 or skip?

## Cleanup TODO
- Remove/gitignore agent build artifacts in repo root: `node_modules/`, `render_frames.js`, `encode_webp.py`, `package.json`, `package-lock.json`.

## Notes on environment
- Runs on Windows (not WSL). Mockups live in `C:\Users\8417\Downloads\Serenity_Mockups\` and open via `cmd.exe /c start`. The brainstorming companion server is flaky from the Windows browser — prefer the Windows-folder + file:// approach.
