# Phase H — Reminders (due-relative ladder + snooze) — Design Spec

_Date: 2026-07-06 · Branch: `wf/phase-h-reminders` (off `wf/urgency-peek`) · Milestone: States & Contexts, Phase H_
_Status: approved design + flow-hardened (§8: 17 confirmed → 13 requirements + 3 clarifications, folded); source for the TDD plan._

## 1. Goal

Today Serenity has **no reminder mechanism**: the parser's `reminder` intent just routes to a due-dated todo (the flag isn't even persisted on `Todo`), and two mascot voice lines (`deadline_near`, `timer_due`) sit dormant with nothing firing them. Phase H adds **opt-in, due-relative reminders**: per todo you arm any subset of a fixed ladder — **1 week / 1 day / 1 hour / 30 min / 5 min** before `due` — and Serenity rings each armed rung as its time arrives, through the mascot bubble + a tray toast + a banner on the todo card. A ringing reminder is **acknowledged** by **Snooze** (defer *down* the ladder to the next armed rung) or **Dismiss**. Snooze never moves the todo's `due`. Cross-context rings stay privacy-blurred (relative time only, no title) and can be snoozed/dismissed without revealing the item — extending the urgency-peek `PeekPlaceholder`.

### Locked decisions (from brainstorm)

- **Attach model:** opt-in; the user picks individual rungs per todo (no auto-arming of every dated todo).
- **Picker surface:** one shared `ReminderPicker` widget, embedded in the TodoCard 🔔 control, `QuickTodoDialog`, and the calendar-slot dialog.
- **Fire surface:** mascot bubble (`deadline_near` dormant lines, spoken if TTS on) **+** tray `showMessage` **+** a card banner that persists **while ringing**.
- **Ring lifecycle:** a fired reminder rings until acknowledged (Snooze / Dismiss). The **card banner is the durable surface** — it is state-driven from the persisted `reminder_active`, so it re-renders and stays actionable across app restarts. The mascot **bubble + tray toast are transient fire-moment surfaces** (best-effort, not restored on restart — the tick fire-guard blocks a re-fire of an already-active ring; **[C-2]**).
- **Catch-up:** on resume/tick, if several armed rungs are already past, **collapse** to a single ring (the most urgent) and mark the rest fired — never a wake-up storm.
- **Snooze:** defer to the next armed rung down the ladder; the **bottom** rung (or a nudge) → a fixed **+5 min re-nudge** (repeatable).
- **Cross-context:** blurred fire (relative time only, no title), snooze/dismiss without reveal.
- **NL capture:** IN — the parser `reminder` intent extracts an offset ("remind me 1 day before" / "erinnere mich 1 Tag vorher") and arms the nearest rung.
- **ICS VALARM round-trip:** DEFERRED (documented non-goal).
- **Scheduler:** a pure, clock-injected `core/reminders.py` (mirrors `core/breaktime.py`), driven by a coarse Shell QTimer + an `_on_resume` catch-up tick.

## 2. Data model — new fields on `Todo` (JSON store, no migration)

`Todo` is a JSON dataclass with a tolerant `from_dict`; adding fields is additive-safe. **Phase H does not block on Phase I** — only the note *SQLite* index has the migration gap; the Todo JSON store coerces unknown/missing fields to defaults (the Phase C `_clean_*` pattern). Four fields (`models.py`):

| Field | Type | Meaning |
|---|---|---|
| `reminder_offsets` | `list[int]` | Armed rungs, **minutes before `due`**; subset of `{10080, 1440, 60, 30, 5}`. `[]` = no reminders. Source of truth for what's armed. |
| `reminder_fired` | `list[int]` | Offsets already consumed (fired + acknowledged, or collapsed). |
| `reminder_active` | `Optional[int]` | Offset currently **ringing** (already in `reminder_fired`); `None` = quiet; sentinel `0` = a +5 min nudge ring. Drives the **durable banner** (persisted → re-renders across restart); the bubble/tray fire once and are not restored (§1, C-2). |
| `reminder_nudge_at` | `Optional[datetime]` | Absolute time of a scheduled +5 min re-nudge (bottom-rung / nudge snooze); else `None`. |

Tolerant coercion in `from_dict` (mirror `_clean_context` / `_clean_state_tag`): `reminder_offsets`/`reminder_fired` coerce to a de-duplicated list of **known** rung ints (drop anything not in `RUNG_MINUTES`, plus `0` allowed in `fired`/`active` as the nudge sentinel); `reminder_active` to an `Optional[int]` in the allowed set (else `None`); `reminder_nudge_at` via `_parse_iso`. `to_dict` serializes all four (`_iso` for the datetime).

