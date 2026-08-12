# Meeting-Prep — Design Spec

_Date: 2026-08-12 · Project "B" (rides on the LLM queue, Infra "A") · Branch `wf/meeting-prep` (off `main` @ `a351ce9`)._
_Status: approved design (brainstormed 2026-08-12); source for the flow-harden + TDD plan._

## 1. Goal

For a meeting, assemble a **Vorbereitung** from the **previous occurrence's protocol** plus **topically-linked
notes** and **your own open todos**, and write it into **this occurrence's protocol note** — so you walk into
the meeting with one document that already knows what was left open, and then type your notes into that same
document, which becomes the source for the next prep.

Two triggers, both explicit: a **Prep button** on every meeting (one-off, on demand) and a **default-off
auto-prep toggle** set when the meeting is created (the series then preps itself ahead of time). Not every
meeting needs a prep — nothing is generated unless you pressed the button or armed the toggle.

Scope: the prep itself. The queue, the working indicator and the off-time submission seam already exist
(Infra A, `docs/superpowers/specs/2026-07-17-llm-queue-design.md`).

## 2. Decisions (locked in the 2026-08-12 brainstorm)

| # | Decision | Chosen |
|---|---|---|
| D1 | Trigger | Prep button on every meeting **+** default-off auto-prep toggle at creation |
| D2 | Artifact | The occurrence's **protocol note**, pre-filled — not a separate prep note |
| D3 | Content | Open Aufgaben · carry-over agenda / deferred Beschlüsse · related notes since the predecessor · your own open todos touching the meeting |
| D4 | Linkage | **Series key + topic fallback**, and the block names which one it used |
| D5 | GAP 1 | Folded in: parser `meeting` intent sets `category="meeting"` |
| D6 | Delivery | **Silent**; a "prepped" marker on the meeting row. No bubble, no toast |
| D7 | First occurrence | Create the note anyway with what is available + an honest "kein früheres Protokoll gefunden" |
| D8 | Re-prep | Regenerate the block **in place** between markers; never touch text you typed |
| D9 | Lead window | ~18h — evening before and morning of |
| D10 | Auto scope | Only meetings whose `prep_auto` toggle is on (default **off**) |
| D11 | Toggle surface | `QuickTodoDialog` **and** `CaptureBubble`, shown only once the title parses as a meeting |

Assumptions stated rather than asked: the prep is written in `settings.language` (like capture and voice), and
the auto path runs as a **HEAVY** break job so it inherits the AC-power guard.

## 3. Why the linkage needs a series key

