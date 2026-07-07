# Phase H — Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in due-relative reminders on todos — a fixed ladder (1w/1d/1h/30m/5m before `due`), ringing via mascot bubble + tray + a card banner until Snoozed (down the ladder, +5 min nudge at the bottom) or Dismissed; cross-context rings stay title-less and ack-able without reveal.

**Architecture:** Pure clock-injected `core/reminders.py` (mirrors `core/breaktime.py`); 4 new tolerant `Todo` fields; a shared `ReminderPicker` widget (card 🔔 + QuickTodoDialog); ring banner on `TodoCard`/`PeekPlaceholder`; Shell drives a coarse 60 s QTimer + cold-launch/resume catch-up ticks and routes fires to bubble/tray/banner. Spec: `docs/superpowers/specs/2026-07-06-phase-h-reminders-design.md` (R-1…R-13, C-1…C-3) — **each task's implementer MUST read the spec sections named in the task.**

**Tech Stack:** Python 3.12, PySide6 (offscreen-testable), pytest.

## Global Constraints

- Suite gate after EVERY task: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → all pass (plain `python` is NOT on PATH).
- New .py files start with the project header comment block (Author/Created/Purpose/Role/Functions — see any existing file).
- Privacy invariant (P1): a cross-context surface (bubble/tray/banner/mini) NEVER renders the todo's title/tags/category, an absolute clock time, or the string "None". Cross-context bubble copy comes ONLY from the title-less `reminder_due_blurred` voice bucket [R-1].
- Snooze NEVER mutates `todo.due`. `arm` NEVER recomputes `reminder_fired` from scratch [R-3]. Nothing re-rings a todo whose `reminder_active` is already set (tick guard-1).
- Conventional commits, one per task. Don't touch unrelated code; match file style.

### Shared interface reference (source of truth for names/types across tasks)

```python
# serenity/core/reminders.py  (T2–T4)
RUNG_MINUTES: list[int] = [10080, 1440, 60, 30, 5]        # descending
RUNG_LABELS: dict[int, str]                                # {10080:"1 week",1440:"1 day",60:"1 hour",30:"30 min",5:"5 min"}
NUDGE_MINUTES = 5
NUDGE_SENTINEL = 0
@dataclass(frozen=True)
class Fire: todo_id: str; offset: int; is_nudge: bool
def snap_to_rung(minutes: int) -> int
def armable_offsets(todo, now: datetime) -> list[int]
def pre_mark_past(todo, now: datetime) -> None
def tick(todo, now: datetime) -> Optional[Fire]
def acknowledge_snooze(todo, now: datetime) -> None
def acknowledge_dismiss(todo) -> None
def silence(todo) -> None                                  # clear active+nudge ONLY (not fired)
def arm(todo, offsets: list[int], now: datetime) -> None   # delta semantics [R-3]
def relative_phrase(due: datetime, now: datetime, lang: str) -> str   # localized [R-7]

# Todo fields (T1): reminder_offsets: list[int]; reminder_fired: list[int];
#                   reminder_active: Optional[int]; reminder_nudge_at: Optional[datetime]
# Capture field (T7): reminder_offset: Optional[int]   (minutes, pre-snap)

# UI signals:
# ReminderPicker(due_provider, initial, fired) . changed = Signal(list) . selected() -> list[int] . refresh()
# TodoCard: reminders_changed = Signal(object); ring_snooze = Signal(object); ring_dismiss = Signal(object)
# PeekPlaceholder: ring_snooze = Signal(); ring_dismiss = Signal()
# TodosView: reminders_changed = Signal(); ring_acked = Signal(object)
# MiniWindow: ring_snooze = Signal(str); ring_dismiss = Signal(str)     # todo_id
```

---

### Task 1: `Todo` model — 4 reminder fields + tolerant coercion

**Files:** Modify `serenity/core/models.py` (Todo dataclass ~75, `to_dict` ~118, `from_dict` ~142, new `_clean_*` helpers next to `_clean_context` ~48); test `tests/test_models.py` (extend). **Spec §2.**
**Produces:** the 4 fields above, defaults `[] / [] / None / None`; coercion helpers `_clean_rungs(v, extra=())` (list of known ints, deduped, desc order) and `_clean_active(v)` (int in `RUNG_MINUTES∪{0}` else None). Import `RUNG_MINUTES` lazily/duplicate the literal set in models.py to avoid a core→core cycle — models.py must NOT import reminders.py (reminders imports models types via duck-typing only; actually neither imports the other: hardcode `_KNOWN_RUNGS = {10080, 1440, 60, 30, 5}` in models.py with a comment pointing at reminders.RUNG_MINUTES).

