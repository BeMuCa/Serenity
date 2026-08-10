# Calendar-expand slice (c) — ICS round-trip (import + export) — design

_Spec date: 2026-06-30. Branch `wf/ship-wave`. Final slice of the Calendar-expand feature
(slices (a) read-only grid, (b) drag-schedule/create already shipped). Brainstormed
2026-06-30; flow-hardened via the 6-flow Workflow (`wf_37fa3545-3c1`, 58 raw → 2 P1 / 16 P2
/ 9 P3 confirmed)._

## 1. Goal

Round-trip Serenity todos through the iCalendar (`.ics`) format so the user can:
- **Export** active todos-with-a-due to a `.ics` file and open it in Google / Outlook / Apple Calendar.
- **Import** an external `.ics` and create todos from its events.
- Keep two Serenity instances (work + personal laptop) in sync via repeated export/import
  **without duplicating** the same logical todo (UID-based dedup).

Hand-rolled, **zero new dependencies** (Python stdlib `zoneinfo` only). All format logic lives
in a pure, Qt-free `core/ics.py` that is fully headless-testable; the UI only drives dialogs.

## 2. Scope

**In:** export (all active-with-due todos) · import (create + update via UID match) ·
a `Todo.ics_uid` field · two buttons on the compact Calendar-tab toolbar · a preview-then-confirm
import dialog · defensive parsing of untrusted files.

**Out:** recurrence in the wire format (a recurring todo exports as a single event at its
`due`; a foreign `RRULE` imports only its first occurrence, recorded as skipped-recurrence) ·
subtasks / tags / linked-notes in the payload · cross-**timezone** sharing (see §3) ·
VTIMEZONE generation · `.ics` feeds / subscriptions / live sync.

## 3. Datetime model (CORRECTED — the P1 foundation)

`Todo.due` is a **naive `datetime` in LOCAL wall-clock time** — verified in code, not assumed:
- `models._iso`/`_parse_iso` do no tz handling (`isoformat()` / `fromisoformat()` round-trip verbatim).
- `ranking.seconds_until_due` computes `todo.due - datetime.now()` (naive local) — only correct if `due` is naive local.
- `parser.parse_natural_date` sets `RETURN_AS_TIMEZONE_AWARE: False` → naive, relative to naive-local `now`.

> The original brainstorm "locked" `due` as UTC and timed export as `...Z`. **That was wrong**
> and would shift every timed event by the UTC offset. The flow-harden dissent (IMP-14/EXP-6)
> was correct. Corrected below.

**Export (naive-local → wire):**
- **Timed** (`_has_time` true, i.e. not exactly midnight) → **floating** local time, no `Z`, no TZID:
  `DTSTART:20260630T170000`. Floating = "same wall-clock everywhere" → exact round-trip on the
  user's own machines; no VTIMEZONE, no DST math.
- **All-day** (exactly midnight) → `DTSTART;VALUE=DATE:20260630`, `DTEND;VALUE=DATE:20260701`
  (next day; avoids zero-length all-day misrender — EXP-8).
- **Timed `DTEND`** = `DTSTART + 1h` (floating).
- `DTSTAMP` = generation time in **UTC** (`datetime.now(timezone.utc)` → `...Z`) — RFC-required
  bookkeeping; UTC is correct here (P3 EXP-11).

**Import (wire → naive-local):** every `ParsedEvent.when` is normalized to **naive LOCAL**:
- floating (no `Z`, no `TZID`) → stored **verbatim** as naive local;
- UTC `...Z` → `dt.astimezone().replace(tzinfo=None)` (aware-UTC → local → drop tz);
- `TZID=<zone>` → `dt.replace(tzinfo=ZoneInfo(zone)).astimezone().replace(tzinfo=None)`; an
  unresolvable zone (`ZoneInfoNotFoundError`/`ValueError`/`KeyError`) → **skip that event** with a
  reason (P3 IMP-13), never abort the whole parse;
- `VALUE=DATE` → naive midnight (all-day).

> Known model limit (P3, accepted): a genuinely *timed* foreign event that lands on exactly
> local-midnight is indistinguishable from all-day (`_has_time` reads midnight as all-day, and
> `Todo` has no `has_time` flag). Documented, not fixed.