`TodoStore._spawn_recurrence` (`todo_store.py:183`) builds a **brand-new `Todo` with a new id** and copies no
back-reference; `ics_uid` and `linked_note_ids` are deliberately dropped ("a new occurrence is a new event
identity"). So a recurring meeting has **no identity across occurrences** today, and "the previous occurrence's
protocol" is not derivable from the data.

Two optional fields on `Todo` (`models.py`), both defaulting to absent so existing `todos.json` loads unchanged:

- `series_id: Optional[str]` — set in `_spawn_recurrence` as `done_todo.series_id or done_todo.id`. The first
  occurrence's own id becomes the series identity; every later occurrence carries it.
- `prep_auto: bool = False` — the D1/D10 arming, cloned by `_spawn_recurrence` alongside `category`/`tags`.

When a protocol note is created for a meeting that has a `series_id`, the key is stamped on the note as a tag
(`serie-<series_id>`), which is what makes the chain findable from the note side.

## 4. Core module (`core/meeting_prep.py`, Qt-free, headless-testable)

```
find_predecessor(todo, notes, index=None) -> (Note | None, source)   # source: "series" | "topic" | None
extract_carryover(raw_md) -> Carryover                               # pure Markdown section parsing
gather(todo, notes, todos, index=None, now=...) -> PrepInput
render_prep(prep_input, lang) -> str                                 # deterministic Markdown, no model
llm_prompt(prep_input, lang) -> str                                  # the prompt for the queued job
splice(raw_md, block) -> str                                         # replace between the markers
due_for_auto_prep(todos, now, window_hours=18) -> list[Todo]         # pure eligibility
```

- **`find_predecessor`** — exact first: the most recent note tagged `serie-<series_id>` dated before this
  occurrence. Nothing? Fall back to topic: `semantic_search` (`search.py:112`) on the meeting's title + tags,
  restricted to notes tagged `Protokoll`/`meeting`, most recent before this occurrence. `source` is carried
  into the rendered block so a fuzzy hit is **visible** ("aus Protokoll 2026-08-07 - thematisch gefunden")
  rather than silently wrong.
- **`extract_carryover`** — parses the predecessor's `## Aufgaben`, `## Beschluesse`, `## Agenda` sections.

  **Exact section names matter.** `protocol_template()` (`modals.py:39-52`) writes `## Teilnehmer`,
  `## Agenda`, `## Notizen`, `## Beschluesse`, `## Aufgaben` — ASCII "Beschluesse", **no umlaut**, and **no
  trailing colon**. Matching must be tolerant anyway (accept `Beschlüsse` and a trailing colon too), because
  people edit these headings by hand, but the canonical names are the ASCII ones the template emits.

  **Openness rule (one rule, used by all three sections):** a Markdown list entry counts as **open** unless it
  is a ticked checkbox (`- [x]`) or struck through (`~~…~~`). Plain bullets with no checkbox are open — the
  template does not force checkboxes and people write plain bullets.

  So: still-open Aufgaben = open entries under `## Aufgaben`; carry-over agenda = open entries under
  `## Agenda`; deferred Beschluesse = entries under `## Beschluesse` containing a defer word
  (`vertagt`, `verschoben`, `deferred`, `postponed`, case-insensitive), whether open or not — a decision to
  postpone is a decision, so it is not caught by the openness rule.

  Malformed or missing sections return **empty**, never raise.
- **`gather`** — carry-over + `related_notes` (`search.py:142`) filtered to notes created after the
  predecessor's date + open todos whose tags/category/person overlap the meeting.
- **`render_prep`** — the deterministic block. This is what gets written first and what survives when no
  model is available.

## 5. The block and its markers

The prep occupies a marker-delimited region directly under the note's `# Protokoll - <date>` heading, above
the sections you fill in. Serenity-authored labels follow the template's house style (`modals.py:41` — single
hyphens, no emoji, ASCII headings); text carried over from your notes keeps its original spelling, umlauts
and all:

```markdown
# Protokoll - 2026-08-14

<!-- serenity:prep:start -->
## Vorbereitung
Offen aus Protokoll 2026-08-07 (Serie)
- Angebot an Müller schicken
Agenda-Uebertrag
- Punkt 3 war unerledigt
Verwandte Notizen
- Angebot Müller
- Budget Q4 Draft
Deine offenen Todos
- Angebot finalisieren (faellig 13.08.)
<!-- serenity:prep:end -->

## Teilnehmer
- 

## Agenda
- 

## Notizen
- 

## Beschluesse
- 

## Aufgaben
- 
```

`splice` replaces **only** what is between the markers. Everything you type lives outside them and is never
read, rewritten, or reordered. Markers present **is** the "already prepped" fact — there is no separate
fired-flag that could drift out of sync (D8, and the idempotence guarantee in §7).

## 6. Execution

Both triggers run the same two-step, mirroring the weekly-board digest (`weekly_board_view.py:220`):

1. **Deterministic write, immediately.** Ensure the occurrence's protocol note exists (create from
   `protocol_template()` and link it into `todo.linked_note_ids` if absent), then splice in `render_prep`'s
   output. This is synchronous, cheap, and model-free — the prep exists the moment it is asked for.
2. **LLM refinement, queued.** Submit an `LlmJob` (`core/llm_queue.py:45`) through `Shell._submit_llm_job`
   (`shell.py:1087`), label `Meeting-Prep: <title>` including the todo id so the queue's dedup stops double
   submits. On result, splice the tightened block in place of the deterministic one.

