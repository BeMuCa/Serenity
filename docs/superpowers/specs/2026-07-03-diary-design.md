# Diary — Hybrid Day-Journal on the Weekly Board — Design Spec

_Date: 2026-07-03 · Slice 1 of 3 (Diary → Mood → Yearly review) · Builds after Phase C (needs its stamp machinery)_
_Status: approved design; source for the TDD plan. Slices 2/3 + the ML-correlation future idea are recorded in `notes/1_Planning.md`._

## 1. Goal

Track **what was done in which state**. Serenity already records the state timeline (`activity.json` spans) and — after Phase C — which state/context every note/todo was created under. The diary adds the missing narrative: a **hybrid** day-journal where an **auto-skeleton** (derived from existing data, never persisted) is woven together with the user's **manual lines**, shown **on the Weekly Board below the tracking stats**, with week navigation as the groundwork for the later yearly review.

User decisions locked: hybrid content · lines stored in an own store (`<vault>/diary.json`) · capture via BOTH a `diary:` capture-bar/voice intent AND a line-input in the Board's diary section · surface = Weekly Board (below tracking), NOT a new tab · slicing approved (mood + yearly deferred; ML correlation saved as idea).

## 2. Data model + store (`core/diary.py`, Qt-free)

- `DiaryLine{id: str (uuid4 hex), ts: datetime (naive local, like Todo.due), text: str, state_tag: Optional[str], context: Optional[str]}`.
- `DiaryStore(vault_dir)` over `<vault>/diary.json` (bare JSON list, same discipline as `TodoStore`): tolerant `reload()` (corrupt → `.corrupt-<ts>` backup + `[]`; non-dict rows skipped; `.get()` field reads), `save()` via `atomic_write_text`, `add(line)`, `edit(line_id, text)`, `delete(line_id)`.
- Lines are stamped at capture with Phase C's `stamp()` closure (`state_tag` = running activity's registry key or `None`; `context` = `settings.context()`), `ts = now`. **Editing a line never re-stamps** `ts`/`state_tag`/`context`.

## 3. `Todo.completed_at` (small model addition)

The skeleton needs "todos completed that day", but `Todo` has no completion timestamp (the Board's weekly count uses a proxy). Add `completed_at: Optional[datetime] = None`, stamped by `TodoStore.complete()` — i.e. at the **done-grace commit**, not at the tick — `None` for old/open todos (ics_uid-pattern round-trip + legacy test). If any un-complete path exists (verify at plan time), it clears the field. Recurrence clones spawn with `completed_at=None`.

## 4. Skeleton builder (pure, derived, never persisted)

`build_diary_week(log_entries, todos, notes, lines, anchor, now) -> list[DiaryDay]` (7 days, Monday start via `week_start_dt`; `now` closes the open span):

- `DiaryDay{date, spans: list[DiarySpan], untracked: list[DiaryItem]}`; `DiarySpan{category, start, end, items}`.
- Items woven by timestamp: non-trashed todos with `completed_at` that day, active (non-trashed) notes with `created` that day, diary lines with `ts` that day. An item lands in the span whose `[start, end)` covers its timestamp (open span: `end = now`); otherwise in the day's `untracked` bucket.
- Pure function over passed-in data — headless-tested; the view only renders it.

## 5. Capture paths

- **Parser intent (DE+EN, voice included):** prefix keywords route to a new capture kind `diary` — EN `diary:` / `journal:`, DE `tagebuch:` (exact list + colon/space handling per existing parser conventions at plan time). Deterministic only: the LLM capture-router never reclassifies a diary capture and is not consulted for one (v1). No slot-filling — a diary line has no required slots; empty text after the prefix = no-op with a mascot hint.
- **Commit:** `Shell._commit_capture` gains a `diary` branch → `DiaryStore.add` + mascot confirmation line. Stamp semantics follow Phase C [R10]: snapshot at `_pending` set for the capture path (trivially — diary has no slot-filling, so parse≈commit).
- **Board input:** a one-line input at the top of the diary section ("What did you do?") → `stamp()` at save + `DiaryStore.add` + section refresh.

## 6. Weekly Board rework (`ui/weekly_board_view.py`)

- **Week navigation:** `◀  <week label>  ▶  [Today]` header row; an anchor date on the view (default: current week). `build_board(log, now)` is already pure — pass the anchor. Friday auto-open is unchanged and anchors the current week. The **LLM digest runs only for the current week** (browsing past weeks uses the deterministic hints — no surprise model loads).
- **Diary section** below the hints card: one collapsible group per day (Mon–Sun of the anchored week), each rendering its `DiaryDay` — span headers (label, time range, registry color dot) with woven items beneath (✓ completed todo titles, + created note titles, ✎ diary lines), then the `untracked` bucket. Empty days collapse to a thin header.
- **Line editing:** hover edit (inline, todo-inline-editing precedent) + delete with a small confirm (irreversible; purge-confirm precedent).
- **Context handling:** the Board stays context-agnostic until Phase D (consistent with Phase C's documented exemption); diary lines/items whose `context` is set show a small context marker. Phase D's business/private/both board toggle will govern tracking and diary alike.

## 7. Non-goals (v1)

Mood tracking (slice 2, own brainstorm — mascot 1-tap ask) · yearly review (slice 3 — builds on this week-nav groundwork) · ML correlation of state × mood × diary metrics (**saved future idea**, needs months of data) · LLM routing/classification of diary text · diary in RAG/semantic search (lines are not notes; revisit later) · exporting a day to a vault note · editing a line's timestamp/stamp.

## 8. Ordering & dependency

Builds **after Phase C** (reuses `stamp()`, `key_for_label`, context conventions): roadmap order becomes **C → Diary → D(board context colors) → E…**, so Phase D's board toggle lands on top of the diary section.

## 9. Testing map

- **Store:** round-trip, legacy/corrupt tolerance + backup, add/edit/delete, atomicity path, edit-never-restamps.
- **Builder:** span bucketing incl. open span, untracked bucket, week boundaries (Mon start, items at 23:59/00:00), empty week, cross-week lines excluded.
- **`completed_at`:** stamped at grace-commit, `None` legacy round-trip, recurrence clone spawns unset.
- **Parser/router:** DE+EN prefixes route kind=`diary`; non-prefixed text unaffected; empty-after-prefix no-op; LLM router bypass.
- **Board (offscreen):** anchor math + nav buttons, digest-only-current-week, section renders a built week, input commits + refreshes, delete confirm, Friday auto-open anchors current week.
- Gate: full headless suite green.