- [ ] Failing tests: round-trip all 4 via `to_dict`/`from_dict`; old dict without the keys → defaults; `reminder_offsets=60` (non-list) → `[]`; `[60, 99, 60, "x"]` → `[60]`; `reminder_fired=[0, 5]` kept (sentinel allowed in fired); `reminder_active=99` → `None`; `reminder_active=0` kept; `reminder_nudge_at="garbage"` → `None`; ISO datetime round-trips.
- [ ] Implement: fields + `to_dict` entries (`_iso` for nudge_at) + `from_dict` via the two cleaners (`_parse_iso` for nudge_at).
- [ ] Full suite green → commit `feat(models): reminder ladder fields + tolerant coercion (Phase H §2)`.

### Task 2: `core/reminders.py` — constants, `Fire`, `snap_to_rung`, `armable_offsets`, `relative_phrase`

**Files:** Create `serenity/core/reminders.py` (with header block); test create `tests/test_reminders.py`. **Spec §3 + §4.3 [R-7].**
**Produces:** everything in the interface reference except tick/ack/arm/silence/pre_mark_past (T3/T4). `relative_phrase(due, now, "en")` may delegate to `ranking.format_time_left`; `"de"` renders `"in 3 Std 10 Min"` / `"in 30 Min"` / `"seit 12 Min überfällig"` — same rounding rules as `format_time_left` (`ranking.py:103`: round up when future, down when overdue), NEVER a clock time.

- [ ] Failing tests: `snap_to_rung` boundaries (1440→1440; 700→1440 vs 60 — nearest by absolute distance, ties toward the LARGER/earlier rung; 3→5; 999999→10080); `armable_offsets`: due 2 h out → `[60, 30, 5]` (10080/1440 past); no due → `[]`; `relative_phrase` en/de forms + overdue + no `:` digits.
- [ ] Implement (pure, no Qt/no wall clock).
- [ ] Full suite green → commit `feat(core): reminders module — ladder constants, snap, armable, relative phrase`.

### Task 3: `reminders.tick` — guards, nudge, collapse

**Files:** Modify `serenity/core/reminders.py`; extend `tests/test_reminders.py`. **Spec §3 (tick steps 1–3).**
**Produces:** `tick(todo, now) -> Optional[Fire]` exactly per spec: skip `done`/`deleted`/no-`due`/no-`offsets` → `None`; (1) `reminder_active is not None` → `None`; (2) nudge due → `reminder_active = NUDGE_SENTINEL`, clear `nudge_at`, `Fire(offset=0, is_nudge=True)`; (3) collect armed-unfired with `due - offset·min <= now` → mark ALL fired, `reminder_active = min(...)`, `Fire(offset=min, is_nudge=False)`.

- [ ] Failing tests (all with injected `now`): single rung fires exactly at its time (not 1 s before); collapse: armed [1440,60,5] all past → ONE Fire(offset=5), `fired == [1440,60,5]-set`, active=5; active set → tick returns None even with past rungs; nudge fires at nudge_at (and wins over step-3 rungs — order check); done/deleted/no-due/no-offsets → None and NO mutation; fire mutates fired+active but never `due`.
- [ ] Implement.
- [ ] Full suite green → commit `feat(core): reminders.tick — guard/nudge/collapse (Phase H §3)`.

### Task 4: acknowledge_snooze / acknowledge_dismiss / silence / arm / pre_mark_past

**Files:** Modify `serenity/core/reminders.py`; extend `tests/test_reminders.py`. **Spec §3 [R-3, C-1, C-3] — read the arm delta bullets verbatim.**
**Produces:** the 5 remaining functions. `pre_mark_past(todo, now)`: `reminder_fired = sorted-desc unique union(fired, [o for o in offsets if due - o·min <= now])` (no-op without due). `silence(todo)`: `reminder_active = None; reminder_nudge_at = None`. `arm` delta semantics: dropped rungs leave offsets AND fired; added rungs pre-marked iff past; unchanged keep fired status; `fired ⊆ offsets` invariant; clear active/nudge_at if they reference a dropped rung (active==NUDGE_SENTINEL is NOT a rung reference — a pending/ringing nudge survives re-arm); empty `offsets` clears every field; guard `due is None` → set offsets, fired=[], no fire-time math [C-3].

