# 1 — Planning (source of truth for "what's next")

_Updated 2026-07-12. Full design: `../docs/serenity-spec.md`. Build spec: `3_Build_Decisions.md`._

## Session wrap (2026-07-12) — Diary slice 1 (SHIPPED, `wf/diary`, PR #8)
- **SHIPPED the Diary slice (1 of 3).** Hybrid day-journal: a non-persisted auto-skeleton (activity spans + completed todos + created notes) woven with manual diary lines, on the **Weekly Board below tracking**, with `◀/▶/Today` week nav. Capture via a `diary:`/`journal:`/`tagebuch:` parser intent (voice-capable, text stored **verbatim** — entities/#tags intact) AND a board line-input. Lines stamped with Phase-C `state_tag`+`context` at save; edit never re-stamps.
- **Architecture:** pure `core/diary.py` (`DiaryStore` over `<vault>/diary.json` mirroring `TodoStore`; `DiaryLine`; pure `build_diary_week`). `Todo.completed_at` (done-grace stamp / reopen-clear / recurrence-unset). Parser `diary` intent + general `Capture.verbatim`. Shell `_commit_capture` diary branch (verbatim add, stamp, board refresh, no tag pollution). Board: anchor+nav, diary section (collapsible days, woven ✓/＋/✎ items, untracked, cross-context marker), line input, inline edit/delete, `safe_refresh` defer guard.
- **Process (full GSD pipeline):** brainstorm (done 2026-07-03) → **flow-harden Workflow** (9 lenses → 35 candidates → adversarial verify → **8 nets folded**: 1 P1 / 3 P2 / 4 P3, spec §10) → 11-task TDD plan → **subagent-driven-development** (Haiku implementers + `uplift`, per-task **Opus** review gate — caught a Friday-auto-open anchor bug, vacuous widget tests, a dead-`clear()`; judgment-heavy UI tasks + test fixes escalated to Sonnet).
- **3-pass QA (Workflow-driven, adversarially verified, fixed+committed between each; suite 1417→1426/5):** criticizer (full 7-lens; **1 Critical** — diary captures reducing to empty title were diverted to slot-filling, fixed at `parser.py:285` + real-`_demo_capture` regression test; **2 Minor** — defer guard now covers the board input, input hidden on past-week views); optimizer (5 behavior-preserving: dead `_window`, subsumed test, import fold, stale headers); test-agent (read-only find → controlled fix: verbatim readback, defer-guard-on-commit, negative-scope, None-context marker — all mutation-verified).
- Suite **1426 passed / 5 skipped** (branch start 1157... no — off phase-h @ 1341; **+85**). 22 commits `20ef705`.. no — `4d7ace8`..`b795c71` on `wf/diary` (off `wf/phase-h-reminders`). Spec `docs/superpowers/specs/2026-07-03-diary-design.md` (§10); plan `docs/superpowers/plans/2026-07-10-diary.md`; flows `notes/5_Interaction_Flows.md` (Area: diary); SDD ledger `.superpowers/sdd/progress.md`.
- **PR #8 OPEN** (`wf/diary` → base `wf/phase-h-reminders` #7): https://github.com/BeMuCa/Serenity/pull/8 . GitNexus reindexed (`b795c71`, 7286 sym / 16357 rels / 273 flows).
- **KNOWN COSMETIC (parked):** Qt `QMouseEvent` DeprecationWarnings in the shared `_dblclick` test helper (codebase-wide Qt6 pattern, not diary-specific) — a separate cleanup, not a diary regression.
- **NEXT:** **Phase D** (business/private/both board toggle — governs tracking AND the new diary section). Then Mood (diary slice 2) → Yearly (slice 3). PR stack #2→#3→#4→#5→#6→#7→#8, merge bottom-up on your call.

## Session wrap (2026-07-08) — Phase H: Reminders (built, `wf/phase-h-reminders`)
- **SHIPPED Phase H — opt-in due-relative reminders.** Per todo you arm any subset of a fixed
  ladder **1 week / 1 day / 1 hour / 30 min / 5 min** before `due`; each armed rung rings as its
  time arrives via **mascot bubble + tray toast + a card banner** (the banner is the durable
  cross-restart surface; bubble/tray are transient). A ring is acknowledged by **Snooze** (defers
  DOWN the ladder; the bottom rung → a repeatable +5 min nudge) or **Dismiss**. Snooze NEVER moves
  the todo's `due`. Cross-context rings stay **privacy-blurred** (relative time only, no title) and
  are snoozed/dismissed WITHOUT revealing — extending urgency-peek's `PeekPlaceholder`.
- **Architecture:** pure clock-injected `core/reminders.py` (mirrors `core/breaktime.py`):
  `RUNG_MINUTES`/`RUNG_LABELS`, `snap_to_rung`, `armable_offsets`, `relative_phrase` (en/de),
  `tick` (guard→nudge→collapse), `acknowledge_snooze`/`acknowledge_dismiss`/`silence`/`arm`
  (delta semantics), `pre_mark_past`. Four tolerant `Todo` fields (`reminder_offsets`/
  `reminder_fired`/`reminder_active`/`reminder_nudge_at`; JSON-additive, NO migration). Shared
  `ui/reminder_picker.py` (card 🔔 + QuickTodoDialog + calendar slot). Ring banner on TodoCard +
  PeekPlaceholder. Shell 60 s scheduler + immediate cold-launch + `_on_resume` catch-up; one
  `_reminder_msg` helper is the SINGLE cross/in-context privacy copy rule. NL capture: parser
  `reminder` intent extracts an offset ("1 day before" / "1 Tag vorher") → `snap_to_rung` → `arm`.
- **Process (full GSD pipeline):** brainstorm (1-question-at-a-time, decisions locked) → **flow-harden
  (2 Workflow passes: 8 lenses + critic → adversarial verify → dedup): 76 candidates → 17 confirmed →
  13 requirements + 3 clarifications** folded into the spec, incl. **2 P1 privacy leaks** (title-less
  voice bucket; context-flip must re-blur the bubble) and **2 real §3 logic bugs** (arm-drops-dismissed;
  snooze-to-past clarified as intended escalation) → spec + **14-task TDD plan** → **subagent-driven
  implement: Haiku implementers (+ the new `uplift` skill as start-input) with a Sonnet task-review
  gate after every task.** The gate earned its keep — the pure-core tasks (T1–T4) each shipped exactly
  one Critical that review caught (coercion-bypass crash, broken interface contract, spurious re-ring
  of acknowledged rungs, sentinel-loss); UI tasks surfaced a vacuous P1 privacy test, a re-speak-on-flip
  bug, a double-save, dead styling. All fixed + re-reviewed.
- Suite **1331 passed / 5 skipped** (was 1157 at branch start; **+174**). Commits `20ef705`..`b06edf0`
  on `wf/phase-h-reminders` (off `wf/urgency-peek`). Spec `docs/superpowers/specs/2026-07-06-phase-h-
  reminders-design.md`; plan `docs/superpowers/plans/2026-07-07-phase-h-reminders.md`; SDD ledger
  `.superpowers/sdd/progress.md`.
- **NEW meta-artifact:** `.claude/skills/uplift/SKILL.md` — TDD'd implementation-discipline skill for
  delegated/lower-tier coding agents (baseline-before-claim, proof for "pre-existing", copy-pasted
  counts, no silent interpreter substitution). Memory: `haiku-implementer-uplift-pipeline`.
- **QA PIPELINE DONE (2026-07-10, all 3 passes Workflow-driven, adversarially verified, fixed +
  committed between each; suite 1331→1341/5, +10):**
  - **criticizer** — 9 findings → 5 confirmed → **3 distinct bugs**, all with TDD regression tests
    (`5249e57`): **P1** — `_reassert_ring_bubble` re-blurred only the *visible* mascot on a context
    flip → the hidden mascot leaked a cross-context title on mode re-entry (fix: clear both mascots);
    **High** — arming via NL capture / QuickTodoDialog / calendar-slot never called
    `_sync_reminder_timer`, so a reminder silently never fired that session (fix: sync on all 3
    paths); **Med/R-12** — ICS re-import due-edit left a stale active ring (fix: silence on due
    change). 4 findings adversarially refuted (all sound).
  - **optimizer** — behaviour-preserving (`da595d5`): extracted `ranking.is_cross_context` (4 inlined
    copies → 1), collapsed the NL-commit double-save, corrected the false `fr[ue]her` parser comment,
    dropped 2 duplicate tests. Declined a premature `_order_fired` helper + a near-zero dead-guard.
  - **test-agent** — worktree mutation experiments, 9 findings, 0 refuted, every fix
    mutation-spot-checked (`d5c0745`, test-only): +6 tests (snooze consumed-rung, de-overdue hours,
    pre_mark_past boundary, parser "in advance", tick fault-injection) + **de-vacuumed 3 tests that
    lied about what they guarded** (two never wired a real state filter so the R-4 bypass was never
    reached; the card "e2e" bypassed the real commit path). Fixed the pre-existing `note_draft`
    all-digit-uuid→YAML-int flake (quoted the id in all 7 `promote()` calls).
- **DONE (2026-07-10):** GitNexus reindexed (`0da603a`, 6932 sym / 15509 rels / 265 flows) +
  **PR #7 OPEN** (`wf/phase-h-reminders` → base `wf/urgency-peek` #6):
  https://github.com/BeMuCa/Serenity/pull/7 . Stack #2→#3→#4→#5→#6→#7, merge bottom-up on the
  user's call. **NEXT:** the **Diary slice** (spec ready) → Phase D. **Parked P3/cosmetic (not fixed):** card bell fill/count indicator (spec §4.1 descriptive,
  de-scoped in Task 9); the `fr[ue]her` regex branch is typo-only (matches `fruher`/`freher`, not the
  umlaut) and effectively removable.

