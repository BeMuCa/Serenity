# 1 — Planning (source of truth for "what's next")

_Updated 2026-07-01. Full design: `../docs/serenity-spec.md`. Build spec: `3_Build_Decisions.md`._

## Session wrap (2026-07-01) — Phase A: State/Context registry (built, `wf/phase-a-states`)
- **SHIPPED Phase A — the States & Contexts foundation.** New pure `core/states.py`: frozen
  `ActivityState{key,label,color,poses,category,context}` + `DEFAULT_STATES` seed (7 trackable
  activities + 4 reaction states) + helpers (`default_states`/`activities`/`is_protected`/
  `color_for_label`/`selector_rows`). The 3 hand-synced hardcoded sources
  (`mascot_stage.ACTIVITIES`, `activity_chip._ACTIVITY_COLORS`, `poses.DEFAULT_STATE_MAP`) are now
  PROJECTIONS of the registry. Settings-persisted (`activity_states` field, default `[]` => code
  default) with a hardened untrusted-input `states()` deserializer + registry-derived `state_map()`
  per-key overlay. Activity LOG unchanged (category = display label; no migration).
- **Pose library promoted:** copied all 41 styled webps `current_Imgs/` -> `serenity/assets/poses/`
  (14 re-styled + 27 new), extended `POSE_FILES`. 20 new poses seeded into activities/reactions; 7
  greeting/event poses (`hi/leaving/next_task/ripped_note/trash/verlegen/hand_disappearing`)
  reserved for Phase F/event wiring. **Focus** got its own key (was secretly `coding`); pose pools
  enriched, so the mascot shows more variety and the 14 existing poses now use the re-styled look.
- **Process (full pipeline):** brainstorm (+ pose-gallery artifact, user chose option B "promote all
  art" + option (i) re-style) -> flow-harden Workflow (7 flows -> 21 candidates -> **12 confirmed**
  [1 P1 / 8 P2 / 3 P3], all folded into the spec) -> spec + 5-task TDD plan -> TDD implement -> QA.
  Impact gate grep-verified: `current_state` has ZERO readers (Focus change safe); only
  `shell.py:481` changed `coding`->`focus`.
- **QA caveat:** the QA Workflow's criticizer + test-agent lenses hit a **session usage limit**
  (reset ~15:30 CEST) and ran INLINE instead (optimizer lens completed remotely). Correctness clean;
  folded 3 test hardenings (killed a vacuous override round-trip test; reserved-pose invariant;
  non-str poses element) + 1 PEP8 blank-line fix. **Consider re-running the QA Workflow after the
  limit resets for fully-independent adversarial coverage.**
- Suite **1020 passed / 5 skipped** (was 1001 at branch start; +19). Commits `f8694ad`..`d0c8ff6`
  on `wf/phase-a-states` (branched off `wf/ship-wave`). Docs:
  `docs/superpowers/specs|plans/2026-07-01-phase-a-state-registry*`.
- **NEXT — Phase B: global Private<->Business context TOGGLE.** context field + current_context in
  settings; title-bar/bubble toggle swaps the active set + default pose + filters todos/notes; seed
  the Private set {Chilling,Friends,Girlfriend,Eat,Music,Learning,Gaming,Code} (the current 7 are
  already tagged the Business set). Depends on A (done). See the phased roadmap below.
- **Open:** PR for `wf/phase-a-states` NOT opened (pending user; it stacks on PR #2 until
  `wf/ship-wave` merges).

## Session wrap (2026-06-30) — Calendar-expand slice (c) ICS round-trip (built, `wf/ship-wave`)
- **SHIPPED slice (c): ICS (iCalendar) round-trip import + export** — the FINAL slice of Calendar-expand.
  Hand-rolled, **zero new deps** (stdlib `zoneinfo` only). New pure `core/ics.py` (`todos_to_ics`,
  `parse_ics`, `reconcile`, `_parse_dt`, escape/fold, `decode_ics_bytes`); `Todo.ics_uid` field for
  cross-device dedup; Calendar-tab Export/Import buttons + `ImportPreviewDialog` (preview-then-confirm);
  transactional apply (single `save()` + `reload()` rollback) + cross-surface refresh wiring.