- [ ] Failing tests: snooze with smaller armed-unfired rung → only active cleared (ladder self-walks); snooze at bottom/nudge → nudge_at = now+5 min, active cleared; snooze while active is None → no-op; **escalation [C-1]**: armed [60,5], 60 collapsed-fired+ringing, 5's time already past → snooze clears active and the NEXT tick fires 5 immediately (assert exactly this — it is intended); dismiss → fired == offsets, active/nudge None; **arm preserves dismissed [R-3]**: dismiss with a future rung, re-`arm` same offsets → that rung STAYS in fired (no re-ring on later tick); arm drops a rung → gone from both; arm adds past rung → pre-marked fired; arm([]) clears all; arm with due=None doesn't crash; pending nudge survives an arm that keeps ≥1 rung.
- [ ] Implement.
- [ ] Full suite green → commit `feat(core): reminder acknowledge/arm — delta semantics, snooze escalation (R-3/C-1/C-3)`.

### Task 5: store lifecycle — complete/soft-delete silence, recurrence re-arm, reopen pre-mark

**Files:** Modify `serenity/core/todo_store.py` (`complete` ~108, `soft_delete` ~133, `reopen` ~123, `_spawn_recurrence` ~175); test `tests/test_stores.py` (extend). **Spec §6 [R-5, R-13].**
**Consumes:** `reminders.silence`, `reminders.pre_mark_past` (T4).

- [ ] Failing tests: `complete()` and `soft_delete()` on a ringing todo → active+nudge cleared (fired untouched); recurring todo armed `[10080]` due≈now completed → clone has `reminder_offsets == [10080]`, the 10080 rung already in `reminder_fired` (its fire time vs the NEW due is past → NO ring on the next tick) [R-5]; recurring armed `[5]` weekly → clone's 5-rung NOT pre-marked (future); clone active/nudge_at are None; `reopen()` of a todo whose due passed while trashed → past rungs pre-marked, next `tick` returns None [R-13].
- [ ] Implement: `complete`/`soft_delete` call `reminders.silence(t)`; `_spawn_recurrence` clone gets `reminder_offsets=list(done_todo.reminder_offsets)` then `reminders.pre_mark_past(clone, datetime.now())`; `reopen` calls `reminders.pre_mark_past(t, datetime.now())`.
- [ ] Full suite green → commit `feat(store): reminder lifecycle — silence on complete/delete, recurrence+reopen pre-mark (R-5/R-13)`.

### Task 6: due-edit clears an active ring (calendar drag)

**Files:** Modify `serenity/ui/calendar_week_panel.py` (`_handle_drop` ~348–366); test `tests/test_ui_calendar_week.py` (extend). **Spec §6 [R-12].**
**Consumes:** `reminders.silence` (T4).

- [ ] Failing test: drop a ringing todo (`reminder_active=60`, `reminder_nudge_at` set) on a new slot → both cleared, `due` updated, `reminder_fired` untouched.
- [ ] Implement: in `_handle_drop`, after computing the new `t.due` and before `self.todo_store.update(t)`: `if t.reminder_active is not None or t.reminder_nudge_at is not None: reminders.silence(t)`.
- [ ] Full suite green → commit `feat(calendar): due edit while ringing silences the stale ring (R-12)`.

### Task 7: parser + capture — `reminder_offset` extraction (DE+EN)

**Files:** Modify `serenity/core/parser.py` (Capture ~61, new regex near `_DATE_TRIM_RE` ~142, wire in `parse_capture` ~181) and `serenity/core/phase2_stubs.py` (`_merge` ~150–185: copy the parser-derived `reminder_offset` onto the merged capture — LLM must never override it, mirroring how `date` stays parser-derived); tests `tests/test_parser.py` + `tests/test_phase2_stubs.py` (extend). **Spec §7.**
**Produces:** `Capture.reminder_offset: Optional[int]` (minutes, pre-snap). Extraction pattern (offset phrase → minutes, then strip from title): `(\d+)\s*(min(uten)?|minutes?|stunden?|std|hours?|h|tag(e|en)?|days?|d|wochen?|weeks?|w)\s*(vorher|davor|before|in advance|früher|frueher)` case-insensitive; units → minutes (min=1, h=60, d=1440, w=10080).

