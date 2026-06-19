# 1 — Planning (source of truth for "what's next")

_Updated 2026-06-19. Full design: `../docs/serenity-spec.md`._

## Where we are
- Design/brainstorm phase complete enough to plan from. No app source yet.
- All visual direction explored via interactive mockups (see spec §14). Main sidebar = `app-ui-v2.html`.
- AI stack decided & verified (spec §11). Phase plan locked (spec §12).

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
