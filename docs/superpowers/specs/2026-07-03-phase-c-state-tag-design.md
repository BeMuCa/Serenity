# Phase C — `state_tag` + `context` on Notes & Todos + Two-Axis Filtering — Design Spec

_Date: 2026-07-03 · Branch: `wf/phase-c-state-tag` (off `wf/phase-b-context`) · Milestone: States & Contexts_
_Status: approved design + flow-hardened (34 candidates → 30 verified → 16 deduped requirements folded); source for the TDD plan._

## 1. Goal

Every new Note and Todo is stamped at creation with the **activity state** it was created under (`state_tag`, a stable registry key, `None` when idle) and the **global context** (`context`, always `business|private`). Two filter axes then act on the item surfaces: the **global context toggle** (Phase B) now also filters what is shown, and a **deselectable, auto-selected state chip** narrows Notes/Todos to the current activity. User decisions locked during brainstorm: both axes (faithful to the milestone brief) · `state_tag` stores the registry **key**, not the label · context is **always set** on new items (fresh vault, no legacy data, no migration) · derived items **inherit** their parent's stamp.

## 2. Dependencies & current state

- Phase A registry (`core/states.py`): `ActivityState{key,label,color,poses,category,context}`, `selector_rows`, `color_for_label`; registry user-editable later (Phase E).
- Phase B: `Settings.current_context` + `context()` (always `business|private`), `Shell.set_context/_sync_context` (`shell.py:814-839`) — currently syncs title-bar/tray/mascots ONLY.
- The running activity: `activity_store.running()` → `ActivityEntry|None`; `.category` is the **label** (e.g. `"Working"`); Idle = no span (`_on_activity` calls `stop()`); a running span **persists across restart** (`activity.json`).
- Serialization precedent: `ics_uid` (`models.py`, `tests/test_models.py:18-26`) — optional scalar, `.get()` on load, legacy round-trip test.
- The note SQLite index is a **write-only disposable cache** (no `SELECT` anywhere; positional 10-col INSERT; no schema-version mechanism). All list surfaces read in-memory objects.
- Only `Shell` holds both `settings` and `activity_store`.

## 3. Data model (`core/models.py`)

- `Note` and `Todo` each gain `state_tag: Optional[str] = None` and `context: Optional[str] = None`, following the `ics_uid` pattern: emitted in `to_frontmatter()`/`to_dict()`, read in `from_frontmatter()`/`from_dict()`.
- **Tolerant deserialize [R6]:** on load, a `context` value that is not exactly `"business"` or `"private"` (including non-strings) coerces to `None`; a non-string `state_tag` coerces to `None`. Any non-empty string `state_tag` is kept (registry-independent; may reference a later-deleted key).
- **NOT touched:** the SQLite index schema and `_index_note` (write-only cache; adding columns would break pre-existing caches — no schema-version mechanism exists until Phase I).

## 4. Stamp machinery

- New pure helper `states.key_for_label(states, label) -> Optional[str]`: first matching **activity** row in registry order (deterministic on duplicate labels **[R9]**); `None` for no match / Idle.
- `Shell` builds one closure `stamp() -> (state_tag, context)`: `state_tag = key_for_label(settings.states(), running().category)` if a span is running else `None`; `context = settings.context()`. Threaded like `settings` already is into `TodosView`, `QuickTodoDialog`, `QuickNoteDialog`, and `CalendarWeekPanel`.
- **Read-time semantics [R10]:** dialogs and the add-bar call `stamp()` at the moment of the store write (`_save`/`_add`), never at construction. The voice/NL capture path **snapshots** the stamp when the capture is parsed and `_pending` is set; `_commit_capture` applies that snapshot unchanged (cleared with `_pending`) — a mid-slot-fill activity switch or context flip never changes the committed stamp.
- `NoteStore.create()` gains optional `state_tag=None, context=None` passthrough params (stores stay Qt-free and never read settings/activity themselves).

## 5. Creation funnels — every path stamps [R11, R12]

