# Diary — Hybrid Day-Journal on the Weekly Board — Design Spec

_Date: 2026-07-03 · Slice 1 of 3 (Diary → Mood → Yearly review) · Builds after Phase C (needs its stamp machinery)_
_Status: approved design + flow-hardened 2026-07-10 (8 gaps folded, see §10); source for the TDD plan. Slices 2/3 + the ML-correlation future idea are recorded in `notes/1_Planning.md`._

## 1. Goal

Track **what was done in which state**. Serenity already records the state timeline (`activity.json` spans) and — after Phase C — which state/context every note/todo was created under. The diary adds the missing narrative: a **hybrid** day-journal where an **auto-skeleton** (derived from existing data, never persisted) is woven together with the user's **manual lines**, shown **on the Weekly Board below the tracking stats**, with week navigation as the groundwork for the later yearly review.

User decisions locked: hybrid content · lines stored in an own store (`<vault>/diary.json`) · capture via BOTH a `diary:` capture-bar/voice intent AND a line-input in the Board's diary section · surface = Weekly Board (below tracking), NOT a new tab · slicing approved (mood + yearly deferred; ML correlation saved as idea).

## 2. Data model + store (`core/diary.py`, Qt-free)

- `DiaryLine{id: str (uuid4 hex), ts: datetime (naive local, like Todo.due), text: str, state_tag: Optional[str], context: Optional[str]}`.
- `DiaryStore(vault_dir)` over `<vault>/diary.json` (bare JSON list, same discipline as `TodoStore`): tolerant `reload()` (corrupt → `.corrupt-<ts>` backup + `[]`; non-dict rows skipped; **rows whose required `ts` is missing/unparseable are skipped** — mirroring `ActivityStore`'s `if start is None: continue` (`activity_store.py:75-77`), because `_parse_iso` returns `None` rather than raising, so an unskipped bad-`ts` row would load as `ts=None`, violate the non-Optional model contract, and crash `build_diary_week` on every board open; `.get()` field reads), `save()` via `atomic_write_text`, `add(line)`, `edit(line_id, text)`, `delete(line_id)`. **[flow-harden P1-1]**
- Lines are stamped at capture with Phase C's `stamp()` closure (`state_tag` = running activity's registry key or `None`; `context` = `settings.context()`), `ts = now`. **Editing a line never re-stamps** `ts`/`state_tag`/`context`.

## 3. `Todo.completed_at` (small model addition)