- **Locked decisions** (brainstorm): round-trip; export = active-with-due todos; CATEGORIES only (no
  subtasks/tags/RRULE); recurrence OUT (recurring todo → single event; foreign RRULE → first occurrence
  + skip-note); UID dedup via `ics_uid or id`. **Key correction during design:** `Todo.due` is NAIVE
  **LOCAL** wall-clock (verified in code — `ranking` does `due - datetime.now()`, parser sets
  `RETURN_AS_TIMEZONE_AWARE:False`), so timed export = **floating** (no `Z`); import normalizes foreign
  `Z`/`TZID` → local. The initial "UTC/emit Z" assumption was wrong and would have shifted every time.
- **Process: full GSD pipeline, multi-agent.** Flow-harden Workflow (6 flows → 58 confirmed gaps → 2 P1
  + 16 P2 folded into the spec) → spec+TDD plan → **9-task subagent-driven TDD** (fresh implementer +
  adversarial reviewer per task) → **QA pipeline**: criticizer (22→6 confirmed: trash-mutation on apply,
  `parse_ics` OverflowError crash, microsecond fixpoint break, double-update, markup-in-preview,
  truncation) → optimizer (6 behaviour-preserving edits) → test-agent (+24 tests). Each pass adversarially
  verified; fixed between each.
- Suite **1001 passed / 5 skipped** (was 936 at slice start; +65). 12 commits `9d2aa82`..`9e36c50`.
  Docs: `docs/superpowers/specs|plans/2026-06-30-calendar-expand-c*`.
- **Known design note (not a bug):** a foreign ICS `UID` that coincidentally equals a local todo's `id`
  would match on re-import — spec-compliant (keying by `id` is what enables the cross-device fixpoint),
  unlikely with real domain-qualified UIDs, untested. Documented for later if it ever bites.
- **NEXT: Phase A — State/Context registry** (`core/states.py`; the foundation of the States & Contexts
  milestone). HIGH fan-out (chip + selector + tracker + Settings all read it) → the place to actually use
  GitNexus `impact` before editing. `wf/ship-wave` pushed through slice (b); slice (c) NOT yet pushed, no
  PR opened. Pre-existing tracked junk under `.superpowers/brainstorm/*` (old companion-server logs/pids)
  could be cleaned up someday — unrelated to this work.

## Session wrap (2026-06-29) — Calendar-expand slice (a) (built + pushed, `wf/ship-wave`)
- SHIPPED slice (a) of Calendar-expand: a read-only Teams-style **expanded week time-grid** in the
  reusable `ExpandedPanel` (7 day-cols × 24 hour-rows, all-day strip, week nav, ~08:00 default scroll)
  + a read-only right-hand active-todo list, opened by a ⤢ button on the Calendar tab. Read-only.
- Decomposed into 3 slices (USER chose): **(a) read-only grid [DONE]** → (b) drag-schedule/create
  write path → (c) ICS import/export. Each its own spec→plan→build.