| Funnel | Site | Stamp |
|---|---|---|
| Voice/NL capture (todo + note) | `shell._commit_capture` (~746/757) | snapshot taken at `_pending` set |
| QuickTodoDialog (incl. calendar slot-click) | `modals.py` ~204/209; opened from `calendar_week_panel.py` ~366 | `stamp()` at save; closure threaded via `_open_calendar_expanded` (`shell.py` ~585) |
| QuickNoteDialog | `modals.py` ~143 | `stamp()` at save |
| Todos add-bar | `todos_view._add` ~501 | `stamp()` at save |
| ICS import (create branch) | `calendar_view._apply_import` ~259 | `context` = threaded context provider, `state_tag=None`; the re-import **update** path (~255-257) never restamps |
| Recurrence clone | `todo_store._spawn_recurrence` ~183 | **inherits** parent todo's `state_tag`+`context` (test pins the clone field list — it already silently omits `ics_uid`/`linked_note_ids`, which stays as-is) |
| Prep-note from a todo | `todos_view.TodoCard._on_note_btn` ~411 | **inherits** the todo's stamp (passed explicitly to `create()`) |
| Pop-out recovery re-save | `note_editor_panel._save_as_new` ~281 | keeps the old note's stamp |
| `phase2_stubs` placeholder Notes (~335/389) | never persisted | never stamped |

A test asserts **no in-app creation path produces `context=None`**.

## 6. Filtering — the pure predicate + which surfaces

New pure core predicate (in `core/states.py` or a small `core/filtering.py`):

```python
def visible(item, context, state_key=None) -> bool:
    item_ctx = item.context if item.context in ("business", "private") else None   # [R6] belt+braces
    if item_ctx is not None and item_ctx != context: return False
    if state_key is not None and item.state_tag != state_key: return False        # pure equality only
    return True
```

`state_key=None` always means "state axis off", **never** "match items with `state_tag=None`" **[R2]**.