The skeleton needs "todos completed that day", but `Todo` has no completion timestamp (the Board's weekly count uses a proxy). Add `completed_at: Optional[datetime] = None`, stamped by `TodoStore.complete()` — i.e. at the **done-grace commit**, not at the tick — `None` for old/open todos (ics_uid-pattern round-trip + legacy test). If any un-complete path exists (verify at plan time), it clears the field. Recurrence clones spawn with `completed_at=None`.

## 4. Skeleton builder (pure, derived, never persisted)

`build_diary_week(log_entries, todos, notes, lines, anchor, now) -> list[DiaryDay]` (7 days, Monday start via `week_start_dt`; `now` closes the open span):

- `DiaryDay{date, spans: list[DiarySpan], untracked: list[DiaryItem]}`; `DiarySpan{category, start, end, items}`.
- Items woven by timestamp: non-trashed todos with `completed_at` that day, active (non-trashed) notes with `created` that day, diary lines with `ts` that day. An item lands in the span whose `[start, end)` covers its timestamp (open span: `end = now`); otherwise in the day's `untracked` bucket.
- **Span→day rule (cross-midnight) [flow-harden P2-2]:** a span crossing `00:00` is split at the day boundary and clipped into each day it touches (day-1 gets `[start, 24:00)`, day-2 gets `[00:00, end)`), reusing `aggregate_seconds`' window-clip discipline (`activity.py:66-96`). Without this, a post-midnight item (e.g. a todo completed `00:30`, filed on day-2 by its own timestamp) finds no covering span on day-2 and drops to `untracked` — misreporting tracked time as untracked and inverting the slice's goal.
- Pure function over passed-in data — headless-tested; the view only renders it.

## 5. Capture paths

- **Parser intent (DE+EN, voice included):** prefix keywords route to a new capture kind `diary` — EN `diary:` / `journal:`, DE `tagebuch:` (exact list + colon/space handling per existing parser conventions at plan time). Deterministic only: the LLM capture-router never reclassifies a diary capture and is not consulted for one (v1). No slot-filling — a diary line has no required slots; empty text after the prefix = no-op with a mascot hint.
- **Commit:** `Shell._commit_capture` gains a `diary` branch → `DiaryStore.add` + mascot confirmation line **+ `board_view.refresh()`** (mirroring the todos/notes refreshes so an already-open Board diary section isn't stale until the next tab switch) **[flow-harden P3-1a]**. **`DiaryLine.text` = the prefix-stripped VERBATIM remainder** (surface `parse_capture`'s internal `rest`) — NOT `cap.title` (entity/date-stripped: "diary: met with Sarah about #budget today" → "met about") nor `cap.raw` (prefix-baked); for `kind=diary`, `_extract_entities` / `_clean_title` / `add_tags(cap.tags)` are **bypassed** so `#tags`/`@cat`/`with <Name>`/date-words stay in the prose and the tag registry stays clean **[flow-harden P2-3]**. The empty-after-prefix no-op keys off the stripped remainder being blank. Stamp semantics follow Phase C [R10]: snapshot at `_pending` set for the capture path (trivially — diary has no slot-filling, so parse≈commit).
- **Discoverability [flow-harden P3-4]:** add a `diary:`/`journal:`/`tagebuch:` line to `_CHEATSHEET` (`modals.py:259-267`, the mic-open overlay enumerating capture intents) — a new parser intent does not auto-update the hardcoded list.
- **Board input:** a one-line input at the top of the diary section ("What did you do?") → **`text.strip()`; blank = no-op** (this path bypasses `parse_capture`, so it needs its own empty guard, mirroring `todos_view.py:633-635`, else a stray Enter persists a ghost blank line) **[flow-harden P3-2]** → `stamp()` at save + `DiaryStore.add` + section refresh.

## 6. Weekly Board rework (`ui/weekly_board_view.py`)

- **Week navigation:** `◀  <week label>  ▶  [Today]` header row; an anchor date on the view (default: current week). **Extend `build_board` to take the anchor and BOUND the selected week to `[week_start_dt(anchor), week_start_dt(anchor)+7d)` [flow-harden P2-1]** — pass a real `until` into `aggregate_seconds` (NOT `until=None`, which sums every *later* week's seconds into a past view: a 5 h week can render as 40 h) and apply the SAME `[start, until)` bound to the completed-todo count, switching it from `updated>=start` to **`completed_at` within the window** (so neither later weeks nor edited-but-long-done todos leak in). Friday auto-open is unchanged and anchors the current week. The **LLM digest runs only for the current week** (browsing past weeks uses the deterministic hints — no surprise model loads).
- **Diary section** below the hints card: one collapsible group per day (Mon–Sun of the anchored week), each rendering its `DiaryDay` — span headers (label, time range, registry color dot) with woven items beneath (✓ completed todo titles, + created note titles, ✎ diary lines), then the `untracked` bucket. Empty days collapse to a thin header.
- **Line editing:** hover edit (inline, todo-inline-editing precedent) + delete with a small confirm (irreversible; purge-confirm precedent). **`refresh()` is an unconditional teardown (`weekly_board_view.py:126-131`) — route auto-open/uncorrelated board refreshes through a `safe_refresh`-style defer guard (port `todos_view.py:617-630`) that skips teardown while an inline diary-line editor is focused, so a concurrent diary commit or Friday auto-open doesn't destroy an open edit and drop the typed text [flow-harden P3-1b].**
- **Context handling:** the Board stays context-agnostic until Phase D (consistent with Phase C's documented exemption — cross-context diary text on the Board is BY DESIGN, not a leak; flow-harden confirmed this, refuting all 3 privacy candidates on the basis that `phase-c-spec:62-67` enumerates the context-axis surfaces and the Board is not among them). A small context marker shows only on **cross-context** lines/items (`is_cross_context`, `ranking.py:82-88` — the item's `context` differs from the *current* one), **NOT** on every line whose `context` is merely set: `settings.context()` never returns `None`, so "context is set" would mark 100 % of lines for the default single-context user **[flow-harden P3-3]**. Phase D's business/private/both board toggle will govern tracking and diary alike.

## 7. Non-goals (v1)

Mood tracking (slice 2, own brainstorm — mascot 1-tap ask) · yearly review (slice 3 — builds on this week-nav groundwork) · ML correlation of state × mood × diary metrics (**saved future idea**, needs months of data) · LLM routing/classification of diary text · diary in RAG/semantic search (lines are not notes; revisit later) · exporting a day to a vault note · editing a line's timestamp/stamp.

## 8. Ordering & dependency

Builds **after Phase C** (reuses `stamp()`, `key_for_label`, context conventions): roadmap order becomes **C → Diary → D(board context colors) → E…**, so Phase D's board toggle lands on top of the diary section.

## 9. Testing map

- **Store:** round-trip, legacy/corrupt tolerance + backup, add/edit/delete, atomicity path, edit-never-restamps; **poison row (missing/garbage `ts`) is dropped on reload — never loaded as `ts=None` [P1-1].**
- **Builder:** span bucketing incl. open span, untracked bucket, week boundaries (Mon start, items at 23:59/00:00), empty week, cross-week lines excluded; **cross-midnight span split — a post-midnight item (00:30) lands in a clipped span on the later day, not `untracked` [P2-2].**
- **`completed_at`:** stamped at grace-commit, `None` legacy round-trip, recurrence clone spawns unset; **cleared on `reopen()`/`restore()`.**
- **Parser/router:** DE+EN prefixes route kind=`diary`; non-prefixed text unaffected; empty-after-prefix no-op; LLM router bypass; **diary prose with `#tags`/`@cat`/`with <Name>`/date-words stored VERBATIM (entities preserved) and adds nothing to the tag registry [P2-3].**
- **Board (offscreen):** anchor math + nav buttons, digest-only-current-week, section renders a built week, input commits + refreshes, delete confirm, Friday auto-open anchors current week; **past-week view over both stats bounded — later weeks excluded from tracked seconds AND completed count [P2-1]; blank board input is a no-op (no ghost line) [P3-2]; context marker shows only on cross-context lines [P3-3]; capture commit refreshes an open board [P3-1a] and an in-flight inline edit survives a concurrent refresh [P3-1b].**
- Gate: full headless suite green.

## 10. Flow-harden amendments (2026-07-10)

Pre-code flow-harden pass (Workflow: 9 lenses → 35 candidates → adversarial verify → **10 confirmed → 8 deduped**; method `notes/5_Interaction_Flows.md` → "Area: diary (slice 1)"). All 8 folded inline above (tagged `[flow-harden …]`):

- **P1-1** — bad-`ts` row must be skipped in `DiaryStore.reload` (else it loads as `ts=None` and crashes the whole board on every open, non-self-healing). → §2.
- **P2-1** — anchored past-week stats need an upper bound (`until=week_start_dt(anchor)+7d`) on both tracked seconds and the completed count (switch to `completed_at`). → §6.
- **P2-2** — cross-midnight spans split+clip per day so post-midnight items aren't misfiled to `untracked`. → §4.
- **P2-3** — diary `.text` = prefix-stripped VERBATIM remainder; bypass entity/date/tag handling for `kind=diary`. → §5.
- **P3-1** — diary commit refreshes an open board (a) + a `safe_refresh` defer guard protects an in-flight inline edit (b). → §5/§6.
- **P3-2** — blank board input is a no-op (this path skips `parse_capture`'s guard). → §5.
- **P3-3** — context marker only when cross-context (`is_cross_context`), not "context is set". → §6.
- **P3-4** — add the diary verbs to `_CHEATSHEET`. → §5.

Refuted (sound, NOT folded): 3 privacy candidates (Board is a documented Phase-C context exemption — cross-context text on the board is by design); `note.created=None` crash (NoteStore backfills `created`); `restore()` erases entry (spec §3 already clears `completed_at`); 23:59 next-day filing (deliberate grace-commit, already tested); corrupt→empty invisible loss + `_backup_corrupt` overwrite (backup + `atomic_write_text` re-raise protect it).