- Architecture: Qt-free `calview.build_timegrid` (+`TimeGrid`) headless-tested; thin
  `ui/calendar_week_panel.CalendarWeekPanel`; the shell single-instance pop-out **generalized
  (isinstance-based)** to host either a note or the calendar (cross-kind switch routes through the
  note's dirty `handle_close()` first). Reuses collect_events/_has_time/_week_start/_week_label.
- Full QA pipeline (now the standard — see memory `feature-qa-agent-pipeline`): usecase-extender
  flow-harden (23→7: 0 P1, 4 P2, 3 P3, folded into the spec) → criticizer (0 real bugs) → optimizer
  (3 simplifications) → test (5 coverage/discrimination hardenings). Suite **912 passed / 5 skipped**
  (was 799 at session start). Docs: `docs/superpowers/specs|plans/2026-06-29-calendar-expand-a*`.
- **handle_close()→True is correct only because (a) is read-only — slice (b) MUST revisit it** when
  drag-scheduling adds an in-flight write.
- **slice (b) DONE + pushed** (commits `c30acda`..`29c9284`): drag-to-reschedule (right-list rows +
  grid event-blocks → hour cells keep-minute / all-day strip → midnight) + create-on-slot
  (`QuickTodoDialog.default_due`, when-only parse) + `wrote` signal → shell cross-surface refresh.
  Hardened (32→14: 0 P1/8 P2/6 P3) + QA'd (criticizer 0 bugs). Suite **936/5**. Docs:
  `docs/superpowers/specs|plans/2026-06-29-calendar-expand-b*`.
- Process codified: `CLAUDE.md` now has the build+audit pipeline + relaxed GitNexus policy
  (PR-boundary / high-fan-out only); old copy at `CLAUDE.md.bak-2026-06-29`. Memory: `feature-qa-agent-pipeline`.
- **slice (c) — ICS round-trip: DONE 2026-06-30** (see the 2026-06-30 wrap at the top). Then **Phase A**
  (state registry; HIGH fan-out — the place to actually use GitNexus `impact`).

## Session wrap (2026-06-27) — Notes-expand (built, on `wf/ship-wave`)
- NEW FEATURE shipped (branch `wf/ship-wave`, 8 commits `fdbeb9a`..`1e3a0c7` + 2 docs): **Notes-expand**
  — expand a note into a large left-docked Serenity-themed pop-out editor (plain-text body +
  toggled raw-YAML front-matter sub-editor + "Open in OS editor" hand-off), on a reusable
  `ExpandedPanel` foundation that **Calendar-expand will reuse next**.
- Process (full GSD-style flow, multi-agent): brainstorm → **flow-hardening pass** (44 candidate
  gaps → 35 confirmed, 11 P1/17 P2/7 P3) folded into the spec → TDD plan → implementation →
  **adversarial review** (19 confirmed findings incl. a CRITICAL: the external-change guard was
  unreachable dead code — container was `Qt.NoFocus`) → fixes. Docs: `docs/superpowers/specs/
  2026-06-27-notes-expand-design.md`, `docs/superpowers/plans/2026-06-27-notes-expand.md`.
- Architecture: all fail-safe logic in Qt-free `core/note_draft.py` (headless-tested): hybrid
  draft-sidecar + explicit commit, content-keyed recover/external-change (never mtime), strict
  commit validator (immutable id, typed FM fields), `promote()` field-merge + corrupt-backup +
  store re-get. `NoteStore.reload_note` + draft-aware `purge`. UI: `ExpandedPanel`,
  `NoteEditorPanel`, `platform_win.dock_left_of`, NoteCard ⤢ entry, shell single-instance wiring.
- Suite: **882 passed, 5 skipped** (was 799; +83 tests). gitnexus blast radius self-contained
  (all affected processes internal to the feature). gitnexus index left stale (re-analyze on next use).
- **NEXT: Calendar-expand** — its own brainstorm → spec → plan → build, reusing `ExpandedPanel`
  (week grid like Teams, create/drag-schedule todos, ICS import/export). Then resume Phase A
  (state registry) per the build order below. Pre-existing uncommitted Calendar-tab tweaks
  (calview/calendar_view + tests) and GitNexus artifacts (`.claude/`, `AGENTS.md`, `codebase-map.html`)
  remain in the working tree, untouched by this feature's commits.

## Session wrap (2026-06-24)
- COMMITTED this session (branch `wf/ship-wave`): todo features #4/#5/#6, the Qwen3 `<think>`
  fix, Settings About tab (version + manual update check), README install/update guide, this
  States&Contexts roadmap, the style-studio extracted to `feature/style-studio/` (+ a reviewed
  cleanup), 40 styled mascot WebP in `current_Imgs/` (26 NEW + 14 re-styled), a done-grace
  bug-fix (below), and LLM GGUF-discovery + stale-label fixes (`5def135`). Suite 735/5.
- 26 NEW poses staged in `current_Imgs/` (dj, searching, cheering, spilled_coffee, ...) — NOT
  wired into the app yet; promote in Phase E. The 14 live poses still live in serenity/assets/poses.
- **USER-SET BUILD ORDER (2026-06-24):** (1) **Calendar tab** [NEW, see below] → (2) **Phase A**
  (state registry) → B..G per the roadmap, H interleaved. **RELEASE work only when the user calls
  for it** (manual first release + self-written CI/CD + maybe OWASP — planned this evening; see
  memory `release-cicd-evening-plan`).
- LLM model robustness: (A) DONE - GGUF discovery is now tolerant (`LlamaCppLLM._discover_gguf`
  prefers the named defaults but falls back to ANY `models/*.gguf`, so the official Q8_0 0.6B is
  found; `5def135`). (D) DONE - corrected the stale `Qwen3-4B / whisper.cpp / stubbed` Settings
  labels. DEFERRED to the evening release work: (B) an LLM model picker (1.7B / 0.6B / custom
  path, mirroring the embedding-model picker) and (C) a "Test model" health-check that actually
  loads + runs a tiny generate (today's `_probe` only checks file-exists + importable, NOT real
  usability, so a corrupt/incompatible GGUF still reads "Active"). Plus the `[llm]` packaging
  verification: bundle llama-cpp's native DLLs into the frozen exe (likely
  `collect_dynamic_libs('llama_cpp')` in `serenity.spec`) + confirm load on a clean Windows box.