## 3. `core/reminders.py` — pure, clock-injected (mirrors `breaktime.py`)

No Qt, no wall clock — `now` is always injected, so every rule is headless-testable with zero timing flakiness.

- `RUNG_MINUTES = [10080, 1440, 60, 30, 5]` (descending: earliest-first) + a label map for the picker (`"1 week"`, `"1 day"`, `"1 hour"`, `"30 min"`, `"5 min"`).
- `NUDGE_MINUTES = 5` · `NUDGE_SENTINEL = 0`.
- `snap_to_rung(minutes: int) -> int` — NL capture snaps a free offset to the nearest ladder rung.
- `@dataclass Fire { todo_id: str; offset: int; is_nudge: bool }` — one ring event.
- `armable_offsets(todo, now) -> list[int]` — the rungs whose fire time (`due - offset·min`) is still in the **future** (used to grey past rungs in the picker; a rung already past would fire retroactively).
- `tick(todo, now) -> Optional[Fire]` — the core step; **mutates** the todo's `reminder_*`, returns a `Fire` or `None`. Guard: skip if `done`/`deleted`, no `due`, or no `reminder_offsets`.
  1. `reminder_active is not None` → return `None` (never stack a second ring over an unacknowledged one).
  2. `reminder_nudge_at is not None and now >= reminder_nudge_at` → fire nudge: `reminder_active = NUDGE_SENTINEL`, clear `reminder_nudge_at`, return `Fire(is_nudge=True, offset=0)`.
  3. Else collect armed-unfired offsets whose `due - offset·min <= now`. If none → `None`. Otherwise **collapse**: mark them **all** fired, set `reminder_active = min(those)` (smallest offset = closest to due = most urgent), return `Fire(offset=that, is_nudge=False)`.
- `acknowledge_snooze(todo, now) -> None` — no-op if `reminder_active is None`. Else:
  - a **smaller armed-unfired** offset exists (`< reminder_active`, not in `reminder_fired`, and `reminder_active != NUDGE_SENTINEL`) → just clear `reminder_active` (the ladder self-walks; that lower rung fires on its own schedule via `tick`).
  - otherwise (bottom armed rung, or a nudge, or no smaller rung remains) → `reminder_nudge_at = now + NUDGE_MINUTES·min`, clear `reminder_active`.
- `acknowledge_dismiss(todo) -> None` — `reminder_fired = list(reminder_offsets)`, `reminder_active = None`, `reminder_nudge_at = None`. Silent forever unless re-armed.
- `arm(todo, offsets, now) -> None` — set `reminder_offsets` from the picker while **preserving prior fired state [R-3]**. Do NOT recompute `reminder_fired` from scratch (that would resurrect a rung the user explicitly dismissed): apply a *delta*:
  - **dropped** (in old offsets, not in `offsets`) → removed from `reminder_fired` too.
  - **added** (in `offsets`, not in old offsets) → pre-mark fired iff its fire time is already past (`due - offset·min <= now`), so arming never retroactively rings; else armed-unfired.
  - **unchanged** (in both) → keep its current fired status (a dismissed/consumed rung stays consumed).
  - Result invariant: `reminder_fired ⊆ reminder_offsets`. Clear `reminder_active`/`reminder_nudge_at` if they reference a dropped rung. Removing all offsets clears every reminder field. **Guard `todo.due is not None` before computing fire times [C-3]** (belt-and-suspenders; call sites already gate on a due, but `arm` must never do `None - timedelta`).
  - **Re-arming a dismissed rung** is therefore an explicit *untick → re-tick* (drops it from `fired`, then re-adds it armed-unfired); the picker styles consumed rungs distinctly so the user sees which will still ring **[R-3]**.

**Why snooze needs no explicit "advance":** rungs are absolute fire times. Snoozing an upper rung only marks it fired and stops the ring; the next lower armed rung is untouched and fires when *its* `due - offset` arrives. The collapse in `tick` handles the "many rungs already past" case; snooze handles the "one ring at a time" case.

**Snooze escalation near the deadline is intended [C-1]:** if, when you snooze an upper rung, the next lower armed rung's fire time is *already past* (you ignored the ring until close to due), it re-fires on the very next `tick` — this is correct escalation, not a bug. Snooze defers to the next armed rung; it **never pushes a reminder past the `due` time** (deferring a near-due snooze to a `+5 min` nudge could ring *after* the deadline and silence the last pre-due reminder — explicitly rejected). Dismiss is the real "silence it" path.