- [ ] Failing tests: `"remind me 1 day before dentist"` → intent reminder, `reminder_offset == 1440`, title == "dentist" (offset phrase stripped, `missing == ["date"]` since no date); `"Erinnerung Zahnarzt morgen 1 Tag vorher"` → offset 1440 + date parsed + title "Zahnarzt"; `"remind me 30 minutes before standup tomorrow 9:00"` → 30; `"reminder call mom tomorrow"` → offset None (unchanged today-behavior); `"erinnere mich 2 Wochen vorher"` → 20160 (pre-snap — snapping happens at arm time); phase2 `_merge` keeps the parser offset when the LLM emits a different/absent one.
- [ ] Implement (strip the matched phrase from `rest` BEFORE `_clean_title`; do not touch `_DATE_TRIM_RE`).
- [ ] Full suite green → commit `feat(parser): due-relative reminder offset extraction DE+EN (Phase H §7)`.

### Task 8: voice lines — `reminder_due` + `reminder_due_blurred` buckets

**Files:** Modify `serenity/data/voice_lines.json` (two NEW top-level keys, de+en, ≥3 variants each); test `tests/test_reminders.py` or `tests/test_task_lines.py`-adjacent — add `tests/test_reminders.py::test_voice_buckets_*`. **Spec §4.3 [R-1, R-7].**
**Produces:** `reminder_due`: variants formatted for a RELATIVE `{time}` phrase + `{title}` (e.g. en `"⏰ \"{title}\" is due {time}."`, de `"⏰ \"{title}\" ist {time} fällig."` — phrasing must read correctly with `{time}`=`"in 30 min"`/`"in 30 Min"`); `reminder_due_blurred`: NO `{title}` in ANY variant (e.g. en `"🔒 A {context} item is due {time}."`, de `"🔒 Ein {context}-Eintrag ist {time} fällig."`). The dormant `deadline_near`/`timer_due` buckets stay untouched (still dormant).

- [ ] Failing tests: load `voice_lines.json` → both keys exist with de+en; **structural leak check [R-1]**: no variant in `reminder_due_blurred` (any lang) contains `{title}`; every variant in both buckets contains `{time}`; `VoiceLines.say("reminder_due_blurred", "de", time="in 30 Min", context="Private")` returns text without "{" (all slots filled).
- [ ] Implement (JSON edit only).
- [ ] Full suite green → commit `feat(voice): reminder_due + title-less reminder_due_blurred buckets, relative-time phrasing (R-1/R-7)`.

### Task 9: `ReminderPicker` widget + TodoCard 🔔 + QuickTodoDialog row

**Files:** Create `serenity/ui/reminder_picker.py`; modify `serenity/ui/todos_view.py` (TodoCard: 🔔 QToolButton + QMenu/QWidgetAction popover; new signal `reminders_changed = Signal(object)`; TodosView: handler calls `reminders.arm(todo, offsets, datetime.now())` + `self.store.save()` + `self.refresh()` + emit `reminders_changed = Signal()`), `serenity/ui/modals.py` (QuickTodoDialog: picker row bound to a `due_provider` that parses the current `when` field / `default_due`; on `_save` after `todo_store.add`: if `picker.selected()`: `reminders.arm(todo, picker.selected(), datetime.now()); todo_store.save()`); tests create `tests/test_reminder_picker.py`, extend `tests/test_modals.py`. **Spec §4.1 [R-8, R-3-styling]. Calendar-slot dialog is QuickTodoDialog(default_due=…) → gets the row for free.**
**Produces:** `ReminderPicker(due_provider: Callable[[], Optional[datetime]], initial: list[int] = (), fired: list[int] = ())` with 5 checkboxes (RUNG_LABELS order), `changed = Signal(list)`, `selected() -> list[int]`, `refresh()` re-evaluating: no due → all disabled + hint label "Set a due date to add reminders"; due but `armable_offsets` empty → all disabled + hint "Due too soon for a reminder" [R-8]; past rungs individually disabled; rungs in `fired` get a dimmed "already fired" style but stay toggleable (untick→retick re-arms [R-3]).

- [ ] Failing tests: no due → 5 disabled + first hint; due 2 h out → exactly [60,30,5] enabled; due 2 min out → all disabled + "too soon" hint [R-8]; toggling emits `changed` with the selected list; fired rung shows dimmed style property; QuickTodoDialog: type a `when` with a due 2 days out, tick "1 day", save → created todo has `reminder_offsets == [1440]` and empty fired; TodoCard 🔔 exists for a due-dated todo and commits arm via TodosView (todo in store gains offsets, store saved).
- [ ] Implement.
- [ ] Full suite green → commit `feat(ui): shared ReminderPicker — card bell + quick-todo row (§4.1, R-8)`.