- A session bug-sweep (adversarial scan of this session's `serenity/` changes) found + FIXED
  (commit `796065b`, +5 regression tests): a HIGH done-grace data-loss bug — the grace QTimer
  was on the ephemeral TodoCard, so a refresh() mid-window (add/edit/voice-capture) silently
  dropped the completion; now the timer lives on TodosView (keyed by id) and survives rebuilds.
  Plus 2 MED: `_linked_note` skips trashed notes; subtask auto-complete syncs the main checkbox.
- FLOW-HARDENING AUDIT (read-only, full doc: `notes/5_Interaction_Flows.md`): mapped every
  interaction flow across 7 areas -> interruptions -> safety-net gaps. **114 gaps: 16 P1
  (data-loss/irreversible), 45 P2 (silent inconsistency/freeze), 53 P3 (polish).** The audit itself
  was read-only.
  **=> ALL 16 P1 are now FIXED + committed (`dce881d`..`6922fdb`, +35 TDD tests, suite 770/5):**
  the `atomic_write_text` helper (`tmp` + `os.replace`) routed through TodoStore/ActivityStore/
  Settings/CloneRegistry saves + NoteStore `_write`; corrupt-file-on-load backup (`.corrupt-<ts>`
  vs silent reset); guarded note mutate (no memory/disk divergence on a failed write); purge-unlink
  guard; crash-safe merge + fail-fast tidy-tags; confirm dialogs on irreversible purge + remove-clone.
  **REMAINING: P2 (45) + P3 (53) stay in `notes/5_Interaction_Flows.md` for later** (e.g. timer
  double-count across close, UI-thread model-load freezes, slot-fill dead-ends).

### NEW FEATURE — Calendar tab (build FIRST, before Phase A)
Simple + small, per the user. Week vs Month view; pick a week; render that week as a calendar grid
with events placed on their day, and a list below of that week's saved things. Events/data already
exist — no new model: todos with a `due` date are the events (category "meeting" highlighted), and
`Note.created` dates the saved notes. Read-only in v1 (no event creation). New tab in the shell tab
row (Todos / Notes / Graph / Board / **Calendar**). Headless-testable: a pure `core/` helper that
buckets dated items into a week/month grid; the view just renders it. Self-contained (like the
Phase H quick wins) — no dependency on the states/contexts work.

## Recent progress (2026-06-23, branch `wf/ship-wave`)
- Shipped (committed): #4 note<->meeting links (`Todo.linked_note_ids` + prep/protocol
  button; the note survives trash/purge), #5 done-grace (line-through + `undo_seconds`-timed
  commit, default 20->5; un-tick cancels), #6 inline todo/subtask editing. README features
  section + the ever-evolving LLM voice-lines bullet.
- Fix: Qwen3 `<think>` leak - `LlamaCppLLM.generate` now injects `/no_think` + `strip_think()`
  (RAG answers + the weekly digest were truncating). 5 degrade-path tests now skip when the
  real extra is installed.
- Suite: 728 passed, 5 skipped (was 635 - extras now installed in `.venv`).

### Real-backend verification (2026-06-23) - DONE on WSL/CPU (was stub-only)
- semantic (fastembed+sqlite-vec): real 768-d embeddings, native KNN, cross-lingual meaning
  search + dedup - WORKS.
- llm (llama-cpp built from source, Qwen3-0.6B Q8_0 GGUF): all 3 consumers run; capture-routing
  contract holds (date stays parser-derived). `<think>` leak found + fixed.
- stt (faster-whisper tiny): loads; accuracy still needs a real spoken wav.
- power (psutil): AC guard reads power state, blocks heavy jobs safely.
- Install note: `[llm]` has NO prebuilt wheel - needs cmake + from-source build
  (`CMAKE_ARGS="-DGGML_NATIVE=OFF"`); document for the Windows frozen exe.
- Still needs Windows/real-audio/golden-set: STT accuracy, DE+EN 30-utterance eval (4B models),
  exe DLL bundling.
- GGUF filename: `core/llm.py` hardcodes `Qwen3-0.6B-Q4_K_M.gguf` but the official 0.6B repo
  ships only Q8_0 - reconcile the constant / make discovery tolerant.