## Session wrap (2026-07-03) — Phase C + Diary designed & spec'd (docs only, `wf/phase-c-state-tag`)
- **Phase C design LOCKED via brainstorm** (user decisions: BOTH filter axes; `state_tag` = stable registry
  KEY; context ALWAYS set at creation — fresh vault, no legacy data, no migration; derived items INHERIT
  the parent's stamp). Grounded by a 6-reader recon Workflow.
- **Flow-harden Workflow:** 7 flow lenses → 34 candidates → adversarial verify (26 confirmed, 1 refuted;
  7 verifies + synthesis hit the session usage limit — 4 were dups, the 3 real ones verified INLINE next
  day, all confirmed) → **deduped to 16 requirements (10 P2 / 6 P3)** folded into the spec. Notable: the
  chip-on-context-flip conflict resolved (visible+unchecked); AI surfaces (related/Ask/duplicates) filter
  CANDIDATE lists while `semantic.index()` stays full-corpus (prune caveat `phase2_stubs.py:316`); calendar/
  graph/mini get the context axis; the note SQLite index deliberately untouched (write-only cache, no
  schema-version mechanism until Phase I). Spec: `docs/superpowers/specs/2026-07-03-phase-c-state-tag-design.md`.
- **Diary (NEW, slice 1 of 3) brainstormed + spec'd:** hybrid auto-skeleton (derived from activity spans +
  todos completed + notes created; never persisted) + manual lines in an own `<vault>/diary.json` store;
  capture = `diary:`/`journal:`/`tagebuch:` parser intent (voice too) + a Board input; surface = **Weekly
  Board below the tracking** + ◀▶ week navigation (groundwork for the yearly review); adds
  `Todo.completed_at` (stamped at done-grace commit). Spec: `docs/superpowers/specs/2026-07-03-diary-design.md`.
  **Build order: C → Diary → D** (Phase D's board toggle then governs the diary section too).
- **Slices recorded:** Mood (slice 2, own brainstorm later: mascot 1-tap mood ask via bubble, weekly strip
  on the Board) → Yearly review (slice 3: year view of tracking+diary+mood on the week-nav groundwork).
- **FUTURE FEATURE IDEA (saved, do NOT build yet):** ML correlation of state × mood × diary metrics
  (entry length, sentence length, entries/day, time-of-day) — local-only, needs months of accumulated data.
- **BUILT (same day, /goal autonomous — user waived the review gates):** 10-task TDD plan
  (`docs/superpowers/plans/2026-07-03-phase-c-state-tag.md`, `c3e4fa5`) executed inline T1→T9:
  model stamps + tolerant coercion, `key_for_label`/`visible()`, store passthrough + recurrence
  inherit, `Shell.stamp()` + all direct funnels (save-time; capture snapshot), derived funnels +
  ICS context threading, the state chip + two-axis list filtering + grace/hint nets, cross-surface
  context (calendar/graph/mini + visible-tab flip fan-out), AI-surface candidate filtering
  (full-corpus index kept) + trash suffix, fm-editor stamp round-trip. Suite **1100 passed / 5
  skipped** (was 1041; +59). **Debug note:** an unconditional hidden-tab refresh in the flip
  fan-out SEGFAULTED the offscreen suite (QGraphicsScene churn) — bisected via file-revert
  probes; fixed by refreshing only the visible tab (hidden tabs self-heal on `switch_tab`).
- **QA pipeline DONE (all 3 passes, Workflow-driven, adversarially verified, fixed between):**
  - **criticizer** — 7 confirmed / 3 refuted. MED (correctness): AI surfaces indexed the FULL
    corpus but re-projected onto context-filtered candidates with a small fixed top_k → other-
    context notes could crowd out in-context Ask/Related/Duplicates hits. Fix: `SemanticIndex.
    population()` + over-fetch the full ranking in `related_notes`/`rag._retrieve`/
    `dedup._duplicate_pairs_semantic`, re-project, truncate. LOW: cancel-grace left a stale
    foreign-context card → `_cancel_grace` rebuilds when filtered out. + R11/R10/R5/R13 coverage.
  - **optimizer** — 1 accepted / 4 rejected (correctly declined a premature filter-helper
    abstraction). Collapsed `visible()`'s mutate-then-test into one guard.
  - **test-agent** — 5 confirmed / 6 refuted mutation-survivors killed (related_notes top_k
    truncation, notes-side state axis, R5 chip-only gating, chip registry color, notice title-
    leak). Each fix mutation-spot-checked (fails under mutant, passes clean).
  - Suite **1115 passed / 5 skipped** (was 1041 at branch start; +74). 19 commits on
    `wf/phase-c-state-tag`; GitNexus reindexed (known stale by 1 commit, docs-only auto-block).
- **NEXT:** push `wf/phase-c-state-tag` + open PR #5 (base=phase-b-context) — DEFERRED to the
  user. Then the **Diary slice** (spec ready: `docs/superpowers/specs/2026-07-03-diary-design.md`;
  build order C → Diary → D). Merge the PR stack #2→#3→#4→#5 bottom-up on the user's call.
  Branch chain: `main` ← ship-wave (#2) ← phase-a-states (#3) ← phase-b-context (#4) ←
  **phase-c-state-tag** (built + QA'd, not pushed).

## Session wrap (2026-07-03, same session) — Urgency-peek (built, `wf/urgency-peek`)
- **User idea → two features:** "filter todos using the chip" surfaced (a) todos already
  hard-filter (Phase C) BUT urgency doesn't override the filter — an urgent off-state/off-context
  todo gets buried; and (b) reminders don't exist at all (the parser's `reminder` intent is just
  a due-dated todo; `deadline_near`/`timer_due` voice lines are dormant = the unbuilt Phase H).
  User chose: **peek tweak now, reminders (Phase H) next.**
- **Urgency-peek SHIPPED** (specs/plans `2026-07-03-urgency-peek*`; flow-harden Workflow: 14
  candidates → 7 deduped reqs R-A..R-H, incl. the boundary-timer gap, the grace×peek collision,
  the two-click confirm anti-mis-click guard, due-less placeholder forms, and the mini-dock
  "All clear" lie). Core: `ranking.peek_class` + `format_time_left` (relative-only). UI:
  `peek_placeholder.py` (blurred widget + shared `blurred_line`), TodosView classification +
  `_boundary_timer`, `Shell._on_resume` refresh + `reveal_context`→`set_context`, mini peek line.
  **Blurred surface never shows title/tags/absolute times/None/elapsed seconds.**
- **QA pass ran INLINE** — the criticizer Workflow's 3 finder agents all died on the session
  subagent limit (reset 15:10 CEST), so the three lenses ran inline (Phase-A precedent): no
  correctness bugs confirmed (boundary-timer thrash impossible — hide+due ⇒ due > 4 h ⇒ boundary
  always positive; `_cancel_grace` guard composes with peeks; reveal-lambda/mini-sentinel/invalid-
  context paths checked); optimizer: unified `ranking.*` module-qualified imports in todos_view;
  test-agent: +3 hardenings (R-C hint non-count, mini tooltip privacy, boundary-timer earliest-
  crossing min→max mutant killer). **OPEN: consider re-running the QA Workflow after the limit
  resets for fully-independent adversarial coverage** (inline = same eyes that wrote the code).
- Suite **1149 passed / 5 skipped** (was 1115 at branch start; +34). 10 commits on
  `wf/urgency-peek` (off phase-c-state-tag), not pushed. GitNexus reindexed (6362 symbols).
- **PUSHED + PRs OPENED (2026-07-03):** PR **#5** `wf/phase-c-state-tag` (base #4) + PR **#6**
  `wf/urgency-peek` (base #5). Stack: #2→#3→#4→#5→#6, merge bottom-up on the user's call.
  **Independent agentic QA rerun DONE** (5 lenses, 17 agents, adversarially verified): 11
  confirmed / 1 refuted — the fresh-eyes pass caught what inline QA missed (mocked-out R-D
  gate, untested 24h cap/soonest-due pick, and a real LOW bug: boundary-timer/resume refresh
  tearing down in-flight inline edits/drags → fixed with `safe_refresh` defer + `drag_active`
  signal; `needs_tick` now due-dated-only; `blurred_line` derives its own label). All fixes +
  8 test hardenings pushed to PR #6. Suite **1157 passed / 5 skipped**. LESSON: inline QA is
  a stopgap — the independent rerun found 11 things it missed; always re-run agentic QA after
  a limit-forced inline pass.

### Phase H seed — REMINDERS (brainstorm FIRST THING next session; user-chosen next)
**User ask (verbatim intent):** calendar items / due todos get a reminder option — a due-relative
ladder **1 week / 1 day / 1 hour / 30 min / 5 min** — "with the possibility to push the reminder
along this line downwards" (snooze/defer steps DOWN the ladder). From a blurred cross-context
peek you can snooze WITHOUT revealing; to see what the item is you must switch context.
**Ground truth (verified this session):**
- NO reminder mechanism exists. The parser's `reminder` intent ("Erinnerung/remind me") just
  routes to a todo with a due date — the flag isn't even persisted on `Todo`.
- Two mascot voice lines sit DORMANT for this: `deadline_near` + `timer_due`
  (`serenity/data/voice_lines.json`) — nothing fires them yet.
- Ranking already floats urgency (tier 2 at ≤4 h, tier 3 at ≤30 min/overdue/timer) and
  **urgency-peek** (just shipped) surfaces urgent todos through the context/state filter.
**Anchors already built for H:** `PeekPlaceholder` (spec says it gains `[snooze ▾]`) + the mini
peek line; `ranking.format_time_left` (relative-only, privacy-safe) for reminder copy.
**Locked decision:** snooze defers the REMINDER down the ladder — it never moves the todo's
actual `due` (the due-defer alternative was explicitly rejected).
**Open design Qs for the brainstorm:** default ladder vs per-todo opt-in + where offsets are set
(QuickTodoDialog? calendar slot dialog? card?); fire surface (mascot bubble via the dormant
lines; tray notification too?); persistence shape (reminder offsets + fired/snoozed state on
`Todo`, ics_uid-pattern tolerant round-trip — schema change ⇒ mind Phase I before release);
scheduler (shell QTimer vs a pure core scheduler seam like breaktime's); blurred-snooze UX;
NL capture ("remind me 1 day before"); the roadmap's old H sketch (due-15m/due-5m) is
SUPERSEDED by the ladder — H's other item (NL todo editing) stays separate.
**Queue after H:** Diary (spec ready) → Phase D (board context colors) → E… (roadmap unchanged).

## Session wrap (2026-07-01) — Phase B: global context toggle (built, `wf/phase-b-context`)
- **SHIPPED Phase B — the Private↔Business context toggle.** Flipping context swaps the mascot
  selector's activity set, shows a per-context "mood" idle pose, and persists `current_context` —
  from **three entry points**, all kept in sync: a **title-bar button**, an **in-ring bubble**
  (`→ Private`/`→ Business`), and a **tray right-click menu** item.
- **Registry:** +8 Private activities (`Chilling/Friends/Girlfriend/Music/Learning/Code/Eat/Gaming`,
  `context="private"`); `CONTEXT_DEFAULT_POSE={"business":"idle","private":"chilling"}`;
  `selector_rows(states, context=None)` filters to one context + the neutral Idle. `Settings`
  gains `current_context` + a `context()` guard + a load-time heal. `Shell.set_context`/`_sync_context`
  re-syncs title-bar/tray/**both mascots** (shell + mini) with the mood pose (idle only). **Context is
  a property of the activity, not the moment** — a running span is KEPT on flip (counts as its own
  context's time); mood pose skipped while tracking.
- **Process (full pipeline):** brainstorm → flow-harden Workflow (7 flows → 21 candidates → **11
  confirmed** [0 P1 / 8 P2 / 3 P3, deduped to 8], folded) → spec + 6-task TDD plan → TDD implement →
  QA Workflow (**6 confirmed**: a MED boot-order bug — `_sync_context` ran before `_build_tray`
  created the tray action; + mini-mood-on-create; + coverage). Both audit passes adversarially
  verified. A test-isolation leak (shared vault activity.json) fixed.
- Suite **1040 passed / 5 skipped** (was 1021 at Phase-A tip; +19). Commits `cf5840b`..`faa0085` on
  `wf/phase-b-context` (off `wf/phase-a-states`). Docs: `docs/superpowers/*/2026-07-01-phase-b-*`.
- **NEXT — Phase C: `state_tag` on notes+todos** — auto-apply the current state on creation +
  a deselectable filter chip (Notes + Todos). Optional `state_tag`+`context` on Note (front-matter +
  index col) and Todo. Depends A+B (done). Then Phase D (board context colors — folds in the user's
  "business/private/both" Weekly-Board toggle request).
- **Open:** PR for `wf/phase-b-context` (stacks on PR #3 → #2). Branch chain: `main` ← ship-wave (#2)
  ← phase-a-states (#3) ← phase-b-context (#4).
- **xhigh code-review (2026-07-01):** 5 findings. Fixed 2 CONFIRMED cleanups in `set_context`
  (no-op guard + accurate coercion comment, `41bb61e`). 1 CONFIRMED left as intended (flipping
  context replaces a transient reaction pose with the mood pose — deliberate feedback). **DEFERRED
  to Phase E** (unreachable until the registry editor exists; `activity_states` is `[]` today):
  (a) a user-edited registry that drops all of a context's activities → empty selector ring (the
  editor should block emptying a context or show a hint); (b) an override missing the `chilling`
  key → the private mood pose silently degrades to idle. The Phase-E editor must keep
  `CONTEXT_DEFAULT_POSE`'s keys + each context non-empty.

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

Recommended order: A -> B -> C -> Diary slice -> D -> E -> F -> G; H interleaved as fast value;
Mood + Yearly-review slices after Diary (see the 2026-07-03 wrap); I before any release that
ships the new schema (C). Each phase gets its own bite-sized TDD plan when started.

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