## 4. UI

### 4.1 `ReminderPicker` (new shared widget, `serenity/ui/reminder_picker.py`)

Five rung toggles bound to a todo's `reminder_offsets`. **Disabled with a hint ("Set a due date to add reminders") when the todo has no `due`** — reminders are due-relative. Rungs in `armable_offsets(todo, now)` are enabled; rungs whose fire time is already past are **greyed** (arming them would be retroactive). When a `due` exists but `armable_offsets` is **empty** (todo due in < 5 min / overdue → every rung greyed), show a distinct hint ("Due too soon for a reminder") so the all-greyed state never looks broken **[R-8]**. Rungs already in `reminder_fired` (consumed/dismissed) render distinctly from armed-unfired ones **[R-3]**. One widget, three hosts → no triplicated logic:

- **TodoCard** — a 🔔 control opens the picker as a small popover; a filled bell (with a count) indicates armed reminders.
- **`QuickTodoDialog`** (`modals.py`) — an inline rung row; only meaningful once a due is parsed/entered (greyed until then).
- **calendar-slot dialog** (`calendar_week_panel.py` → `QuickTodoDialog(default_due=slot)`) — the slot pre-fills `due`, so rungs are immediately armable.

Committing the picker calls `reminders.arm(todo, offsets, now)` → `store.save()` → refresh.

### 4.2 Ringing banner (`TodoCard`, + `PeekPlaceholder` cross-context)

While `reminder_active is not None`, the card shows a highlighted banner strip: `⏰ due in 30 min` (via `ranking.format_time_left`, relative-only) + **[Snooze] [Dismiss]** buttons.

