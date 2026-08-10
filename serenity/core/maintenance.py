"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: The background maintenance JOBS the break-time scheduler runs while the user is on
         a break - the real work half of the break-time mode (the framework lives in
         core.breaktime; this is what gets registered into it).
Role:    A pure, Qt-free FACTORY that, given whatever backends the app already holds (the
         semantic index, the note store, the LLM), returns the list[BreakJob] to register on
         a BreakScheduler. Each job's run() is a zero-arg closure that GUARDS on its backend
         being available and returns a short status string (surfaced as JobResult.value), so
         on a base install (no [semantic]/[llm] extras) every job cleanly NO-OPs - it loads
         no model and never raises - and the app behaves exactly as today. The scheduler's
         tier gate (HEAVY -> AC + a long idle) keeps the big-model work off the working path.

Functions:
- build_maintenance_jobs(*, semantic, note_store, todo_store, llm, task_lines, warm_cache)
  -> list[BreakJob]
  - the HEAVY "semantic-reindex" job (re-embeds changed notes via SemanticIndex.index)
  - the HEAVY "task-voicelines" job (authors a per-todo personalized spoken line via the LLM
    into the shared TaskLineStore; no-ops without an LLM - see core.task_lines)
  - warm-cache precompute is DEFERRED (no question source exists yet - see the note below)
============================================================
"""

from __future__ import annotations

from typing import Optional

from .breaktime import BreakJob, Tier
from .task_lines import DEFAULT_LIMIT, generate_task_lines


def build_maintenance_jobs(*, semantic=None, note_store=None, todo_store=None, llm=None,
                           task_lines=None, warm_cache=None) -> list[BreakJob]:
    """Build the break-time maintenance jobs from the app's live backends.

    Keyword-only and every argument optional (defaulting None) so the shell can hand over
    whatever it has - and a base install passes live-but-unavailable backends without
    special-casing. Returns the BreakJobs in registration order. The jobs themselves are the
    only place that touches a backend; this factory only wires the closures, it runs nothing.

    `warm_cache` is accepted for forward-compatibility but builds NO job yet (see below)."""
    jobs: list[BreakJob] = []

    # JOB - "semantic-reindex" (HEAVY): re-embed the notes whose content changed since the
    # last index pass. HEAVY because SemanticIndex.index() can spin up the e5 model - exactly
    # the big-model work the HEAVY tier (AC + a long idle) exists to gate off the working
    # path. It is incremental (skips unchanged notes, prunes deleted) so a repeat tick with no
    # changes is cheap - which matters because the scheduler has no per-job cooldown and
    # re-runs every eligible job each tick (see breaktime.BreakScheduler.tick).
    def _reindex() -> str:
        # Guard on availability so a base install (no embedder) returns a clean status and
        # loads no model, rather than relying on the scheduler's exception catch.
        if semantic is None or not getattr(semantic, "available", False):
            return "skipped - no index"
        if note_store is None:
            return "skipped - no notes"
        notes = note_store.all_active()
        semantic.index(notes)
        return f"reindexed {len(notes)}"

    jobs.append(BreakJob(id="semantic-reindex", name="Semantic reindex",
                         tier=Tier.HEAVY, run=_reindex))

    # JOB - "task-voicelines" (HEAVY): author a short, PERSONALIZED spoken line for the top
    # active todos via the local LLM, ahead of time, so the mascot can read a tailored line
    # the moment the user starts a task. HEAVY because it spins up the generation model - the
    # same big-model work the HEAVY tier (AC + a long idle) exists to gate off the working
    # path. It DEGRADES cleanly: with no LLM / an unavailable LLM / no todo source /no shared
    # store it stores nothing and returns a clean status, loading no model - so a base install
    # (no [llm] extra) keeps using the deterministic VoiceLines catalog exactly as today. It
    # is INCREMENTAL + BOUNDED (generate_task_lines authors at most DEFAULT_LIMIT lines and
    # skips todos that already have one), so a repeat tick over an unchanged backlog is cheap -
    # which matters because the scheduler re-runs every eligible job each tick with no cooldown
    # (see breaktime.BreakScheduler.tick).
    def _task_voicelines() -> str:
        # Guard up front so a base install returns a clean status and loads no model, rather
        # than relying on the scheduler's exception catch (mirrors _reindex above).
        if llm is None or not getattr(llm, "available", False):
            return "skipped - no llm"
        if todo_store is None or task_lines is None:
            return "skipped - no todos"
        todos = todo_store.active()[:DEFAULT_LIMIT]
        written = generate_task_lines(todos, llm, task_lines)
        return f"voicelines {written}"

    jobs.append(BreakJob(id="task-voicelines", name="Task voice lines",
                         tier=Tier.HEAVY, run=_task_voicelines))

    # JOB - "warmcache-precompute" (HEAVY): DEFERRED, intentionally not built here.
    # WarmCache.precompute(questions, ...) needs a list of candidate questions, but the app
    # has no question source yet (Ask runs cache-less, no recent-questions store exists) and
    # the shell never builds a shared WarmCache. Wiring it for real would mean inventing a
    # question store, which is out of scope. The `warm_cache` kwarg is kept so the seam is
    # ready; what unblocks the job is (a) a question source + (b) a shared WarmCache instance.
    _ = warm_cache  # accepted for forward-compat; no job built this pass

    return jobs
