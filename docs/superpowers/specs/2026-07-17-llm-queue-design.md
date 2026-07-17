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