## NEXT MILESTONE - States & Contexts (decisions LOCKED 2026-06-23)
User-confirmed decisions:
- Note/todo state stored as a `state_tag` field (front-matter), NOT folder-per-state.
- "Context" = a GLOBAL Private<->Business toggle that swaps the activity set + Serenity's mood
  AND filters the todos/notes shown. Default state = Idle per context.
- Keywords: LLM auto-grows the (already bilingual DE+EN) keyword list on weak parse + a Settings
  editor to view/add/edit/remove. Always degrades to the deterministic parser.
- ONE editable STATE REGISTRY in core/ drives selector bubbles, chip, tracker colors, Settings,
  and state_tag.

Ground truth from recon (2026-06-23):
- Reaction states (alert/thinking/success/error) are set via `set_state()` (mascot_stage.py:266)
  which ONLY swaps the pose - they CANNOT enter the tracker; only the activity selector writes
  the log. (#3 worry unfounded.)
- Parser is ALREADY DE+EN (parser.py); keyword lists are hardcoded constants, not user-editable;
  the Settings "Intent keywords" tab is a read-only cheat-sheet.
- Vault is FLAT (`<vault>/notes/*.md`); front-matter = source of truth; `.index.sqlite` is a
  disposable rebuilt cache. Note model has tags but no category/state.
- Activities hardcoded 3x: mascot_stage.ACTIVITIES, activity_chip._ACTIVITY_COLORS, poses
  DEFAULT_STATE_MAP.
- Board has NO per-activity colors today (only the chip dot). No context concept anywhere.
- Data already update-safe: all user data in %APPDATA% + vault, OUTSIDE the install dir. NO DB
  migration mechanism exists (zero user_version / ALTER).

### Phased roadmap (each phase = independently shippable + headless-tested)
- Phase A - State/Context REGISTRY (foundation). `core/states.py`: ActivityState
  {key,label,color,context,pose}; split reaction vs trackable; persist in settings
  (backward-compat); chip + selector read it. Risk HIGH fan-out -> gitnexus impact first.
  Verify: registry unit tests; existing UI tests green.
- Phase B - Global Private<->Business TOGGLE. context field + current_context in settings;
  title-bar/bubble toggle swaps active set + default pose; seed Business {Working,Coding,Meeting,
  Planning,Focus,Entertainment} + Private {Chilling,Friends,Girlfriend,Eat,Music,Learning,Gaming,
  Code}. Depends A. Verify: context-switch + persistence tests.
- Phase C - state_tag on notes+todos, auto-apply + deselectable FILTER chip. Optional
  state_tag+context on Note (front-matter + index col) and Todo; thread current state into
  creation; auto-selected removable filter row in Notes (+Todos). Depends A,B. Verify: round-trip
  (old notes null), filter logic, index rebuild.
- Phase D - Tracker CONTEXT COLORS. context in aggregation; board rows get border-left
  violet=business / cyan=private; category->context via registry w/ neutral fallback. Depends A.
  Verify: board build + row-class tests.
- Phase E - Settings: MANAGE STATES + per-state mascot IMAGE. Rework Appearance into a
  States&Contexts panel: per-state row (label . context . color . image picker, default idle) +
  add/remove. Depends A. Verify: settings round-trip, backward-compat.
- Phase F - VOICELINES per state/context + standup greetings. Data-driven state/context axis in
  the voice_lines loader (fallback to default state); per-context persona; new greeting events
  morning-standup / after-break / after-eating wired to shell.greet + break-end; LLM task-lines
  get a state-aware prompt + clear-on-switch. Depends A,B. Verify: loader merge/fallback, greeting
  dispatch.
- Phase G - KEYWORD learning + editor (#2). settings.intent_keywords (context-scoped);
  _detect_intent reads a merged map; LLM keyword-suggestion gated on weak parse in CaptureRouter
  w/ strict validation; editable Settings list (replace the read-only grammar tab). Always
  degrade to parser. Depends loosely A/B. Verify: injected-keyword parser tests, bad-suggestion
  rejected, degrade-without-LLM.
- Phase H - QUICK WINS (independent): timer reminders (due-15m / due-5m; dormant deadline_near /
  timer_due events already in voice_lines.json), snooze/defer due, NL todo editing (edit-intent
  router -> structured diff). Verify: per-feature tests.
- Phase I - UPDATES & MIGRATIONS (#1; before any release that changes the schema): PRAGMA
  user_version migrations for semantic.sqlite + a SCHEMA_VERSION rebuild-on-mismatch for the note
  index; signed Inno Setup installer (Windows, per-user, fixed AppId, never touches %APPDATA%/
  vault); optional in-app GitHub-release check. Verify: migration replay/atomic/rollback tests;
  installer Windows-only.

Recommended order: A -> B -> C -> D -> E -> F -> G; H interleaved as fast value; I before any
release that ships the new schema (C). Each phase gets its own bite-sized TDD plan when started.

## Where we are (2026-06-20)
- **Phase-1 base + Stage-1 + Stage-2 all BUILT and on `main`.** 635 unit tests pass headless
  (`QT_QPA_PLATFORM=offscreen pytest`).
- **What remains is Windows-only + real-backend verification** — see "Verify next" below.
  Stage-1 and Stage-2 themselves are DONE; nothing more to *build* on either before packaging.

### Stage-1 features (done, on main)
- Activity time-tracking + running chip (`core.activity` / `activity_store`, `ui.activity_chip`).
- Weekly Performance Board tab (`core.weekly_board`, `ui.weekly_board_view`); auto-opens Fri 17-18h.
- Focus Pomodoro 25/5 (`core.pomodoro`, `ui.focus_widget`).
- Three window modes - Full / Hidden / Mini-dock (`core.window_mode`, `ui.mini_window`).
- Quick-Note tag field + meeting-protocol template; read-only dependency-graph tab
  (`core.depgraph`, `ui.graph_view`).
- Kokoro English voice picker (English by default, an all-languages toggle exposes all 54).

### Stage-2 AI features (done, on main - each degrades gracefully without its optional backend)
- Semantic "Meaning" search (`core.semantic` - e5 + sqlite-vec, `[semantic]` extra); keyword
  "Text" search remains the fallback.
- Note-linking / related notes (`core.search.related_notes` + `SemanticIndex.related`).
- Near-duplicate / fragment detection + safe merge (`core.dedup` + `ui.duplicates_dialog`;
  merge soft-deletes the dropped note to Trash, never purged).
- Tag consolidation (`core.tagsync` + `ui.tag_consolidation_dialog`; deterministic, model-free).
- Ask-Your-Vault RAG + warm-cache (`core.rag` + `ui.ask_dialog`).
- AI weekly digest in the board (`core.digest`).
- LLM capture routing (`core.llm`: LLMEngine / StubLLM / LlamaCppLLM + `phase2_stubs.CaptureRouter`,
  `[llm]` extra; the LLM is validated + merged onto the parser baseline, never writes directly).
- On-device voice STT seam (`core.stt` TranscriptionService + faster-whisper, `[stt]` extra).
- Break-time framework (`core.breaktime`: scheduler + tier-swap + AC-power guard, `[power]` extra).
  Framework only - registry + gating logic; NOT yet wired into the Qt event loop.

### Optional extras (all OUT of the base; the app runs with NONE installed and degrades)
`[voice]` `[clone]` `[semantic]` `[llm]` `[stt]` `[power]` `[dev]` - five of the seven
(voice/semantic/llm/stt/power) have a matching `requirements-*.txt`; `clone` and `dev` do not.
Model weights are never bundled: the GGUF (and the Piper `.onnx` voices) are user-placed, while
e5 / Whisper / Kokoro / Chatterbox download their model once on first use into the per-user cache.

### Historical context (earlier slices)
- Phase-1 vertical slice was the first runnable PySide6 app in `serenity/`, `python -m serenity`:
  shell (frameless docked always-on-top + tray + single-instance), mascot stage (WebP via QMovie,
  random pose, click-to-pick activity, slot-filling bubble), Todos (NL dates, subtasks, timers,
  recurring, ranking, drag-reorder), Notes-as-md (+ SQLite index, keyword search, color/pin/
  expand/view-raw), Trash, Settings, capture bar + quick modals.
- The Phase-2 seams were first stubbed in `serenity/core/phase2_stubs.py` (CaptureRouter /
  TranscriptionService / SemanticIndex) as real interfaces; the Stage-2 work above filled them in
  with real lazy backends behind those same seams.
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

## Verify next (the remaining work - all Windows-only or real-backend)
**This is the only outstanding work. Stage-1 + Stage-2 are built and on main.**

### A. Native verification (needs a real Windows box - WSL can't show tray/always-on-top)
- Run `python -m serenity` on Windows; confirm right-edge dock, always-on-top, tray,
  WebP animation, autostart HKCU Run entry, single-instance. See README "Verifying on Windows".
- Build the exe: `pyinstaller serenity.spec` on Windows, then walk the native-verification
  checklist in `notes/4_Packaging.md`. The exe build + native checks are Windows-only.
- TTS: install `pip install -r requirements-voice.txt`, drop the Kokoro model + voices and the
  Piper amy/kerstin .onnx into the voices folder, enable in Settings, confirm she speaks EN/DE
  and degrades to silent without the models.

### B. Real-backend verification (the AI backends are STUB-TESTED only)
The 635 tests exercise every Stage-2 feature through deterministic stubs (StubLLM,
StubEmbedder, StubTranscriber, the pure-Python cosine / token fallbacks). The REAL backends
have not been run yet - verify each on a box with the extra + its model present:
- `[llm]` (llama-cpp + a small Qwen3 GGUF in `<config>/models/`): capture routing, RAG answers,
  the weekly digest. Validate the German model (Qwen3-4B vs Gemma 3 4B) on a ~30-utterance
  DE+EN golden set.
- `[semantic]` (fastembed e5 + sqlite-vec): Meaning search, related notes, embedding-path dedup.
- `[stt]` (faster-whisper): a real spoken capture flowing through CaptureRouter.
- `[power]` (psutil): the break-time heavy-job AC guard on a laptop.
- Smoke-test bundling the optional `[llm]` extra into the frozen exe (native llama-cpp DLLs).

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

## Immediate next steps (SUPERSEDED - historical, all done; see "Verify next" above for what's left)
1. Decide **WebP vs GIF** for the animated mascot set (recommend WebP) — see `current_imgs_preview.html`.
2. Lock Serenity's **final look**: pose-per-state mapping + the effect preset (already tuned: holo 64 / aberr 0–5px@4.2s / glow 21@175 / scan 15/2px / noise 36 / poster 16 / glitch 12% / bright -4 / sat +100).
3. Run **writing-plans** to turn the spec into a Phase-1 implementation plan.
4. **Start coding Phase 1** — begin with the **app shell** (tray + docked always-on-top window) so Serenity is on screen early, then todos, then notes-as-files + keyword search, then voice transcription.
5. Before any AI feature: smoke-test **PyInstaller + llama-cpp-python** bundling on a clean Windows box (top risk).
   - DONE (here-buildable groundwork, `wf/packaging`): `serenity.spec` (windowed onedir base exe) pointed at
     a top-level `serenity_launch.py` runner (PyInstaller runs the entry script without package context, so
     `__main__.py`'s relative import would crash the exe), the FFmpeg multimedia DLLs collected explicitly via
     `collect_dynamic_libs('PySide6')`, the frozen-path fix in `core/paths.py` (assets/data resolve under
     `sys._MEIPASS`; config stays per-user) + a second frozen-autostart fix in `ui/platform_win.py`,
     frozen-branch tests (`tests/test_paths_frozen.py`), and the Windows build steps + native-verification
     checklist in `notes/4_Packaging.md`. STILL TODO on a Windows box: run `pyinstaller serenity.spec`, walk
     the checklist, and (later) smoke-test bundling the optional llama-cpp-python extra.
6. Validate the German model (Qwen3-4B vs Gemma 3 4B) on a ~30-utterance DE+EN golden set.

## Open decisions (need user input)
- Resurfacer (resurface old/orphan notes) — RESOLVED: dropped, replaced by the Friday
  Weekly Performance Board (see `core/weekly_board.py`).
- Meeting Recap (local recorded meeting → action items) — Phase 3 or skip?

## Cleanup TODO
- DONE: the loose root build artifacts (`node_modules/`, `render_frames.js`, `encode_webp.py`, `package.json`, `package-lock.json`) now live in `feature/style-studio/` — a self-contained, offline build-time asset tool (NOT shipped in the app), with its own `.gitignore`, `README.md`, and a `stylize.py` one-command wrapper.

## Notes on environment
- Runs on Windows (not WSL). Mockups live in `C:\Users\8417\Downloads\Serenity_Mockups\` and open via `cmd.exe /c start`. The brainstorming companion server is flaky from the Windows browser — prefer the Windows-folder + file:// approach.