- **Button path:** submits immediately (pressing a button is explicit consent to spend the cycles).
- **Auto path:** a **HEAVY** `BreakJob` registered through `maintenance.build_jobs(..., submit=...)`
  (`maintenance.py:35`), so it inherits the AC guard and the 5-minute heavy-idle threshold
  (`breaktime.py:49`). It walks `due_for_auto_prep` and preps each eligible meeting that is not already
  prepped.

Eligible = `prep_auto` is on **and** `due` is within the next 18h **and** the note has no prep markers yet.

## 7. Failure, staleness, degrade

- **No `[llm]` / model missing / job fails** → the deterministic block stays. The feature never becomes
  unavailable, only less polished — the project's standing degrade pattern.
- **Stale result:** apply the LLM result only if the note still exists **and** both markers are still present.
  Note deleted, meeting deleted, or you removed the block → result dropped, silently.
- **Idempotence:** auto-prep cannot fire twice for one occurrence, because "already prepped" is derived from
  the markers in the note (§5).
- **Predecessor unreadable:** `extract_carryover` returns empty; you still get related notes, your own todos,
  and the honest "kein früheres Protokoll gefunden" line (D7).
- **No `[semantic]`:** `find_predecessor`'s topic fallback and `related_notes` degrade to the existing
  tag/keyword path (`search.py` is already semantic-or-fallback).

## 8. UI surface

- **Prep button** on the meeting row in `TodosView`, next to the existing protocol button that is already
  gated on `category == "meeting"` (`todos_view.py:433,461`).
- **Prepped marker** on the same row when the linked protocol note carries the markers.
- **Auto-prep toggle**, default off, in `QuickTodoDialog` (`modals.py:205`, also the calendar slot-create
  path) and `CaptureBubble` (`capture_bubble.py:80`), shown only once the typed title parses as a meeting.
  Meetings created from the bare capture bar get `prep_auto=False` and are armed later from the row.
- Per the standing UI rule, **every one of these controls ships with a hover explanation** — the toggle, the
  button, and the marker.

## 9. Parser change (GAP 1)

`parser.py` has a `meeting` intent from the keywords `termin`/`meeting` (`parser.py:35`), but `category` is
only ever set from an explicit `@category` token (`parser.py:131-143`, `250`). So a captured "Termin mit
Müller" never becomes `category="meeting"` and never gets the protocol affordance at all.

Change: when the intent is `meeting` and no explicit `@category` was given, set `category="meeting"`. An
explicit `@category` still wins. Existing todos are untouched; only new captures classify.

## 10. Testing

Pure core (headless, no Qt):

- `extract_carryover`: open vs. ticked Aufgaben, deferred Beschlüsse, carry-over agenda, missing sections,
  malformed input returns empty rather than raising.
- `find_predecessor`: series hit, topic fallback, nothing found, and that a series hit **wins** over a more
  recent topical match.
- `splice`: replaces between markers, preserves text outside them, and is a no-op-safe insert when the note
  has no markers yet.
- `render_prep`: deterministic output, and the source attribution ("Serie" vs "thematisch gefunden").
- `due_for_auto_prep`: inside/outside the 18h window, `prep_auto` off excluded, already-prepped excluded.

Integration / UI:

- `parser`: `meeting` intent sets the category; explicit `@category` still wins.
- `_spawn_recurrence`: clones `series_id` and `prep_auto`; first occurrence seeds `series_id` from its own id.
- Toggle appears only for meeting-parsing titles, in both creation surfaces; defaults to off.
- Prep button submits exactly one job; a second press while one is pending does not enqueue a duplicate.
- A result whose markers have vanished is dropped and does not rewrite the note.
- Every new control has a non-empty tooltip.

## 11. Non-goals

- No new interruption channel — no bubble, no toast (D6).
- No editing of the protocol body by the app beyond the marker region.
- No retroactive series-tagging of protocols already in the vault; those are reachable through the topic
  fallback only.
- No meeting-recording / transcription (that is the separate parked "Meeting Recap" idea).
