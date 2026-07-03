# Urgency-Peek — Urgent Todos Surface Through the Two-Axis Filter — Design Spec

_Date: 2026-07-03 · Branch: `wf/urgency-peek` (off `wf/phase-c-state-tag`) · Follows Phase C_
_Status: approved design + flow-hardened (14 confirmed candidates deduped to 7 requirements); source for the TDD plan._

## 1. Goal

Phase C's context/state filter can bury a genuinely urgent todo (a *Coding* task due in 1 h stays hidden while you track *Working*). Fix: an urgent todo (the existing urgent band, `urgency_tier ≥ 2`: overdue, due ≤ `WARN_HOURS`=4 h, running timer, in-progress) **peeks through** instead of hiding — as a **full card** when only the *state* axis rejected it, and as a **privacy-blurred read-only placeholder** when the *context* axis rejected it (time-left + context label only; switch context to see what it is). User decisions locked: state = soft for urgent items · context = blurred peek (never titles) · no delay/snooze yet (that is Phase H reminders — the placeholder gains `[snooze ▾]` then).

## 2. Classification (pure core)

`ranking.peek_class(todo, context, state_key, now) -> "show" | "peek_full" | "peek_blurred" | "hide"`:

- `show` — `states.visible(todo, context, state_key)` passes.
- `hide` — filtered AND not urgent (`urgency_tier(todo, now) < 2`).
- `peek_full` — filtered, urgent, context matches (`todo.context` valid-and-equal or unstamped ⇒ only the state axis rejected).
- `peek_blurred` — filtered, urgent, context differs.

Plus a dedicated **relative-only** time formatter (e.g. `overdue 12 min` / `in 47 min` / `in 3 h 10 m`) — never absolute clock times on the blurred surface **[R-F]**.

## 3. The blurred placeholder (new widget, `serenity/ui/todos_view.py` or sibling)

Read-only row showing ONLY:

| todo state | placeholder text |
|---|---|
| has `due` | `⏰ <relative time-left> · 🔒 <Private\|Business> item` |
| `due=None`, `timer_running` | `▶ running · 🔒 <…> item` **[R-E]** |
| `due=None`, `in_progress` | `● in progress · 🔒 <…> item` **[R-E]** |

No title/tags/category/body/subtasks, **no tooltip, no accessibleName** [R-F], never the string "None", never elapsed timer seconds (nothing to leak, nothing to crash — `tier ≥ 2` with `due=None` is exactly timer/in-progress) [R-E]. Not a drag source or drop target.

**Click-to-reveal = two-click armed confirm [R-D]:** first click never flips context — it re-renders the placeholder in place to an armed `Switch to <Private|Business>?` state that auto-disarms after ~3 s (single-shot timer) or on refresh; only a second click while armed calls `shell.set_context`. A confirm click arriving within `QApplication.doubleClickInterval()` of arming is ignored, so an accidental double-click arms but never flips (folds the double-click/click-through finding). A mis-click during a Business screen-share therefore exposes nothing.

