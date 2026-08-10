# Urgency-Peek Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Urgent todos (`urgency_tier ≥ 2`) surface through the Phase C context/state filter — full card when only the state axis rejected them, privacy-blurred placeholder when the context axis did.

**Architecture:** Pure classifier + relative formatter in `core/ranking.py`; a new `ui/peek_placeholder.py` widget (tick protocol + two-click armed confirm); `TodosView.refresh` classification with grace precedence + a boundary re-classification timer; a mini-dock peek line. Spec: `docs/superpowers/specs/2026-07-03-urgency-peek-design.md` (R-A…R-H).

**Tech Stack:** Python 3.12, PySide6 (offscreen-testable), pytest.

## Global Constraints

- Suite gate after EVERY task: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → all pass.
- New .py files start with the project header comment block.
- The blurred surface NEVER renders title/tags/category/body, absolute clock times, the string "None", elapsed timer seconds, tooltips, or accessibleName [R-E/R-F].
- Conventional commits, one per task.

---

### Task 1: Pure core — `peek_class` + `format_time_left`

**Files:** Modify `serenity/core/ranking.py`; test `tests/test_ranking.py`.
**Interfaces — Produces:** `peek_class(todo, context, state_key, now) -> str` ("show"|"peek_full"|"peek_blurred"|"hide"); `format_time_left(due, now) -> str` (relative-only: `overdue 12 min` / `in 47 min` / `in 3 h 10 m`).

- [ ] Failing tests: truth table (visible→show; filtered+not-urgent→hide; filtered+urgent+context-match/unstamped→peek_full; filtered+urgent+context-differ→peek_blurred; chip-off ⇒ state axis off), formatter (minutes/hours forms, overdue form, no `:` clock digits, singular/plural sane).
- [ ] Implement: `peek_class` delegating to `states.visible` + `urgency_tier`; `format_time_left` pure divmod.
- [ ] Full suite green → commit `feat(ranking): peek_class + relative time formatter (urgency-peek)`.

### Task 2: `PeekPlaceholder` widget

**Files:** Create `serenity/ui/peek_placeholder.py`; test `tests/test_peek_placeholder.py`.
**Interfaces — Produces:** `PeekPlaceholder(todo, context_label)` with `needs_tick()`, `tick(now)`, signal `reveal_requested`; internal armed-confirm state (`_armed`, 3 s single-shot disarm QTimer, `QElapsedTimer` gate `> QApplication.doubleClickInterval()`).

- [ ] Failing tests: text forms per R-E table (due / due=None+timer_running / due=None+in_progress); privacy (todo.title absent from every child widget text, `toolTip()==""`, `accessibleName()==""`); tick updates label + overdue flip; confirm flow (1st click ⇒ no `reveal_requested`, armed text shown; auto-disarm after timer; click within doubleClickInterval of arming ⇒ still nothing; deliberate 2nd click (monkeypatch the elapsed gate) ⇒ exactly one `reveal_requested`).
- [ ] Implement: `QFrame#card` row, one QLabel, `mousePressEvent` state machine; not draggable (no drag/drop handlers).
- [ ] Full suite green → commit `feat(ui): privacy-blurred PeekPlaceholder with tick + two-click confirm (R-B/R-D/R-E/R-F)`.

### Task 3: `TodosView` integration + boundary timer + shell wiring

**Files:** Modify `serenity/ui/todos_view.py` (refresh/_tick/_sync_tick_timer + `_boundary_timer`), `serenity/ui/shell.py` (`_on_resume` refresh; reveal → `set_context`); test `tests/test_ui_filter.py` (extend).
**Interfaces — Consumes:** T1 classifier, T2 widget. **Produces:** `TodosView` renders per class; `_peek_widgets` list joined with `_cards` in tick paths.

- [ ] Failing tests (Shell-level, offscreen): cross-context urgent ⇒ exactly one placeholder + zero title occurrences in the todos list; same-context off-state urgent ⇒ full card ranked at top; non-urgent stays hidden + counted, peeked NOT counted [hint]; grace × peek_blurred ⇒ exactly one full card, un-tick cancels, count right [R-C]; tick timer active when the only urgent item is blurred [R-B]; boundary timer: hidden todo due `WARN_HOURS+ε` out ⇒ `_boundary_timer` armed with ~ε interval; firing `refresh()` surfaces it [R-A]; placeholder confirm ⇒ `settings.context()` flipped [R-D wiring].
- [ ] Implement: refresh classification order (grace-ids first-class bypass → classify rest), placeholder construction wired to `self._reveal` → `shell` via a new `reveal_context` signal (Shell connects to `set_context`), `_tick`/`_sync_tick_timer` iterate `self._cards + self._peek_widgets`, `_boundary_timer` (single-shot, re-armed at refresh end: `min(seconds_until_due(t) − WARN_HOURS·3600)` over hide-classified due todos, clamp ≥ 1 s), `Shell._on_resume` adds `self.todos_view.refresh()`.
- [ ] Full suite green → commit `feat(ui): urgency-peek in TodosView + boundary re-classification (R-A/R-C + wiring)`.

### Task 4: Mini-dock peek line

**Files:** Modify `serenity/ui/mini_window.py`; test `tests/test_ui_filter.py` (extend).
- [ ] Failing tests: urgent cross-context todo + no pick ⇒ peek line text (no title, has 🔒) instead of "All clear"; with a pick ⇒ line under it; click emits `context_toggle_requested`; no urgent cross-context ⇒ line hidden [R-H].
- [ ] Implement: after the pick, compute any `peek_class(t, ctx, None, now) == "peek_blurred"` over actives; a clickable QLabel with the R-E-form text; `mousePressEvent` → `context_toggle_requested.emit()`.
- [ ] Full suite green → commit `feat(ui): mini-dock blurred peek line (R-H)`.

### Task 5: Docs

- [ ] Append the urgency-peek flows to `notes/5_Interaction_Flows.md` area 9 (or a 9b subsection); planning wrap in `notes/1_Planning.md`; spec/arch one-liners.
- [ ] Full suite green → commit `docs: urgency-peek flows + wrap`.

## After the plan: QA pipeline

criticizer → optimizer → test-agent (adversarially verified, fix between, suite green after each).