**Context axis applies to** (state axis only where noted):
- `NotesView` + `TodosView` lists (post-filter after Text/Meaning search / ranking; **both axes**).
- Calendar tab (`collect_events` input), week pop-out grid + its side list **[R13]** (context only).
- Dependency-graph tab: nodes filtered by context; edges to hidden nodes dropped (read-only viz) **[R13]**. With calendar+graph filtered, the `_open_calendar_todo` deep-link dead-end disappears by construction.
- Mini-window "UP NEXT" pick: `visible(t, context, None)` before `mini_todos` **[R13/mini]**.
- **AI surfaces [R16]:** related-chips (`NoteCard._ensure_related`), `ReadNoteDialog` chain, Ask-dialog retrieval, and the duplicates scan filter their **candidate note list** by context. `semantic.index(...)` keeps receiving the FULL `all_active` corpus (its `store.prune(keep_ids=…)` would otherwise delete the other context's embeddings and force re-embeds on every flip — `phase2_stubs.py:316`); `related_notes`/`semantic_search` already re-project onto the candidate list. The Ask warm-cache key includes the current context. Pattern: thread a second, context-filtered `candidates_provider` alongside the unfiltered index corpus.

**Deliberately context-agnostic (documented, not omitted):** Weekly Board (Phase D adds the business/private/both board toggle), Trash (stays fully reachable; rows gain a context suffix in the meta label when stamped **[R14]**), tag consolidation (tags only, no bodies), ranking order (computed on the full set; filter applied after).

**Sync fan-out:** `Shell._sync_context` additionally refreshes `notes_view`, `todos_view`, `calendar_view`, an open `CalendarWeekPanel` pop-out (mirroring `_on_calendar_wrote`), the mini window (`refresh_todo`), and re-evaluates the state chips.

## 7. The state chip (Notes + Todos)

Checkable `QPushButton#pill` (Text/Meaning pattern); Notes: after the search row; Todos: a new row above the list. Shows the running activity's **label + registry color**.

| Situation | Chip | State filter |
|---|---|---|
| Boot with a restored running span **[R1]** | visible + checked, label/color from registry — driven by one shell-level sync at construction (next to the `shell.py:373` chip restore) + from `_on_activity`; **never** by views subscribing to mascot signals | on |
| Activity start/switch **[R4]** | both chips re-check + re-label via the same shell sync | on |
| Manual uncheck **[R4]** | lasts for the current span only; per-view (the two views may diverge); session-only, never persisted | off |
| Idle / stop **[R2]** | hidden | off (`state_key=None`) |
| Running label unmappable (`key_for_label`→`None`) **[R2]** | hidden — visibility and stamping derive from the SAME `key_for_label` result | off |
| Context flip while a cross-context activity runs **[R7+R15, conflict resolved]** | **visible but unchecked** — the chip keeps telling the truth about the running span (R15), but stops force-filtering the new context's list by a foreign state (R7); user may re-check (cross-context stamps are legal: state=running key + context=new is an accepted pair); next activity start restores auto-check | off until re-checked |
| Context flip, running state's context ∈ {new, `any`} | unchanged | unchanged |

**Done-grace interplay [R3]:** `TodosView.refresh` always renders a card for any id in `_grace_timers` even when the post-filter would hide it (undo stays reachable); hiding via flip/chip never cancels the timer — completion still commits on expiry, with the mascot completion bubble suppressed when the todo's context differs from the current one.

## 8. Pop-out editor front-matter [R8]

`note_draft.validate()` rejects a `context` value outside `{business, private, null}` (`NoteDraftInvalid`, panel stays open) and a non-string non-null `state_tag`. `promote()` copies `state_tag`+`context` in its `fm_edited` merge (missing key → keep live value; explicit null → `None`) — a raw-YAML edit of either field persists exactly as an external-editor edit would.

## 9. Empty-state hints [R5]

When the post-filter hides ≥1 item that matched a non-empty Notes search, or hides ≥1 active todo while the state chip is checked, the view shows a count-only notice via the existing notice-label pattern ("N hidden by context/state filter") — never hidden titles, never during plain unfiltered browsing.

## 10. Non-goals

SQLite index columns (Phase I) · LLM routing changes · Weekly Board filtering + context colors (Phase D) · registry editor (Phase E) · chip-state persistence · re-stamping on edit (stamps are creation-time snapshots; only the pop-out fm editor can deliberately change them) · tidy-tags context filtering · backfill/migration (fresh vault).

## 11. Flow-harden fold (34 candidates → 26 workflow-confirmed + 3 inline-confirmed + 1 refuted; deduped to 16)

| # | Sev | Requirement (one line) |
|---|---|---|
| R1 | P2 | Chip derives from `running()` via one shell sync at construction + `_on_activity` (boot-restored span works) |
| R2 | P2 | Idle/unmappable ⇒ chip hidden, state axis inert (`state_key=None` = off, never "match None") |
| R3 | P2 | Grace-pending cards always render; hide-by-filter never cancels grace; cross-context bubble suppressed |
| R4 | P3 | Auto-select semantics: re-check on every start/switch; manual uncheck lasts one span; per-view |
| R5 | P3 | Count-only "N hidden by filter" notice when a filter empties matched results |
| R6 | P2 | Deserialize coerces invalid context/non-str state_tag → None; `visible()` treats invalid context as both; pure equality |
| R7 | P2 | Context flip re-evaluates chip: cross-context running state ⇒ visible+unchecked (conflict resolution, §7) |
| R8 | P2 | Pop-out fm edits of state_tag/context validate (reject bad context) + persist via `promote()` |
| R9 | P3 | `key_for_label` = first match in registry order (duplicate labels deterministic) |
| R10 | P2 | Stamp read at write-time (dialogs/add-bar); capture path snapshots at `_pending` set |
| R11 | P2 | Every in-app funnel stamps (incl. calendar slot dialog + ICS import context threading); no `context=None` from the app |
| R12 | P2 | Derived items inherit: recurrence clone, prep-note, recovery re-save (clone field list pinned by test) |
| R13 | P2 | Context axis on calendar tab + week pop-out + graph + mini pick; `_sync_context` fans refresh to all of them |
| R14 | P3 | Trash unfiltered; rows show context suffix when stamped |
| R15 | P3 | Flip never stops a running span; post-flip stamp = (running key, new context) is a legal pair |
| R16 | P2 | AI surfaces filter candidates by context (index stays full-corpus; Ask cache keyed by context); tidy-tags exempt |

Refuted (recorded): "todo typed while Idle vanishes on Enter" — unreachable; the only `stop()` path is the same-thread mascot signal.

## 12. Testing map

- **Models:** round-trip incl. legacy dict/fm without keys (copy the `ics_uid` test), invalid-value coercion [R6].
- **Pure core:** `key_for_label` (match, no-match, duplicates [R9]), `visible()` (axes on/off, invalid contexts `'work'`/`123`, non-str state_tag, `None` semantics [R2/R6]).
- **Stamping:** one test per funnel in §5 (incl. the no-`context=None` sweep, snapshot semantics [R10], inheritance [R12]).
- **Views (offscreen):** chip table in §7 row by row (boot-restore, switch, uncheck-span, idle, unmappable, flip cases), grace interplay [R3], hints [R5], context flip refreshes notes/todos/calendar/pop-out/mini [R13].
- **AI surfaces:** related/Ask/duplicates candidate filtering + full-corpus index preserved + cache key [R16].
- **Editor:** validate/promote for the two fields [R8]. Trash suffix [R14].
- Gate: full headless suite green (`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`).