### Task 10: ring banner (TodoCard + PeekPlaceholder) + always-render bypass + grace-arm silence

**Files:** Modify `serenity/ui/todos_view.py` (TodoCard banner strip; refresh classification bypass; `_arm_grace`; ack handlers; `ring_acked = Signal(object)`), `serenity/ui/peek_placeholder.py` (buttons row when `todo.reminder_active is not None`; `ring_snooze`/`ring_dismiss` signals; banner text stays `blurred_line`); tests extend `tests/test_ui_filter.py` + `tests/test_peek_placeholder.py` + `tests/test_todos_grace.py`. **Spec §4.2 [R-4], §6 [R-10].**
**Consumes:** `reminders.acknowledge_snooze/acknowledge_dismiss/silence` (T4).

- [ ] Failing tests: card of a ringing in-context todo shows a banner (`⏰` + `format_time_left` text + Snooze + Dismiss); Snooze click → `acknowledge_snooze` effect (active cleared) + store saved + `ring_acked` emitted; Dismiss likewise; **[R-4] bypass**: a NON-urgent (`due` 7 days out) other-context todo with `reminder_active` set renders as exactly one `PeekPlaceholder` (not dropped, not counted hidden), and same-context/state-filtered renders a full card; placeholder buttons don't trigger the reveal arm (clicking Snooze ≠ mousePressEvent arm); placeholder privacy: no title anywhere with the banner present; **[R-10]**: `_arm_grace` on a ringing todo clears active+nudge (banner gone on the grace card), un-tick within the window does NOT resurrect it.
- [ ] Implement: classification override in `refresh()` after `cls = ranking.peek_class(...)`:
  ```python
  if t.reminder_active is not None and cls == "hide":
      cls = ("peek_blurred" if t.context in ("business", "private") and t.context != ctx
             else "peek_full")   # a ringing todo always has a surface (R-4)
  ```
  `_arm_grace` start: `if todo.reminder_active is not None or todo.reminder_nudge_at is not None: reminders.silence(todo); self.store.save()`.
- [ ] Full suite green → commit `feat(ui): ring banner + always-render bypass + grace-arm silence (R-4/R-10)`.

### Task 11: Shell scheduler + fire routing + catch-up ticks

**Files:** Modify `serenity/ui/shell.py` (init after `_board_timer` block ~258: `_reminder_timer` 60 s + immediate `self._reminder_tick()` [R-9]; `_on_resume` ~963: tick before `safe_refresh`; new `_reminder_tick`, `_sync_reminder_timer`, `_route_fire`; connect `todos_view.reminders_changed → _sync_reminder_timer` and `todos_view.ring_acked → _on_ring_acked`); tests create `tests/test_reminder_shell.py`. **Spec §4.3 + §5 [R-9, C-2].**
**Consumes:** T3 tick, T8 voice buckets, `reminders.relative_phrase`.
**Produces:** `Shell._ring_bubble: Optional[str]` (todo_id of the bubble currently showing a ring), cleared in `_on_ring_acked` (also `self.mascot.bubble.hide()`).

- [ ] Failing tests (offscreen Shell): armed todo crossing its fire time + `_reminder_tick()` → todo mutated+saved (reload store: fired/active set), bubble text non-empty, tray-message call recorded (monkeypatch `tray.showMessage`), todos view refreshed; **in-context copy contains the title, cross-context copy does NOT and contains the context label** (drive both by flipping `settings.current_context`); cross-context `{time}` phrase has no `:` clock digits; one `store.save()` per tick with fires (monkeypatch-count); tick with nothing due → no bubble change; `_sync_reminder_timer`: no armed todos → timer inactive, one armed → active; cold-launch: constructing Shell with an already-past rung fires immediately [R-9]; `_on_resume` ticks; ack → `_ring_bubble` cleared + bubble hidden.
- [ ] Implement `_route_fire(fire, now)`:
  ```python
  t = self.todo_store.get(fire.todo_id)
  if t is None: return
  ctx = self.settings.context()
  cross = t.context in ("business", "private") and t.context != ctx
  phrase = reminders.relative_phrase(t.due, now, self._lang)
  if cross:
      msg = self.voice.say("reminder_due_blurred", self._lang, time=phrase,
                           context=(t.context or "").capitalize())
  else:
      msg = self.voice.say("reminder_due", self._lang, time=phrase, title=t.title)
  mascot = self._mini.mascot if (self._mode == MODE_MINI and self._mini is not None) else self.mascot
  mascot.says(msg)
  self._ring_bubble = t.id
  if self.tray.isVisible():
      self.tray.showMessage("Serenity", msg, QSystemTrayIcon.Information, 4000)
  ```