- **In-context** (the todo's own context/state visible) → the full card shows the banner; copy may include the title.
- **Cross-context** → the banner rides the existing `PeekPlaceholder` (already blurred, title-free); it shows `blurred_line(todo, now)` + Snooze/Dismiss. **Snooze/Dismiss never reveal** the item (no context switch, no title). This is the anchor urgency-peek's spec reserved (`[snooze ▾]`).

**A ringing todo MUST always render [R-4].** A rung can fire while the todo is *not* urgent (the 1-week rung fires 7 days out, `urgency_tier=0`). If such a todo is also filtered (other context / state chip), `ranking.peek_class` returns `"hide"` and `TodosView.refresh` would drop it → the banner + Snooze/Dismiss have **no surface**, `reminder_active` stays stuck, and `tick`'s guard-1 blocks every later rung for that todo (a stuck bubble + unacknowledgeable ring for hours/days). So `reminder_active is not None` is a **surfacing trigger** that bypasses `hide` — mirroring the `_grace_timers` bypass (`todos_view.py:589`): render a full card in-context, a blurred `PeekPlaceholder` cross-context, regardless of `urgency_tier`. (Grace precedence still wins if the id is also in `_grace_timers`.)

Snooze → `reminders.acknowledge_snooze`; Dismiss → `reminders.acknowledge_dismiss`; both `store.save()` + refresh + clear the bubble.

### 4.3 Fire routing (`Shell`)

Each `Fire` from a tick routes to three surfaces:

- **Mascot bubble** — a reminder voice line (spoken if TTS on). **`{time}` renders a *localized, relative* time phrase** — the dormant `deadline_near`/`timer_due` lines were written for an **absolute clock** ("due at {time}" / "um {time}"), and `ranking.format_time_left` emits **hard-coded English** ("in", "h", "min", "overdue"). Feeding a relative phrase into "at/um {time}" yields "due at in 30 min" nonsense in both languages — and TTS speaks it. So: **add reminder-specific relative-time copy in `de`+`en`** whose phrasing fits a relative phrase, and supply a **localized** relative-time helper for the `{time}` slot (don't reuse the clock-oriented lines verbatim) **[R-7]**.
- **Cross-context copy is structurally title-less [R-1].** In-context copy may include `{title}`; cross-context copy uses a **dedicated event key** (e.g. `deadline_near_blurred` — `🔒 A {context} item is due {time}`) with **no `{title}` variant in the bucket**. This matters because `VoiceLines.say` picks a *random* variant within a bucket and `_fill` leaves an unfilled `{title}` slot literal — folding title-less lines into the shared `deadline_near` bucket would let the random pick voice/print a private title across the context boundary. Routing strictly by context to a title-free bucket makes the leak *structurally impossible*.
- **Tray** — `tray.showMessage("Serenity", <msg>, ...)`; cross-context message is title-less (same rule as the bubble).
- **Card banner** — set by `reminder_active` (§4.2); the affected tab refreshes.
- **MINI window mode [R-6].** In MINI the full Shell (and its mascot) is hidden and `MiniWindow` has no banner/Snooze/Dismiss; its peek-line click emits `context_toggle_requested` — **a reveal**, which must never be the *only* way to acknowledge a cross-context ring. On a fire while in MINI, surface a reachable **privacy-safe** ack: route the bubble to the *visible* mini mascot **and** give `MiniWindow` a minimal `reminder_active`-driven Snooze/Dismiss affordance (relative-time line only) — separate from the context-toggle affordance.

A tick that produced any `Fire` triggers exactly one `store.save()` before routing.

## 5. Scheduler wiring (`Shell`)

- A coarse **QTimer (~60 s)** ticks the scheduler: for each active todo with `due` + `reminder_offsets`, call `reminders.tick(todo, now)`; collect `Fire`s; if any, one `store.save()` + route (§4.3) + `todos_view.safe_refresh()`.
- **Immediate catch-up on cold launch [R-9].** A `QTimer` does not fire on `start()` (first tick is +60 s) and `_on_resume` only fires on a WM power-resume event — so after the app was *closed* across a fire time, nothing rings for up to ~60 s. Run **one catch-up tick at startup** (after views are built, mirroring the immediate `self._maybe_auto_open_board()` at `shell.py:262`) so a cold reopen collapses past rungs to one ring per todo at once.
- **`_on_resume`** (already exists) fires an **immediate** catch-up tick before its `safe_refresh()` — a sleep/resume jump crosses many fire times at once; `tick`'s collapse guarantees a single ring per todo.
- The QTimer runs only when at least one active todo has armed offsets (mirror `_sync_tick_timer`'s "run only when needed" discipline), so idle RAM/CPU stays flat.
- Acknowledge buttons (§4.2) route through `reminders.acknowledge_*` → save → refresh → clear bubble.
- **Bubble/tray are not re-asserted on restart [C-2].** The catch-up tick will NOT re-fire an already-`reminder_active` ring (guard-1), and startup `greet("open")` overwrites the bubble anyway — this is intended: the **banner** (state-driven) is the durable surface; the bubble/tray are transient. No mechanism re-shows a bubble for a ring that was already active before the restart.

## 6. Integration points

- **Recurrence** (`todo_store._spawn_recurrence`): the spawned next occurrence **clones `reminder_offsets`** and re-arms via **`arm`'s past-rung pre-mark against the NEW due [R-5]** — i.e. pre-mark any rung whose `new_due - offset·min <= spawn-now` as fired; `reminder_active`/`reminder_nudge_at` start empty. (Empty `reminder_fired` would fire a spurious ring the instant you complete a recurring todo: e.g. a "weekly, remind 1 week before" occurrence's 1-week rung fire time = the *new* due − 7 d ≈ now → immediate collapse-ring every cycle.)
- **Complete / soft-delete + done-grace [R-10]**: clear `reminder_active` / `reminder_nudge_at` (and stop routing) at grace **ARM** — the moment the box is ticked (`_arm_grace`), **not** at grace commit. During the ~5 s undo window the todo is still `done=False`, so the scheduler keeps ticking it: without an arm-time clear the alarm keeps blaring on a just-checked task and a pending nudge can even *newly* fire mid-grace. A `tick` already skips `done`/`deleted` (post-commit). Un-ticking during the window does **not** resurrect a ring that already fired (the arm-time clear makes this consistent).
- **Editing `due` [R-12]**: recompute fire times; already-fired rungs stay fired (no surprise re-rings). **If a ring is active** (`reminder_active is not None`) when `due` changes (e.g. a calendar-panel drag, `calendar_week_panel.py:363`), **clear `reminder_active` + `reminder_nudge_at`** — the active ring referenced the old due (a stale "due in 7 days" banner still offering Snooze/Dismiss otherwise). Lower armed rungs re-fire on the recomputed schedule via `tick`.
- **Reopen / restore [R-13]**: `reopen()` / `restore()` flip `done`/`deleted=False` — apply `arm`'s past-rung pre-mark against the current `due` so an item restored *after* its due passed doesn't collapse-fire immediately (matching `arm`'s "never retroactively rings" invariant; today an identical *freshly-armed* past-due todo stays silent, so reopen must too).
- **NL capture** (§7): flows a parsed offset into the created todo.

## 7. NL capture

The parser's existing `reminder` intent (`parser.py`; `CaptureRouter` sets `Capture.reminder`) is extended to also extract a **due-relative offset** from phrases like "remind me 1 day before" / "erinnere mich 1 Tag vorher". A new `Capture.reminder_offset: Optional[int]` (minutes) carries it; the todo-creation path (`Shell._commit_capture` / the reminder→todo funnel) arms `snap_to_rung(offset)` on the new todo via `reminders.arm` — **only when `todo.due is not None` [C-3]** (a date-less reminder can't reach commit today — `missing=["date"]` gates it — but the guard keeps `arm` crash-proof regardless of path). Degrades cleanly: an unparseable/absent offset → a due-dated todo with no armed rung (today's behavior), never a crash.

**Over-long lead time feedback [R-11]:** if the snapped rung's fire time is already past (the NL lead time exceeds time-to-due — e.g. "remind me 1 week before" on a todo due tomorrow), `arm` pre-marks it fired and it never rings. Unlike the picker's greyed rungs, the NL path is otherwise silent — so surface a short confirm-bubble note ("couldn't set that reminder — due is too soon") rather than silently arming-then-suppressing, so the user isn't left believing a reminder is set.

## 8. Flow-harden fold

Two Workflow passes (8 flow lenses + completeness critic → adversarial verify → dedup synthesis): **76 candidate gaps → 17 confirmed** (adversarially verified, default-refute), deduped to **13 requirements + 3 clarifications** folded above. Notable refutations recorded below so they're not re-litigated.

| # | Sev | Requirement (folded inline in §) |
|---|---|---|
| R-1 | **P1** | Cross-context rings use a **dedicated title-less voice key** (`deadline_near_blurred`), never the shared `deadline_near` bucket — the random variant picker can never voice/print a `{title}` cross-context. (§4.3) |
| R-2 | **P1** | On a **context flip / restart**, the active reminder **bubble** is cleared/re-blurred (not just the card) — a title-ful in-context bubble must not persist after leaving that context. (§4.2/§5) |
| R-3 | P2 | **§3 logic bug** — `arm()` **preserves prior fired** (delta, not recompute) so committing the bell never resurrects a **dismissed future rung**. (§3, §4.1) |
| R-4 | P2 | A todo with `reminder_active` set **always renders** (full card / blurred placeholder) regardless of `urgency_tier` — never `hide` — so Snooze/Dismiss stay reachable. (§4.2) |
| R-5 | P2 | **Recurrence** clone re-arms via `arm`'s **past-rung pre-mark against the new due**, not empty `reminder_fired` — no spurious ring on completion. (§6, §3) |
| R-6 | P2 | A fire in **MINI mode** surfaces a reachable **privacy-safe** ack (mini Snooze/Dismiss); the peek-line context-toggle (a reveal) must not be the only ack. (§4.3) |
| R-7 | P2 | Reminder copy is **i18n-aware + relative-consistent**: `{time}` = localized relative phrase; don't reuse the clock-oriented `at/um {time}` dormant lines verbatim. (§4.3) |
| R-8 | P3 | Picker shows a hint when **all rungs are greyed** (due < 5 min), not only for the no-due case. (§4.1) |
| R-9 | P3 | **Immediate catch-up tick at cold launch** (not only +60 s QTimer / WM-resume). (§5) |
| R-10 | P3 | Clear the ring at **grace ARM** (box checked), not grace commit — no blaring on a just-checked task. (§6) |
| R-11 | P3 | **Over-long NL lead time** → user feedback that no ring will occur (mirror the greyed picker). (§7) |
| R-12 | P3 | **Due edit while ringing** clears `reminder_active` (+`nudge_at`); lower rungs re-fire via `tick`. (§6) |
| R-13 | P3 | **Reopen / restore** applies `arm`'s past-rung pre-mark against the current due — no retroactive ring. (§6) |
| C-1 | note | **Snooze escalation near due is INTENDED** (S1 refuted): a lower rung already past re-fires next tick; snooze never pushes past `due`. (§3) |
| C-2 | note | **Banner is the durable cross-restart surface; bubble/tray are transient** (L3 refuted — don't re-assert the bubble on restart). (§1/§5) |
| C-3 | note | Defensive `todo.due is not None` guard at `arm` call sites (L4 refuted as unreachable, but cheap belt-and-suspenders). (§3/§7) |

**Notable refutations (not folded):** L4 date-less-capture `TypeError` — impossible (`missing=["date"]` gates the commit). S3 nudge-not-cancellable — the always-present 🔔 picker + complete/delete already clear `nudge_at`. S4 arm-keeps-nudge — a surviving nudge is *correct* per the ring-lifecycle invariant (always-clearing would drop an unacknowledged ring).

## 9. Non-goals

- ICS `VALARM` round-trip (export armed rungs / import foreign alarms) — deferred to a follow-up.
- Reminders on **notes** (no deadlines) or on calendar/graph surfaces beyond the todo list + mini dock.
- Changing the ladder rungs, `urgency_tier` thresholds, or the ranking.
- Moving the todo's `due` on snooze (explicitly rejected — snooze defers the *reminder*).
- Recurring/repeating reminders beyond the +5 min nudge loop.
- A per-todo custom offset UI (the ladder is fixed; NL capture snaps to it).

## 10. Testing

**Core (`core/reminders.py`, injected `now`):** correct rung fires at its time · multi-rung-past **collapse → one** (rest marked fired) · `reminder_active` blocks a second ring · snooze self-walks to the next lower rung · bottom-rung / nudge snooze → `reminder_nudge_at` set · nudge fires at `nudge_at` · dismiss silences all · `done`/`deleted`/no-`due`/no-`offsets` skipped · `snap_to_rung` boundaries · `armable_offsets` future-only.
  - **`arm` delta [R-3]:** unchanged-commit **preserves** a dismissed future rung in `reminder_fired` (dismiss→arm→no re-ring); dropped rung leaves `fired`; added past rung pre-marked; `fired ⊆ offsets` invariant; empty offsets clears all. **`arm(due=None)` no-crash [C-3].**
  - **Snooze escalation [C-1]:** snooze an upper ring when the next lower rung is already past → it re-fires next tick (asserted intended), and never schedules a fire past `due`.
  - **Recurrence [R-5]:** clone re-arm pre-marks rungs with `new_due - offset ≤ spawn-now` fired → no immediate ring; a future shorter rung still fires.
  - **Reopen/restore [R-13]:** past-due rungs pre-marked fired on reopen → no retroactive collapse-ring.

**Model:** `to_dict`/`from_dict` round-trip of the four fields + tolerant coercion (unknown rung dropped, bad `active` → `None`, bad datetime → `None`).

**Parser:** "remind me 1 day before" / "erinnere mich 1 Tag vorher" → `Capture.reminder_offset` snapped to the right rung; no-offset reminder still routes to a due-dated todo; over-long lead time → feedback path **[R-11]**.

**UI (offscreen):** picker arms/removes offsets, disabled without `due`, greys past rungs, **all-greyed hint [R-8]**, consumed-rung styling [R-3] · banner shows while `reminder_active`, Snooze/Dismiss call the right core fn · **ringing todo renders even when `peek_class`→`hide` [R-4]** · cross-context banner + tray + bubble carry **no title**, and the cross-context bubble uses the **title-less voice key** (no `{title}` variant reachable) **[R-1]** · **context-flip / restart clears the active bubble [R-2]** · relative-time `{time}` copy renders sanely in `de`+`en` (not "at in 30 min") **[R-7]** · fire routing hits bubble + tray + banner · **cold-launch immediate catch-up tick [R-9]** + `_on_resume` catch-up · **grace-arm clears the ring [R-10]** · **due-edit-while-ringing clears active [R-12]** · **MINI fire has a reachable privacy-safe ack [R-6]**.

## 11. Anchors (verified 2026-07-06)

`models.py:75` `Todo` (+ `_clean_*` pattern `models.py:48`) · `core/breaktime.py` `BreakScheduler` (pure-seam precedent) · `ranking.format_time_left` (`ranking.py:103`, relative-only) · `peek_placeholder.blurred_line` / `PeekPlaceholder` (`peek_placeholder.py:33/47`, `needs_tick`/`tick`/`reveal_requested`) · `Shell._on_resume` (`shell.py:963`, `safe_refresh`) + `tray.showMessage` (`shell.py:995`) · `QuickTodoDialog` (`modals.py:155`, `default_due`) + calendar slot (`calendar_week_panel.py:375`) · done-grace `_grace_timers` (`todos_view.py:515`) · recurrence `_spawn_recurrence` (`todo_store.py:175`) · `CaptureRouter` reminder flag (`phase2_stubs.py:164`) · dormant `deadline_near`/`timer_due` (`data/voice_lines.json`).