**Live countdown [R-B]:** the placeholder implements the same `needs_tick()` (True while shown) / `tick(now)` (re-render time-left, flip to the overdue form past due) protocol as `TodoCard`, and `TodosView._tick` + `_sync_tick_timer` iterate placeholders alongside cards — so the 1 s tick stays active when the only urgent item is a blurred one, and the countdown (the placeholder's only informative content) never freezes.

## 4. `TodosView.refresh` integration

Per ranked todo (rank order preserved — urgent peeks naturally sit on top):

1. **Grace precedence [R-C]:** id in `_grace_timers` ⇒ bypass classification entirely — exactly one full `TodoCard` with `show_grace_pending()` (never a placeholder, never double-rendered, the un-tick undo handle stays reachable), excluded from the hidden count.
2. `show` / `peek_full` ⇒ normal `TodoCard`.
3. `peek_blurred` ⇒ the placeholder.
4. `hide` ⇒ excluded; still counted in the "N hidden by context/state filter" hint (peeked/grace items are NOT counted — they're visible).

**Boundary re-classification [R-A]:** nothing re-runs `refresh()` on time passage today, so a hidden todo crossing into the urgent band would stay buried. At the end of every `refresh()`, arm a single-shot timer for the earliest future peek-boundary among hide-classified due-dated todos (`seconds_until_due − WARN_HOURS·3600`, clamped ≥ 1 s; disarmed when none); its timeout re-runs `refresh()`. Additionally `Shell._on_resume` refreshes the todos view (a sleep/resume jump crosses boundaries without the timer firing).

## 5. Mini dock [R-H]

`MiniWindow.refresh_todo` currently context-filters and can claim "All clear - nothing actionable." while an urgent cross-context todo exists — a lie on the always-on-top surface. When any active todo classifies `peek_blurred` (context axis only, `state_key=None`): render the same title-free blurred line (`⏰ <time-left> · 🔒 <…> item`, R-E forms for due-less) — replacing "All clear" when there is no pick, or as a second line under the pick. Clicking it emits the existing `context_toggle_requested` (the mini's toggle already routes through `shell.toggle_context`; the two-click confirm applies in the main list, while the mini line reuses the mini's existing one-click toggle affordance — it IS the context-toggle surface).

## 6. Non-goals

Snooze/defer (Phase H; the placeholder is its future anchor) · notes (no deadlines) · calendar/graph/week-panel peeks (calendar is a time surface already; graph is structural — documented boundary) · reminder offsets/notifications · changing `urgency_tier` thresholds · persisting peek/armed state.

## 7. Flow-harden fold (14 confirmed → 7 deduped; 2 refuted recorded)

| # | Sev | Requirement (one line) |
|---|---|---|
| R-A | P2 | Boundary single-shot timer after every refresh (earliest hide→urgent crossing) + refresh on resume |
| R-B | P2 | Placeholder ticks (needs_tick/tick) and is included in `_tick`/`_sync_tick_timer` — countdown never freezes |
| R-C | P2 | Grace-pending bypasses classification: one full card, undo reachable, excluded from the hidden count |
| R-D | P2 | Two-click armed confirm for reveal (auto-disarm ~3 s; confirm ignored within doubleClickInterval of arming) |
| R-E | P2 | `due=None` placeholder forms (`▶ running` / `● in progress`), no "None", no elapsed seconds, no crash |
| R-F | P3 | Relative-only time format via a dedicated helper; no tooltip/accessibleName on the blurred surface |
| R-H | P2 | Mini dock renders the title-free peek line instead of lying "All clear"; click = context toggle |

Refuted (recorded): synchronous placeholder self-destruction in its own mouse handler (deferred rebuild pattern already avoids it); grace-undo-destroyed-on-flip (superseded by R-C's precedence rule).

## 8. Testing map

- **Pure:** `peek_class` truth table (context match/mismatch × urgent/not × chip on/off × unstamped), the relative formatter (incl. overdue form, no `:` clock digits), boundary-instant math.
- **Widget:** placeholder text per R-E form; privacy assertions (title string absent anywhere in the widget, no tooltip/accessibleName); tick updates the label + overdue flip; two-click confirm (single click ⇒ context unchanged + armed; auto-disarm; double-click ⇒ still unchanged; deliberate second click ⇒ flipped).
- **View (offscreen):** cross-context urgent ⇒ exactly one placeholder; same-context off-state urgent ⇒ full card at top; non-urgent stays hidden + counted; grace × peek ⇒ one card, un-tick works, count right [R-C]; tick timer active with only a blurred item [R-B]; boundary timer fires ⇒ hidden todo surfaces without user interaction [R-A].
- **Mini:** peek line replaces "All clear"; no title text; click emits `context_toggle_requested` [R-H].
- Gate: full headless suite green.
