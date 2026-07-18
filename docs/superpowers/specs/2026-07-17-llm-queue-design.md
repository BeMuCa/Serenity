# LLM Job Queue + Working Indicator — Design Spec

_Date: 2026-07-17 · Infra project "A" (prerequisite for the Meeting-Prep feature "B") · Branch `wf/llm-queue` (off `wf/diary` tip)._
_Status: approved design (brainstormed 2026-07-17); source for the flow-harden + TDD plan._

## 1. Goal

Run all queued LLM work **off the UI thread**, **serialized** through a single worker (the `llama` model is a per-process singleton and cannot run concurrent inferences), with a **visible "working" indicator** and a **hidden inspector panel** where the user can watch the queue and **pause / prioritize** pending jobs. This also fixes today's real freezes: digest, RAG, and task-lines all call `llm.generate()` synchronously on the Qt main thread (`weekly_board_view.py:90` even documents "multi-second inference on the Qt main thread").

Scope: the **executor + indicator + inspector**, plus migration of the two **non-interactive** consumers (Weekly-Board digest, break-time task-lines). RAG/Ask (interactive) is a **non-goal** here (its async "thinking→answer" UX is a separate spec). The Meeting-Prep feature is project B and rides on this queue.

## 2. Executor (`core/llm_queue.py`, Qt-free core + a thin Qt worker in `ui/`)

- **Job model** `LlmJob{id: str (uuid4 hex), label: str, run: Callable[[LLMEngine], str], on_done: Callable[[str], None], on_error: Callable[[Exception], None], state: JobState}`. `label` is the human-readable line shown in the inspector ("Weekly digest", "Preparing your 10:00 standup"). `run` receives the shared LLM and returns its text; it must NOT touch Qt (it runs on the worker thread).
- **`JobState`**: `PENDING | PAUSED | RUNNING | DONE | FAILED`.
- **Queue logic** (pure, headless-testable, Qt-free): an ordered list of jobs + operations `submit(job)`, `pause(id)`, `resume(id)`, `prioritize(id)` (move to front of PENDING), `pause_all()` / `resume_all()` (global), `next_runnable()` (first PENDING job, or None if globally paused / none runnable), `snapshot()` (running + ordered pending/paused, for the inspector). This is a deterministic data structure with no threads — fully unit-tested.
- **Worker (`ui/`, Qt)**: a single `QThread` that loops — ask the queue for `next_runnable()`, run its `run(llm)` off-thread, then deliver `on_done`/`on_error` **on the UI thread via a Qt signal**. If nothing is runnable, it waits (condition/event) until a `submit`/`resume`/`prioritize` wakes it. The worker owns access to the LLM so all inference is serialized on this one thread.
- **Serialization guarantee:** exactly one `run` executes at a time; `submit` while running enqueues; `prioritize` reorders only the PENDING set (the RUNNING job is not interrupted — see §5).

## 3. Submission policies (two, same queue)

- **Immediate:** interactive/passive triggers submit right away and run as soon as the worker is free (e.g. the board digest on board-open; meeting-prep on demand).
- **Off-time:** the existing `BreakScheduler` becomes a **submitter** — its heavy jobs (meeting-prep in project B) call `queue.submit(...)` during idle instead of running `llm.generate` synchronously in the break tick. The queue then executes them off-thread. (This spec migrates **task-lines** to submit-through-queue; meeting-prep submission is project B.)

## 4. Working indicator + hidden inspector (`ui/`)

- **Mascot pose:** while the queue has a RUNNING (or runnable PENDING) job, the mascot holds a **"thinking"** pose (reuses `states.py` "thinking"); when the queue goes idle it reverts to the current **context mood pose** (re-assert via the existing `_sync_context` mood path). Precedence: the busy pose holds over transient reaction poses until the queue drains; a context flip still re-asserts mood (and, if still busy, the thinking pose re-applies).
- **Status line:** a subtle "thinking…" line near the mascot dock, shown ONLY while the queue is non-empty (truly hidden when idle). It is the click target that opens the inspector.
- **Hidden inspector panel:** opened from the status line (a deliberate open, not always visible). Lists the **running** job (label + a spinner) and the ordered **pending/paused** jobs (label + state). Per-job controls: **Pause / Resume** (a PENDING↔PAUSED toggle) and **Prioritize** ("play next" — move to the front of PENDING). A **global Pause/Resume** stops/starts draining after the current job. The RUNNING job shows as running but has no pause (see §5).