**Cross-timezone caveat (accepted):** floating times shift if the two machines are in different
zones. Out of scope — the use case is one person's own laptops. (Alternative `TZID`+VTIMEZONE
export is deferred.)

## 4. `core/ics.py` — pure module API

```
todos_to_ics(todos, now) -> str
parse_ics(text)          -> ParsedCalendar
reconcile(parsed, existing_todos) -> ImportPlan
```

- `ParsedEvent`: `uid: str|None`, `title: str`, `when: datetime` (naive local), `all_day: bool`,
  `category: str|None`, `had_rrule: bool`.
- `ParsedCalendar`: `events: list[ParsedEvent]`, `skipped: list[tuple[str, str]]` (label, reason),
  `is_calendar: bool` (envelope `BEGIN/END:VCALENDAR` seen — lets the UI tell "not a calendar
  file" from "valid but empty"; IMP-16/IMP-17/C-UI-08).
- `ImportPlan`: `to_create: list[ParsedEvent]`, `to_update: list[(Todo, ParsedEvent)]`,
  `skipped: list[tuple[str, str]]` (parse skips + reconcile skips merged).

All three are pure and headless-tested. The UI passes `now=datetime.now()` and
`store.all()`; nothing in `core/ics.py` imports Qt or touches the filesystem.

## 5. Export — spec

1. **Predicate + empty guard (P2 EXP-2/C-UI-01):** `exportable = [t for t in store.all() if
   t.due is not None and not t.done and not t.deleted]`. **Not** `store.active()` (it keeps
   due-less todos). If `exportable` is empty → `QMessageBox.information("Nothing to export")`
   and **return before** opening the save dialog.
2. `path = QFileDialog.getSaveFileName(default="serenity-calendar-2026-06-30.ics")`.
   **Cancel guard (P2 EXP-9/C-UI-02):** `if not path: return` — no write, no toast.
3. **Suffix force (P2 C-UI-04):** if `path` has no `.ics` suffix, append it. (Prevents OS
   non-association and prevents a typed name like `todos.json` from clobbering the live store.)
4. `text = todos_to_ics(exportable, datetime.now())`.
5. **Serialization (P1 EXP-5):** every `SUMMARY`/`CATEGORIES` TEXT value is RFC-5545-escaped —
   `\` → `\\`, `;` → `\;`, `,` → `\,`, newline → `\n`, drop bare CR. For `CATEGORIES`, escape
   commas *within* each value but keep the value-joining commas literal. Then **75-octet
   (UTF-8 byte) line-folding** of every emitted content line (continuation = CRLF + single space).
6. **Write (P2 EXP-3/EXP-4/C-UI-03):** `atomic_write_text(path, text)` inside `try/except
   OSError` → on `OSError` show `QMessageBox.warning("Could not write the calendar file: <exc>")`
   and return; show the success toast **only after** a clean write return (per the
   `settings_window.py:737` precedent).

`UID` per event = `todo.ics_uid or todo.id`.

## 6. Import — spec

1. `path = QFileDialog.getOpenFileName()`. Cancel guard `if not path: return` (P2 C-UI-05/IMP-1).
2. **Size cap BEFORE read (P2 IMP-02/IMP-2/C-UI-06):** `os.stat(path).st_size > 5 MB` →
   `QMessageBox.warning` + return. Then read **bounded**: `f.read(CAP+1)` and reject on overflow
   (covers growing / special files). Never `len()`-after-full-read.
3. **Decode (P2 IMP-03/IMP-3):** read bytes; strip a UTF-8 BOM; detect a UTF-16 BOM (Outlook) and
   decode accordingly; otherwise UTF-8. `UnicodeDecodeError` (a `ValueError`, not `OSError`) →
   `QMessageBox.warning("Not a readable text/.ics file")` + return. `core/ics.py` stays text-only.
4. **Read failure (P2 IMP-4):** wrap the read in `try/except OSError` (permission / locked-mid-sync
   / TOCTOU delete) → warn + return (shares the size-cap handler).
5. `parsed = parse_ics(text)` — defensive:
   - require `BEGIN/END:VCALENDAR`; if absent set `is_calendar=False` (P3 C-UI-07).
   - unfold folded lines; unescape TEXT (P2 IMP-07).
   - each `VEVENT` needs matching `BEGIN/END:VEVENT`; an unterminated trailing event (EOF) →
     skip-with-reason, never a half-event (P3 IMP-5/G9).
   - ignore unknown properties; a malformed event → skip-with-reason. If the event lacks
     `SUMMARY`, the reason uses a fallback label (e.g. `"(event #N)"`) so the reason is never
     `None` (P2 IMP-08).
   - per-event datetime/zone resolution wrapped in `try/except` → skip that event (P3 IMP-13).
   - a `VEVENT` with an `RRULE` → import the `DTSTART` occurrence as one todo **and** append a
     skip note `"recurring event — only the first occurrence imported"` (`had_rrule=True`; P3 IMP-12).
6. `plan = reconcile(parsed, store.all())`:
   - **No UID (P2 IMP-08/G14):** skip with reason `"no UID — cannot dedup"` (never import an
     un-dedupable event).
   - **Duplicate UID within the file (P2 IMP-11/G4):** first wins; the rest → skip
     `"duplicate UID in file"`. Guarantee ≤ one plan entry per existing todo.
   - **Match scope = ACTIVE only (P2 IMP-10/G10/C-UI-16):** build the match index from
     `not done and not deleted` todos, keyed by `id` and `ics_uid`. A UID colliding only with a
     trashed/completed todo falls to `to_create` — never silently mutate or resurrect trash.
   - **Fixpoint (P2 G11):** classify a UID-matched event as `to_update` **only if** a substantive
     field (normalized `due` / `title` / `category`) actually differs; equal-on-all → drop. A
     no-op re-import yields zero updates. (Never key change-detection on `DTSTAMP` — every export
     would look changed.)

## 7. Apply — spec (on Import confirm)

- **Re-entry / idempotency guard (P2 G6/G8, C-UI-11):** disable the Import button / set a one-shot
  flag and `accept()` before applying, so a double-click or force-quit can't double-apply.
- **Re-resolve against the live store at apply time (P2 G8, P3 IMP-12):** the plan may be stale
  (the user deleted/added todos while the modal was open). For each `to_update`, re-find the target
  by `id`/`ics_uid`; if it's gone/purged → skip it. For each `to_create`, if its UID now already
  exists → treat as update (or skip), never create a duplicate.
- **Creates:** `store.add(t, persist=False)` with `t.ics_uid = parsed.uid`.
- **Updates (P2 G7 field-scope):** mutate **exactly** `{due, title, category}`; leave
  `recurring`, `subtasks`, `depends_on`, `timer*`, `linked_note_ids`, `done`, `deleted`
  untouched. Then `store.update(t, persist=False)`.
- **Transactional single save (P2 G1/G9/IMP-8/IMP-15):** after the whole plan is staged in
  memory, call `store.save()` **once**, wrapped in `try/except OSError`. On failure → `store.reload()`
  (drop the in-memory changes) and show an error; do **not** fire the refresh. This makes import
  all-or-nothing: a crash mid-loop can't leave a half-applied vault that the next re-import would
  then partly-dedup against.
- **Refresh wiring (P2 G5/C-UI-13):** the compact `CalendarView` today has **no `wrote` signal**.
  Add `wrote = Signal()`, connect it to `shell._on_calendar_wrote` (the slice-(b) cross-surface
  refresh path), and emit it after a successful import so the Todos list + the grid update. Also
  type-guarded-refresh an open expanded `CalendarWeekPanel` pop-out (mirror the slice-(b) hook).

## 8. Import preview dialog — spec (`ui/ics_import_dialog.py`)

- **Zero-importable (P2 C-UI-08, P3 IMP-16/17):** if `to_create` and `to_update` are both empty,
  show an **info** dialog ("No importable events found" + the skipped reasons) — **not** an
  actionable preview with a disabled button. If `not is_calendar`, the message is "Not a valid
  calendar file" instead.
- Otherwise show counts **N new / M updates / K skipped** (computed from the full lists) with:
  - per-`to_update` row: a **field-level old → new diff** (only changed fields) so a stale
    overwrite is reviewable — explicitly **not** DTSTAMP/`updated`-based (P2 G3).
  - a `"K duplicate UIDs collapsed"` line when dedup merged events, so N/M aren't silently
    under-counted (P3 G14).
  - a recurrence-skip line when any `had_rrule` event was reduced to its first occurrence.
  - a warning marker on `to_update` rows whose target is a **recurring** todo (the recurrence is
    preserved, only due/title/category change) (P2 G7).
- **Row cap (P3 C-UI-15):** render at most ~20 rows per section + "and N more"; counts always from
  the full lists. Sanitize raw file-sourced strings before display.
- Buttons: **[Import] / [Cancel]**. **Nothing is written until Import** is pressed.

## 9. Model change

`core/models.py`: add `ics_uid: Optional[str] = None` to `Todo`, plus `"ics_uid": self.ics_uid`
in `to_dict` and `ics_uid=d.get("ics_uid")` in `from_dict` (backward-compatible — old todos load
with `None`). Low fan-out; verify no positional `Todo(...)` constructor breaks (it's appended last
with a default).

## 10. Folded safety nets (traceability)

**P1 (2):** EXP-5 TEXT-escape + 75-octet fold · IMP-04/IMP-14/EXP-6 naive-**local** datetime
normalization (§3).

**P2 (16):** EXP-2 empty-set predicate · EXP-9 cancel guards · EXP-3/EXP-4 export OSError ·
C-UI-04 suffix force · IMP-02 pre-read size cap · IMP-03 decode/BOM · IMP-4 read OSError ·
IMP-08/IMP-11 no-UID + duplicate-UID rules · IMP-10 active-only match scope · G3 preview diff ·
G11 reconcile fixpoint · G1/G9 transactional single-save · G6/G8 idempotent re-entry + live
re-resolve · G5/C-UI-13 refresh wiring · G7 update field-scope · C-UI-08 zero-importable feedback.

**P3 backlog (9) — listed, only the cheap ones folded above:** EXP-11 DTSTAMP-UTC (folded) ·
IMP-05 midnight-timed reclassification (documented limit) · IMP-14 floating-verbatim (folded into
§3) · IMP-5/G9 truncation refusal (folded) · G14 duplicate-UID count line (folded) · IMP-12
recurrence-skip surfacing (folded) · IMP-13 per-event TZID try/except (folded) · IMP-12 stale-
snapshot purge (covered by §7 re-resolve) · C-UI-15 preview row cap (folded). _Most P3s turned out
cheap enough to fold; none are deferred as real debt except the midnight-timed model limit._

## 11. Testing plan

**Core (headless, no extras):**
- round-trip property: `todos → ics → parse → reconcile` preserves `due`/`title`/`category`/all-day
  for timed (floating), all-day, and unicode/`;,\`-laden titles.
- escaping + 75-octet fold/unfold (incl. a multibyte title that straddles the 75-byte boundary).
- datetime: floating verbatim · `Z`→local · `TZID`→local · unresolvable TZID skip · VALUE=DATE.
- defensive parse: missing VCALENDAR (`is_calendar=False`) · unterminated VEVENT skip · malformed
  event skip-with-reason (incl. no-SUMMARY label) · unknown props ignored · RRULE first-occurrence
  + skip note.
- reconcile: new vs update · no-UID skip · duplicate-UID-in-file collapse · active-only match
  (done/deleted UID → create) · fixpoint (no-op re-import = 0 updates) · update field-scope leaves
  recurring/subtasks intact.
- cross-device fixpoint sim: two `TodoStore`s, export A → import B (creates, `ics_uid` set) →
  export B → import A (updates A in place, no dup) → re-import either (0 updates).
- size cap (bounded read rejects a >5 MB / oversized stream).

**UI (offscreen):** buttons present · empty-export warns + writes nothing · cancel writes/reads
nothing · export OSError shows error not success · import preview counts correct · zero-importable
shows info dialog (button not actionable) · confirm applies the plan + emits `wrote` · cancel
writes nothing · transactional rollback on a save failure leaves the store unchanged.

## 12. Defaults chosen (confirm at review)

- **Datetime: floating-local export** (not UTC, not TZID+VTIMEZONE) — the §3 correction. ← biggest one.
- `DTEND`: timed → +1h; all-day → next-day `VALUE=DATE`.
- Import size cap = **5 MB**; preview row cap ≈ 20/section.
- Export default filename `serenity-calendar-<today>.ics`.
- New module `core/ics.py`; new dialog `ui/ics_import_dialog.py`; buttons on the compact
  Calendar-tab toolbar (`ui/calendar_view.py`).
