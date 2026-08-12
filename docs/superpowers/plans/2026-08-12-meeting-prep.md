# Meeting-Prep — TDD Plan

_Spec: `docs/superpowers/specs/2026-08-12-meeting-prep-design.md` · Branch `wf/meeting-prep`._
_Each task: failing test → implement → full suite green → commit._

| # | Task | Verify |
|---|---|---|
| 1 | `Todo.series_id` + `Todo.prep_auto` on the model, round-tripped through `to_dict`/`from_dict` | old dicts without the keys still load; new values survive a round trip |
| 2 | `_spawn_recurrence` seeds/carries `series_id` and clones `prep_auto` | first occurrence seeds from its own id; second occurrence keeps the same key |
| 3 | Parser: `meeting` intent sets `category="meeting"` unless `@category` given | explicit `@category` still wins; other intents unchanged |
| 4 | `core/meeting_prep.py`: markers + `splice` | replaces between markers, preserves text outside, inserts under the `# Protokoll` heading when absent |
| 5 | `extract_carryover` | open vs ticked vs struck entries; defer words; missing/malformed sections return empty |
| 6 | `find_predecessor` | series hit beats a newer topical match; topic fallback; strictly-earlier (N2); none |
| 7 | `gather` + `render_prep` | four content blocks; source attribution; generation date (N3); empty-predecessor line (D7) |
| 8 | `due_for_auto_prep` | inside/outside the 18h window; `prep_auto` off excluded; already-prepped excluded |
| 9 | `prep_todo` orchestration (deterministic write + note create/link), re-reading raw before splice (N1) | creates+links a protocol note when absent; splices into an existing one |
| 10 | UI: Prep button + prepped marker on meeting rows, with tooltips | button only for `category=="meeting"`; marker reflects markers in the linked note |
| 11 | UI: default-off auto-prep toggle in `QuickTodoDialog` + `CaptureBubble`, with tooltips | hidden until the title parses as a meeting; defaults off; persists to the todo |
| 12 | Shell wiring: submit the refine job, stale-result guard | one job per press; result dropped when the markers are gone |
| 13 | `maintenance`: HEAVY auto-prep break job | registered; walks `due_for_auto_prep`; no duplicate prep |

Suite baseline at branch start: **1538 passed / 5 skipped**.