## 5. Running-job limitation (explicit)

An in-progress `llm.generate()` is a blocking token stream and cannot be paused mid-inference. So: **pause/prioritize act on PENDING jobs**; a **global pause** stops the worker from picking the *next* job (the current one finishes); the RUNNING job always runs to completion. **Aborting a running inference** (via a llama abort-callback) is a documented **future option**, not v1.

## 6. Migration (passive consumers)

- **Weekly-Board digest** (`digest.generate_digest`, called from `weekly_board_view.refresh`): instead of the synchronous call, the board renders its deterministic hints immediately and **submits a digest job**; when the result signal arrives it swaps the AI card in (guarding against a stale anchor/week — only apply if the board is still on the same current week). Kills the main-thread freeze.
- **Break-time task-lines** (`task_lines.generate_task_lines`, the `maintenance.py` HEAVY job): the break job **submits to the queue** rather than running `generate` inline in the (main-thread) break tick.
- **RAG/Ask**: unchanged (synchronous) — deferred.

## 7. Robustness / lifecycle

- **In-memory queue** — jobs are lost on restart; off-time jobs simply re-submit next idle. No persistence in v1.
- **Failure:** a `run` that raises is caught → `on_error` on the UI thread → the job is marked FAILED and dropped from the active queue; the worker continues; the mascot still reverts on drain. The inspector may briefly show a failed job.
- **Shutdown:** on quit, signal the worker to stop; an in-flight inference is **abandoned** (do not block quit on it). No new jobs picked up.
- **Dedup:** `submit` may replace/skip a job with a duplicate id or an already-pending identical label (e.g. don't queue two digests for the same week) — a light guard, mirroring `BreakScheduler.register` dedup.

## 8. Components / isolation

- `core/llm_queue.py` — Qt-free: `LlmJob`, `JobState`, and the pure `LlmQueue` data structure (submit/pause/resume/prioritize/pause_all/next_runnable/snapshot). Headless-tested.
- `ui/llm_worker.py` — the `QThread` worker + result/error Qt signals; owns the LLM handle.
- `ui/llm_inspector.py` — the status line + the hidden inspector panel widget (reads `snapshot()`, calls the queue ops).
- `ui/shell.py` — wires the queue + worker, brackets the mascot busy/idle, and routes digest + task-lines submissions.

## 9. Non-goals (v1)

RAG/Ask migration · aborting a running inference · queue persistence across restarts · the Meeting-Prep feature itself (project B) · multi-worker / GPU parallelism · reordering the RUNNING job.

## 10. Testing map

- **Queue (headless):** FIFO order; submit-while-running enqueues; pause skips a pending job; resume restores order; prioritize moves to front of pending; pause_all/resume_all; next_runnable respects paused + global-pause; snapshot shape.
- **Worker (offscreen, fake LLM):** runs off the UI thread; exactly one job at a time (serialization under concurrent submits); result + error delivered on the UI thread; wakes on submit/resume/prioritize; clean stop on shutdown (in-flight abandoned).
- **Indicator:** thinking pose while non-empty → mood revert on drain; precedence vs a context flip; status line hidden when idle, shown when busy; clicking it opens the inspector.
- **Inspector:** lists running + ordered pending/paused by label; Pause/Resume/Prioritize + global pause mutate the queue as shown.
- **Migration:** board renders hints immediately + swaps digest in on the result signal (and NOT if the week/anchor changed); task-lines submits to the queue instead of inline generate.
- **Failure:** a raising job → on_error fired, job FAILED, queue continues, mascot reverts.
- Gate: full headless suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`).

## 11. Flow-harden folds (2026-07-18)

_Pre-code flow-harden pass (method: `notes/5_Interaction_Flows.md`). Every gap below was adversarially verified against the real source (9 lenses → dedup → default-refute verify → synthesis); only CONFIRMED/REVISED P1+P2 are folded as requirements here, P3 is parked, REFUTED is dropped (see `notes/5` "Area: llm_queue"). Counts: 4 P1, 7 P2, 8 P3, 6 refuted (19 confirmed)._

### P1 — must fold before build

**11.1 — LlmQueue's shared job list has no lock (§2, §8)** · P1 · M (nearer S: one lock, ~8 methods, one test)
- **Gap:** §2 (line 16) calls the queue "a deterministic data structure with no threads", but §2 line 17 has the worker `QThread` call `next_runnable()` every loop while the UI thread calls `submit`/`pause`/`resume`/`prioritize` from inspector clicks (§4/§8) and migration code (§6). Both do compound *find-then-mutate* sequences on one Python list. The GIL makes single ops atomic, not these — an interleaved pair can pop/reorder a **different** job than the user clicked, or raise `IndexError` when a stale index hits a list the other thread already shrank (kills the drain loop → frozen indicator). The "no threads" framing would steer the implementer to skip the lock entirely.
- **Net:** Give `LlmQueue` one internal `threading.Lock`; every public method (`submit`/`pause`/`resume`/`prioritize`/`pause_all`/`resume_all`/`next_runnable`/`snapshot`) acquires it for its **entire** body, including the find+mutate steps. Add a concurrency test that hammers `pause`/`prioritize` from one thread while a fake worker loop calls `next_runnable()` from another and asserts no lost/duplicated/misrouted jobs.
- **Anchors:** `docs/superpowers/specs/2026-07-17-llm-queue-design.md:16-17`, `:29`, `:52`; project's own thread-safety bar at `serenity/ui/shell.py:691-694`.

**11.2 — Worker thread and synchronous RAG/Ask race the same shared `LlamaCppLLM` (§2, §6, §9)** · P1 · M
- **Gap:** §2 line 17 asserts "the worker owns access to the LLM so all inference is serialized on this one thread" — but RAG/Ask stays synchronous on the main thread (§6 line 39, §9 line 57) and is a second, never-migrated caller of the identical shared instance (one `LlamaCppLLM` injected at `shell.py:202` into both board and notes_view; the class-level `_shared` Llama is a per-process singleton). `core/llm.py`'s `generate()`/`_llama()` have no lock; the llama wrapper mutates unsynchronized per-instance state (`n_tokens`, `input_ids`, `scores`, KV-cache) per call. Two threads racing it → garbled output guaranteed for one caller, native segfault a realistic secondary. The design introduces this second concurrent path itself (pre-spec, `generate()` is main-thread only, so a race is structurally impossible today).
- **Net:** Put a single process-wide lock around the one seam every caller already goes through (`LlamaCppLLM.generate()`/`_llama()` in `core/llm.py`), not "trust the worker is the only caller". Main-thread caller (RAG) takes it **non-blocking**: if the worker holds it, `generate()` returns empty so `rag.answer_question`'s existing except-degrade path (`rag.py:242-244`, already tested "inference error → sources-only") fires — no new UI state. The worker takes it blocking (harmless, already serialized). This same lock also closes the cold-start double-load race in `_llama()` (two threads each constructing a Llama, doubling peak RAM), and covers the router (also main-thread, also unmentioned) for free.
- **Anchors:** `docs/.../2026-07-17-llm-queue-design.md:17`, `:39`; `serenity/core/llm.py:137-139`, `:184-204`, `:206-235`; `serenity/ui/ask_dialog.py:138-159`, `serenity/ui/notes_view.py:547-558`, `serenity/ui/shell.py:202`.

**11.3 — App quit can destroy a still-running worker QThread → crash on exit (§7)** · P1 · M
- **Gap:** §7 (line 45) gives only the logical outcome ("an in-flight inference is abandoned; do not block quit on it") with **no disposal mechanism**. `QApplication.quit()` returns immediately; `main()` returns and the Shell (and the worker QThread it owns) is GC'd while the OS thread is still blocked inside `llm.generate()`→`create_chat_completion` (`llm.py:206-235` — one blocking call, no cancel hook). Qt's QThread destructor calls `terminate()` on a still-running thread — unsafe mid-native-call, can crash/corrupt. This is the **first QThread** in the codebase (existing background work is fire-and-forget daemon threads), so no teardown pattern to inherit; `_quit()` (`shell.py:1316-1328`) has zero worker-thread teardown today. Since `_quit()` runs all `*_store.save()` first, this is a dirty-exit crash — notably on the shipped Windows `.exe` — not data loss. Plausible timing: the Friday board auto-open starts the digest right when the user brings the app forward and may also quit.
- **Net:** In `_quit()`, before `QApplication.instance().quit()`: set a stop flag + wake the worker's wait condition, `thread.quit()`, then `thread.wait(bounded_timeout_ms)` — mirroring the existing `break_timer.stop()`/`mini.close()`/`_close_expanded()` steps. If still running after the timeout, do **not** let Python destroy the QThread wrapper (stash it in a module-level list so GC never collects it); let the OS reap the thread on process exit instead of hitting Qt's `terminate()`-on-destroy.
- **Anchors:** `serenity/ui/shell.py:1316-1328`; `serenity/__main__.py:47-51`; `serenity/core/llm.py:206`, `:227`; `docs/.../2026-07-17-llm-queue-design.md:45`, `:53`.

**11.4 — Async digest `on_done` re-render can destroy an in-flight diary edit (§6)** · P1 · S
- **Gap:** §6 (line 37) says the result "swaps the AI card in". The natural reading — a bare `self.refresh()` — runs `refresh()`'s `deleteLater` loop (`weekly_board_view.py:201-205`), tearing down every `self._body` widget, including an active inline diary-line editor (`:507-520`) or a half-typed capture input (`:361-368`) and its uncommitted text. Silent data loss, triggered by a background LLM completion the user did not initiate. The view already has `safe_refresh()` (`:242-256`) built for exactly this class of **input-uncorrelated** trigger (Friday auto-open, capture-bar diary commit); an async digest delivery is precisely such a trigger, but §6 never routes through it. Today the whole call is one blocking `generate_digest()` that can never interleave with an edit — so this hazard is newly introduced by the migration.
- **Net:** Deliver the digest via a **targeted splice** that inserts only the digest card (`insertWidget(0, self._digest_card())`) under the existing focus/defer guard. Note `safe_refresh()` **alone** is insufficient because `refresh()` still calls `generate_digest()` synchronously (`:225-227`) — a deferred `refresh()` would re-freeze; the splice is the sound option.
- **Anchors:** `serenity/ui/weekly_board_view.py:242-256`, `:201-205`, `:361-368`, `:507-520`; `docs/.../2026-07-17-llm-queue-design.md:37`.

### P2 — fold into the spec

**11.5 — Worker check-then-sleep is not atomic against a concurrent submit (lost wakeup) (§2)** · P2 · S
- **Gap:** §2 line 17 says the worker "waits (condition/event) until a submit/resume/prioritize wakes it" but specifies no check-then-sleep discipline (which primitive, or the wait/notify ordering). A `submit` landing between the worker's "nothing runnable" check and "go to sleep" is missed: the job sits PENDING indefinitely, reintroducing exactly the freeze this feature exists to kill — visibly (mascot stuck "thinking", inspector showing a Pending job that never advances). First producer/consumer in the codebase, no pattern to crib.
- **Net:** Specify a `threading.Condition` sharing the **same lock** as 11.1: the worker's "`next_runnable()`, then wait" happens under that lock (`Condition.wait()` atomically releases+reacquires it); every mutator calls `notify()`/`notify_all()` while still holding the lock after mutating.
- **Anchors:** `docs/.../2026-07-17-llm-queue-design.md:17`, `:28`, `:62`.

**11.6 — An exception in the per-job `on_done`/`on_error` consumer suppresses the busy-pose revert (§7)** · P2 · S
- **Gap:** §7's failure isolation is scoped only to `run()` ("a run that raises is caught → on_error…"); it says nothing about isolating the **invocation** of `on_done`/`on_error` itself. The digest `on_done` does real Qt work (card swap + stale-week guard) that can raise. If the delivery slot checks "queue empty → revert mascot" **after** invoking the callback in the same function (permitted; spec is silent), an exception aborts before the revert, leaving the mascot stuck "thinking" though the queue drained — worse, `_sync_context` re-applies "thinking" while still busy, so it never self-heals. The codebase already isolates this class (`breaktime.py:241` "a job must never crash the scheduler / its siblings"; `shell.py:703-704` double-wraps that tick).
- **Net:** In the worker's delivery slot, wrap the callback invocation in its own try/except (log + swallow) and run the queue-empty/mascot-revert check in a `finally` — mirroring BreakScheduler's per-job isolation.
- **Anchors:** `serenity/core/breaktime.py:221-222`, `:241`; `serenity/ui/shell.py:247`, `:703`; `docs/.../2026-07-17-llm-queue-design.md:17`, `:27`, `:44`.

**11.7 — Friday auto-open speaks a stale/empty digest before the async job finishes (§6)** · P2 · M
- **Gap:** `_maybe_auto_open_board` (`shell.py:650-672`) calls `switch_tab('board')` then, on the next line, synchronously reads `comment = self.board_view.digest_text()` for the mascot to speak — the comment at `shell.py:665-667` states the assumption ("switch_tab already refreshed the board, so digest_text() is the freshly-built digest"). Once `refresh()` submits a job and returns immediately, `digest_text()` still holds the **pre-refresh** `_digest` (empty on first-ever open, stale/cached otherwise). Every Friday auto-open speaks the stale line instead of the freshly-authored one — a near-certain miss after a week of new activity, not a rare race. §6 audits only `refresh()`'s internals, never this downstream consumer.
- **Net:** Speak the **deterministic hint** (the `generate_digest` fallback / board hints) as the interim line, then re-speak/update via the digest completion signal (the same mechanism §6 uses for the card swap) once `_digest` is set — or defer the AI line until then.
- **Anchors:** `serenity/ui/shell.py:663-672`, `:472`; `serenity/ui/weekly_board_view.py:191-197`, `:225-227`; `serenity/core/digest.py:151-180`.

**11.8 — Busy-pose revert-on-drain is a no-op whenever an activity/Focus session is tracked (§4)** · P2 · M
- **Gap:** §4 says the busy-pose revert re-asserts mood "via the existing `_sync_context` mood path". That path is idle-gated: `idle = self.activity_store.running() is None`, and the `set_state(CONTEXT_DEFAULT_POSE[ctx])` reassertion sits inside `if idle:` (`shell.py:941-945`). Starting **any** activity (including a Focus Pomodoro, which keeps the span open across work+break) makes `running()` non-None, so a digest/task-lines job draining during normal tracked work leaves the mascot stuck "thinking" while the status line has hidden — a visible app-says-idle/mascot-looks-busy desync with no self-correction until the next reaction pose or queued job.
- **Net:** Give the busy bracket its own revert target: on drain restore whichever pose was active before the bracket started — tracked-activity pose if `activity_store.running()` is non-None, else `CONTEXT_DEFAULT_POSE[ctx]` — instead of delegating to `_sync_context`'s idle-only branch.
- **Anchors:** `serenity/ui/shell.py:936`, `:941`, `:945`, `:521`, `:532`; `serenity/core/activity.py:157`.

**11.9 — Busy/idle bracket and the four ad-hoc reaction poses have no shared precedence — last call wins (§4)** · P2 · M
- **Gap:** §4 declares "the busy pose holds over transient reaction poses until the queue drains" but §8 gives no mediator and §10 tests precedence only vs a *context flip*, never vs the reaction poses. `MascotStage.set_state()` (`mascot_stage.py:266-273`) is stateless last-write-wins with no pending-reaction replay; four sites (`shell.py:495`/`504`/`535`/`671`) call bare `set_state`. During the multi-second off-thread digest window, an independent Pomodoro boundary (`_on_focus_phase`) or todo signal fires a bare `set_state`, silently swallowing the "thinking" pose with no re-assertion on drain. (Drop the candidate's task-lines/Focus-collision and `:671` justifications — refuted: task-lines can't fire during a tracked focus span, and `:671` sets the same "thinking" pose.)
- **Net:** Route all pose changes (busy/idle bracket AND the four reaction sites) through one small mediator that knows the queue's busy flag: while busy, a reaction request is **deferred (remembered, not dropped)** and replayed once the queue drains. (A lighter variant — the busy bracket owns a flag the reaction sites consult, plus a re-assert on drain — also suffices.)
- **Anchors:** `serenity/ui/mascot_stage.py:266`; `serenity/ui/shell.py:495`, `:504`, `:535`, `:671`.

**11.10 — Busy indicator doesn't reach the Mini-mode mascot / status line is anchored to the hidden dock (§4, §8)** · P2 · M
- **Gap:** In MODE_MINI the dock is hidden (`shell.py:1251`) and `self._mini.mascot` is the only visible mascot — exactly the mode a user is in during off-time jobs. If the busy-**set** path writes only `self.mascot` (like all four reaction sites, which never touch `_mascots()`), the working indicator is invisible there. Separately, the "thinking…" status line is anchored near the dock (§4), so in mini its click-target/inspector entry point is invisible regardless of mascot wiring. (§4's *revert* half already reaches both mascots since `_sync_context` iterates `_mascots()`; the fresh-mini-poseless worry is self-neutralized once the reapply routes through `_sync_context`, which `_ensure_mini` at `:1286` already calls.)
- **Net:** Implement the busy-set via a single queue-busy-aware helper that iterates `_mascots()` (dock + mini), matching `_sync_context`'s pattern, and route the thinking-reapply through `_sync_context` (covers fresh mini mascots at creation). **MODE_MINI (user decision 2026-07-18):** the mini mascot shows the **thinking pose only**; the "thinking…" status line + inspector entry point are **dock-only** — mini is documented **inspector-less** (the inspector is a power-user surface; mini is the minimal always-on-top mode). So the status line need not be re-anchored for mini.
- **Anchors:** `serenity/ui/shell.py:878-882`, `:942`, `:1250-1256`, `:1275-1287`, `:495`; `docs/.../2026-07-17-llm-queue-design.md:27`.

**11.11 — Inspector has no live-refresh, so a rendered row can go stale before the click lands (§4, §8)** · P2 · M
- **Gap:** §8 says the inspector only "reads `snapshot()`" (one-shot) and §2's Qt signal delivers only a completed job's own `on_done`/`on_error` — neither is a general "queue changed, re-render" notification. A job the panel rendered PENDING/PAUSED can transition to RUNNING/DONE before the user's Pause/Resume/Prioritize click; op behavior on an id that has left the PENDING/PAUSED set is undefined. The house convention for row lists (`duplicates_dialog.py:88-114`, `maintenance_dialog.py:40-51`) builds rows once and never re-syncs — an implementer copying it ships a stale-until-reopen panel.
- **Net:** Make `pause`/`resume`/`prioritize` explicit no-ops (return bool/None) when the id isn't in PENDING/PAUSED; have the worker emit a lightweight "queue changed" Qt signal on every state transition that the open inspector connects to for a live re-render (mirrors `activity_chip.py:64-72`'s per-second live-update).
- **Anchors:** `docs/.../2026-07-17-llm-queue-design.md:16`, `:52`; `serenity/ui/duplicates_dialog.py:88-114`, `serenity/ui/maintenance_dialog.py:40-51`, `serenity/ui/activity_chip.py:64-72`.

### Parked (P3) — tracked, not folded

- **11.p1 — Async digest delivery has no content-staleness guard** (M): delivery guard checks only week/anchor, not `_board_sig`; a content change during a pending inference yields transient one-cycle stale AI text next to fresh stats. Net: digest job captures its submit-time `_board_sig`; dedup keyed on `(week, that sig)`; `on_done` sets both `_digest` and `_digest_sig` to the **captured** sig (never a delivery-time recompute) — self-heals on the next refresh. Anchors: `docs/.../2026-07-17-llm-queue-design.md:37`, `:46`; `weekly_board_view.py:174-189`, `:224-227`.
- **11.p2 — TaskLineStore mutated from the worker thread** (S): a language-switch `clear()` (main thread) races the worker's `store.set()`; a worker pass can write an old-language line right after `clear()`, and `only_missing` then blocks regeneration → mascot speaks a wrong-language line until the todo evicts (KeyError-cascade refuted by `only_missing=True`). Net: `run()` returns authored `(todo_id, line)` pairs; apply `store.set()` only in `on_done` on the UI thread. Anchors: `task_lines.py:88`, `:154`, `:161`; `shell.py:508`, `:869`.
- **11.p3 — Task-lines job resubmitted every ~180s tick** (S): during a long first run one duplicate no-op job can slip into the queue behind the running one (cycle-burn/stuck-pose refuted — `only_missing=True` no-ops duplicates, pose halts on user return). Net: widen dedup to skip an identically-labeled job that is PENDING **or** RUNNING; job reuses the stable label "Task voice lines". Anchors: `breaktime.py:226-231`, `:50`; `task_lines.py:140-152`.
- **11.p4 — "Recent maintenance" Settings panel loses the async task-lines outcome** (M): the migrated closure returns a submit-time placeholder ("queued"), so the panel never shows the real count/failure. Net: when the job's `on_done`/`on_error` fires, push a follow-up `JobResult` into `PerfSampler` (one-line note in §6/§8's shell.py bullet). Diagnostic-only. Anchors: `shell.py:701-702`; `perf.py:131-146`; `settings_window.py:557-565`.
- **11.p5 — Base install (no [llm]) could flash a bogus busy signal** (S): `weekly_board_view.refresh()` has no call-site availability check, so a literal migration would submit a digest job with no LLM. Net: gate the digest submit on the existing `ai` flag (`:231`), mirroring the card-gating at `:232-233`. (Task-lines half refuted — its guard already lives at `maintenance.py:80-81`.) Spec-precision, not a functional bug.
- **11.p6 — `snapshot()`/busy-check torn read during the PENDING→RUNNING handoff** (S): a read mid-handoff could momentarily drop/duplicate an inspector row (self-correcting; the mascot-flicker mechanism is refuted — the bracket is signal-driven, not polled). Net: subsumed by 11.1 — `snapshot()` builds/returns an immutable copy entirely under the queue lock. Anchors: `docs/.../2026-07-17-llm-queue-design.md:16`, `:27`.
- **11.p7 — Open inspector's behavior when its anchoring status line disappears (queue drains)** (S): spec never says whether an already-open panel auto-closes or stays. Net: spec-decide stay-open showing a clean empty state (`snapshot()` already yields this — the panel is its own widget, not anchored to the line); add one §10 assertion. Anchors: `docs/.../2026-07-17-llm-queue-design.md:28-29`.
- **11.p8 — Rapid board reopens while a digest job is already RUNNING aren't deduped** (M): the `not self._digest` clause re-fires during the RUNNING window and dedup names only PENDING, so rapid re-opens queue redundant digest jobs, prolonging the "thinking" pose (marginal trigger, self-correcting output). Net: same fix as 11.p3 — widen the planned dedup to PENDING-or-RUNNING (subsumes this); the `_digest_sig` pre-submit gate is secondary and insufficient alone. Anchors: `weekly_board_view.py:90`, `:218-227`; `docs/.../2026-07-17-llm-queue-design.md:46`.

### Refuted (verified NOT a gap — dropped)

- **Worker-loop scaffolding crash** — PySide6 catches an exception escaping `QThread.run()`/a queued slot (prints traceback + continues); no whole-app abort, so §7's `run()`-scoped try/except is adequate.
- **No mid-job cancellation hook** — deliberate: §5 runs the RUNNING job to completion, §9 lists aborting a running inference as an explicit non-goal, and §7 never blocks quit on the in-flight job.
- **Model-load-failure swallowed** — `generate()` returning `''` on load/inference failure is the documented degrade contract (`llm.py:209-213`); no regression from the migration. (Its net also rested on a false `self.available` premise — load failure flips the class sentinel `_shared`, not the instance flag.)
- **CaptureRouter unserialized second caller** — `CaptureRouter` is never constructed in the live app (only in tests); the live mic path calls `parse_capture` directly, so its `generate()` is dead code. The real reentrancy risk is RAG/Ask, owned by fold 11.2 (which covers the router for free if it ever goes live).
- **Global-pause status ambiguity** — §4 keys the busy pose to "runnable PENDING" and `next_runnable()` returns None when globally paused, so a paused queue reverts the mascot to its mood pose; the label staying visible is needed as the resume/inspector re-entry point.
- **Failed-job flash has no distinguishing visual** — the inspector shows only RUNNING + PENDING/PAUSED, so DONE and FAILED both vanish symmetrically (no confusable "finished" row); failure surfaces via the per-job `on_error` channel and both migrated consumers degrade gracefully.