- [ ] Full suite green → commit `feat(shell): reminder scheduler — 60s tick, cold-launch/resume catch-up, fire routing (§5, R-9)`.

### Task 12: context-flip bubble re-blur + MINI ack affordance

**Files:** Modify `serenity/ui/shell.py` (`_sync_context` ~881 end: re-route the ring bubble per the NEW context; connect mini signals), `serenity/ui/mini_window.py` (`refresh_todo` ~138: ring line + Snooze/Dismiss buttons when any active todo rings; `ring_snooze`/`ring_dismiss = Signal(str)`); tests extend `tests/test_reminder_shell.py` + `tests/test_ui_context.py`. **Spec §4.2/§4.3 [R-2, R-6].**

- [ ] Failing tests: **[R-2]** fire in-context (title in bubble) → `set_context(other)` → bubble text now title-less (blurred variant) while `reminder_active` persists; flip back → may re-title (assert no title while cross); **[R-6]** in MINI mode a fire routes to `self._mini.mascot` (bubble text set there), MiniWindow shows a ring line + 2 buttons; cross-context mini ring line is `blurred_line` (no title) and the buttons snooze/dismiss WITHOUT flipping context (settings.context unchanged, `reminder_active` cleared); the peek-line context-toggle still works separately.
- [ ] Implement: `_sync_context` end — `if getattr(self, "_ring_bubble", None): t = self.todo_store.get(self._ring_bubble); if t is not None and t.reminder_active is not None: self._route_fire_bubble_only(t)` (factor the bubble-choice out of `_route_fire` so both share the cross/in-context copy rule); mini buttons → shell handlers → `reminders.acknowledge_*` + save + `refresh_todo` + clear bubble.
- [ ] Full suite green → commit `feat(ui): context-flip re-blurs the ring bubble + mini-dock privacy-safe ack (R-2/R-6)`.

### Task 13: NL capture funnel — arm on commit + too-soon feedback

**Files:** Modify `serenity/ui/shell.py` (`_commit_capture` ~757: after `todo_store.add(...)` for `cap.kind == "todo"`); tests extend `tests/test_reminder_shell.py`. **Spec §7 [R-11, C-3].**
**Consumes:** T7 `Capture.reminder_offset`, T4 `arm`, T2 `snap_to_rung`.

- [ ] Failing tests: commit a capture with `reminder_offset=1440` + due 3 days out → created todo has `reminder_offsets == [1440]`, unfired; offset with due=None → no crash, no offsets [C-3]; **[R-11]** offset 10080 with due tomorrow → the rung is pre-marked fired AND the confirm bubble says the too-soon line (assert the bubble text differs from the plain `voice_routed_todo` line).
- [ ] Implement: keep a reference to the created todo; `if cap.reminder_offset and todo.due is not None: rung = reminders.snap_to_rung(cap.reminder_offset); reminders.arm(todo, [rung], datetime.now()); self.todo_store.save(); too_soon = rung in todo.reminder_fired` → when `too_soon`, append/replace the mascot line with a short bilingual "couldn't set that reminder — due is too soon" notice (hardcoded two-string dict is fine; no new voice bucket needed).
- [ ] Full suite green → commit `feat(capture): NL reminder offset arms the rung + too-soon feedback (§7, R-11)`.

### Task 14: docs + reindex + final gate

**Files:** Modify `notes/1_Planning.md` (Phase H wrap), `notes/5_Interaction_Flows.md` (area 10: reminders flows — the §8 fold table summary), `notes/2_System_Arch.md` (one-liner: reminders scheduler seam). **No code.**

- [ ] Update the three notes; run the FULL suite one more time; `npx gitnexus analyze` (PR boundary per CLAUDE.md policy).
- [ ] Commit `docs(notes): Phase H reminders wrap + flows`.

## After the plan: QA pipeline

criticizer → optimizer → test-agent (adversarially verified, fix between, suite green after each) — per `CLAUDE.md` and memory `feature-qa-agent-pipeline`.
