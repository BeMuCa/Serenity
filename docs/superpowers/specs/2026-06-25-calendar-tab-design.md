# Calendar tab — design spec

_Date: 2026-06-25 · Branch: `wf/ship-wave` · Supersedes the `Note.created` part of the Calendar
note in `notes/1_Planning.md` (notes are dropped; see Scope)._

## Goal

A new **Calendar** tab in the shell that shows **todos with a `due` date** as deadline events,
laid out on a 7-column (Mon–Sun) calendar grid sized for the 348px dock. Read-only: it surfaces
existing todos, it does not create or edit them. No new data model.

## Scope (locked)

- **Events = todos with a `due` date only.** Not deleted. A calendar is a deadline view; notes are
  dated by *creation*, not a deadline, so notes are **out** (this overrides the planning-doc line
  about `Note.created`).
- **Read-only.** No event creation/editing in this tab.
- **No new model / no migration.** `Todo.due` and `Todo.category` already exist.
- Recurring todos appear **only at their current `due`** (no future-occurrence expansion).

## Interaction model (from the user)

### Week view (default)
- A single 7-column row (Mon–Sun) for the focused week. Each day cell shows its date number and a
  marker (dot / small count) when it has events; **today** is highlighted; days with a `meeting`
  todo get the accent color.
- **Below the grid: a list of all that week's events**, sorted by time (timed first by `HH:MM`,
  then untimed). Each row shows the title, optional `HH:MM`, and a meeting accent.
- **Click a day cell** → the list filters to just that day. **Click the selected day again** →
  back to the full week.

### Month view
- A **"Month" toggle button extends** the same 7-column grid downward into the focused month
  (multiple Mon–Sun week-rows; leading/trailing padding days from adjacent months are shown but
  flagged out-of-period and de-emphasized). Day cells carry the same event markers.
- **Click any week-row** → collapse back to Week view focused on that week.

### Navigation (shared)
- **‹ / ›** step the focus: prev/next **week** in week view, prev/next **month** in month view.
- **Today** button re-centers the focus on the current week/month.

### Toggles
- **"Show done"** toggle (default **off**) — includes completed todos (rendered struck-through)
  so the calendar isn't overcrowded by default.

## Architecture

Mirrors the `weekly_board` split: **pure logic in `core/`, the Qt view only renders.**

### `serenity/core/calview.py` — pure, framework-free, headless-tested
> Named `calview`, not `calendar`, on purpose: it uses the stdlib `calendar` module
> (`Calendar(firstweekday=0).monthdatescalendar`) for the month grid, so it must not shadow it.

```python
@dataclass
class CalEvent:
    when: datetime          # the todo's due
    title: str
    category: str | None    # "meeting" -> accent; else None/other
    done: bool
    has_time: bool          # show HH:MM only when the due carries a time
    todo_id: str            # for click-through

@dataclass
class DayCell:
    day: date
    in_period: bool         # False for month-grid padding days
    is_today: bool
    events: list[CalEvent]  # sorted: timed-by-HH:MM first, then untimed

@dataclass
class CalGrid:
    weeks: list[list[DayCell]]   # each inner list is exactly 7 DayCells (Mon..Sun)
    label: str                   # "Jun 22 - 28" (week) | "June 2026" (month)
    mode: str                    # "week" | "month"

def collect_events(todos, now=None, show_done=False) -> list[CalEvent]
def build_week(events, anchor, now=None) -> CalGrid     # the Mon..Sun week containing anchor
def build_month(events, anchor, now=None) -> CalGrid    # the weeks of anchor's month
```

- `collect_events`: keep todos where `due is not None and not deleted`; drop `done` unless
  `show_done`; derive `has_time` (a midnight-exact due with no time component reads as all-day —
  reuse the same time-presence convention the rest of the app uses, see note below).
- `build_week` / `build_month`: bucket events into day cells by date; mark `is_today`; for month,
  flag padding days `in_period=False`. Pure functions of `(events, anchor, now)`.

> **has_time convention:** the parser already distinguishes timed vs all-day captures
> (`Capture.has_time`). `Todo` itself only stores `due: datetime`, so the implementation will pick
> the simplest correct rule (e.g. treat `due.time() == 00:00` as all-day) and unit-test it; if a
> cleaner existing signal is found during implementation, use that instead.

### `serenity/ui/calendar_view.py` — renders only
- `CalendarView(todo_store, parent=None)` — a `QWidget` with `refresh()` (rebuilds from
  `todo_store.all()`), matching the `WeeklyBoardView` pattern.
- Header row: `‹  <label>  ›`, a **Month/Week** toggle, a **Today** button, and the **Show done**
  toggle.
- Grid: a `QGridLayout` of clickable day-cell widgets (1 row in week mode, N rows in month mode).
- Event list: a scroll area below (week mode), filtered by the selected day.
- Internal state: `_anchor: date`, `_mode`, `_selected_day`, `_show_done`. Each interaction
  updates state then calls `refresh()`.
- House style: single-hyphen copy, no emoji; `objectName("card")` / `objectName("sectLabel")`;
  colors from `theme.COLORS`.

### `serenity/ui/shell.py` — wiring (LOW risk, additive — impact-checked)
- Add `("calendar", "Calendar")` to the tab-button loop (`shell.py:290`). If the label overflows
  the 5-tab + trash-icon row at 348px, fall back to `"Cal"` or a calendar icon tab (decide by
  eye at build time).
- Construct `self.calendar_view = CalendarView(self.todo_store)` and add it to the stack +
  `_view_index` (`shell.py:319`).
- In `switch_tab`, add `elif key == "calendar": self.calendar_view.refresh()`.
- **Impact analysis (gitnexus, upstream):** `switch_tab` → LOW (4 in-module callers); `_build_ui`
  → LOW (only `__init__`). Adding a tab is additive; nothing existing breaks.

### Click-through (small, retained from default #3)
- Clicking an event row switches to the **Todos** tab via a signal to the shell. If `TodosView`
  exposes a way to focus/scroll-to a specific todo, use it; otherwise just switch tabs. Kept
  deliberately minimal — it is the only non-display interaction.

## Error / edge handling

- Empty store, or no dated todos → an empty grid + a "No deadlines this week" placeholder.
- A week that straddles a month boundary (week view) renders the real dates regardless of month.
- Month padding days render de-emphasized and are not clickable as "events".
- All pure helpers are deterministic in `now` (injected) so tests don't depend on the wall clock.

## Testing (headless, `QT_QPA_PLATFORM=offscreen`)

**Core (`tests/test_calview.py`) — the bulk:**
- `collect_events`: includes todos with `due`; excludes deleted; excludes `done` unless
  `show_done`; `meeting` category flagged; `has_time` true/false; todos without `due` excluded.
- `build_week`: Mon–Sun bucketing; correct week for a mid-week anchor; events land on the right
  day; today flagged; intra-day sort (timed before untimed); label format.
- `build_month`: correct set of weeks incl. leading/trailing padding flagged `in_period=False`;
  events placed; month label; a month whose first week has padding.
- Edges: empty events; anchor on a week boundary; week straddling a month boundary.

**View (`tests/test_ui_*.py`) — light, matching existing UI tests:**
- `CalendarView` instantiates and `refresh()` runs offscreen with an empty and a populated store;
  toggling Month/Week and clicking a day don't raise.

**Whole suite stays green** (currently 770 passing, 5 skipped).

## Out of scope (explicitly)

Event creation/editing, notes on the calendar, recurring-occurrence expansion, drag to
reschedule, multi-day/spanning events, time-grid (hour rows), iCal import/export.
