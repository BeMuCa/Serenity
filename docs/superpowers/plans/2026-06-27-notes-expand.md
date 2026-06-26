# Notes-expand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand a note into a large left-docked Serenity-themed pop-out editor (plain-text body + raw-YAML sub-editor + open-in-OS-editor), fail-safe per the hardened spec, on a reusable `ExpandedPanel` foundation.

**Architecture:** All draft/commit/recover/validate/external-change logic lives in a Qt-free `core/note_draft.py` (headless-tested — the bulk of the 28 P1/P2 guarantees). UI is two thin widgets: a generic `ExpandedPanel` (frameless left-docked window foundation) hosting a `NoteEditorPanel` that wires to `note_draft`. Shell owns single-instance + cross-surface refresh + lifecycle.

**Tech Stack:** Python 3.12, PySide6, PyYAML, stdlib (`hashlib`, `os`, `pathlib`). No new dependency.

**Spec:** `docs/superpowers/specs/2026-06-27-notes-expand-design.md` — task requirements cite its IDs (P1-n / P2-n / P3-n). The spec's §3.1 is the authoritative `note_draft` contract.

## Global Constraints

- Python 3.12 + PySide6; no new third-party dependency (PyYAML/hashlib/QDesktopServices already present).
- Every new `.py` starts with the project header block (Author: Berk / Created: 2026-06-27 / Purpose / Role / Functions|Classes). See CLAUDE.md.
- `core/` is Qt-free and must import no PySide6. UI logic stays out of `core/`.
- Tests run headless: `QT_QPA_PLATFORM=offscreen python -m pytest -q`. The whole suite (currently 799 pass / 5 skip) must stay green after every task.
- Reuse existing infra; do NOT re-invent: `core.paths.atomic_write_text`, `note_store.serialize`/`parse_markdown`/`Note.from_frontmatter`/`_parse_iso`, the `_guarded_set` mutate-after-success pattern, `platform_win.dock_right`/`is_windows`, `theme.COLORS`, the `QuickNoteDialog → _on_note_saved` refresh wiring, `QTimer(self); setSingleShot(True)` debounce idiom, `trash_view` `QMessageBox.question(... default Cancel)`.
- Decisions are CONTENT-keyed, never mtime (P1-2, P2-8, P2-11). `id` is immutable (P1-5). The durable `.md` write is the sole commit point; the index is disposable (P3-1).
- Surgical edits only; match surrounding style; no refactors of working code.

---

### Task 1: `note_draft` serialization primitives

**Files:**
- Create: `serenity/core/note_draft.py`
- Test: `tests/test_note_draft.py`

**Interfaces:**
- Consumes: `note_store.serialize`, `note_store.parse_markdown`.
- Produces:
  - `draft_path(md_path: str) -> str` → `md_path + ".draft"`
  - `build_draft_text(front_matter_text: str, body_text: str) -> str` — canonical `---\n{fm}\n---\n\n{body}\n`, fm sourced ONLY from `front_matter_text`, body ONLY from `body_text` (P1-6).
  - `content_hash(text: str) -> str` — `hashlib.blake2b(text.encode()).hexdigest()` (P2-8).
  - `_norm(md_text: str) -> str` — normalize an `.md` text for content comparison (parse + re-serialize, or strip trailing whitespace) so YAML key-order/whitespace can't produce a false diff.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_note_draft.py
from serenity.core import note_draft as nd

def test_draft_path_appends_draft():
    assert nd.draft_path("/v/n.md") == "/v/n.md.draft"

def test_build_draft_text_sources_each_pane_independently():
    # fm from front_matter_text, body from body_text — never crossed (P1-6)
    fm = "title: Meeting\ntags:\n- work"
    out = nd.build_draft_text(fm, "## Agenda\n- x")
    assert out.startswith("---\n")
    assert "title: Meeting" in out and "## Agenda" in out
    # round-trips through the store parser to both changes
    from serenity.core.note_store import parse_markdown
    got_fm, got_body = parse_markdown(out)
    assert got_fm["title"] == "Meeting" and "Agenda" in got_body

def test_content_hash_differs_on_change():
    assert nd.content_hash("a") != nd.content_hash("b")
    assert nd.content_hash("a") == nd.content_hash("a")
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_note_draft.py -q` → FAIL (module/func missing).
- [ ] **Step 3: Implement** the four helpers in `note_draft.py` (with the header block). `build_draft_text`: `fm = yaml.safe_load(front_matter_text) or {}` then emit via the same shape as `serialize` (or, simpler and format-identical: `f"---\n{front_matter_text.strip()}\n---\n\n{body_text.strip()}\n"` — keep the raw fm text so the validator, not this serializer, is the gate). `_norm`: `parse_markdown`-then-reserialize, fall back to `.strip()`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(note_draft): draft path + serialization + content hash`.

---

### Task 2: `note_draft.validate` — the strict commit gate

**Files:** Modify `serenity/core/note_draft.py`; Test `tests/test_note_draft.py`.

**Interfaces:**
- Produces: `class NoteDraftInvalid(Exception)`; `validate(front_matter_text: str, loaded_note) -> dict` — returns the parsed fm dict on success, raises `NoteDraftInvalid(msg)` otherwise. Rules (P1-1, P1-5, P2-6, P2-7, P2-17): YAMLError → reject; non-dict → reject; `id` absent or `!= loaded_note.id` → reject; `tags` present and not list-of-str → reject; `pinned`/`deleted` present and not bool → reject; `created`/`updated` present non-empty and `_parse_iso(v) is None` → reject; a dropped-but-previously-present `created` → restore `loaded_note.created`.

- [ ] **Step 1: Write failing tests** — one per rule, plus the happy path:

```python
import pytest
from serenity.core.note_draft import validate, NoteDraftInvalid
from serenity.core.models import Note

def _note(**kw):
    base = dict(id="abc123", title="T", tags=["work"], color="#fff", pinned=False)
    base.update(kw); return Note(**base)

def test_validate_accepts_good_frontmatter():
    n = _note()
    fm = validate("id: abc123\ntitle: T\ntags:\n- work\npinned: false", n)
    assert fm["id"] == "abc123"

@pytest.mark.parametrize("raw,msg", [
    ("id: abc123\ntitle: [unclosed", "YAML"),
    ("just a scalar", "mapping"),
    ("title: T", "id"),                      # id absent
    ("id: DIFFERENT\ntitle: T", "id"),       # id changed (P1-5)
    ("id: abc123\ntags: work", "tags"),      # scalar tags (P2-7)
    ("id: abc123\npinned: yes-ish-str", "pinned"),
    ("id: abc123\ncreated: not-a-date", "created"),
])
def test_validate_rejects(raw, msg):
    with pytest.raises(NoteDraftInvalid):
        validate(raw, _note())
```

(Confirm the `pinned: yes-ish-str`/type cases match how `yaml.safe_load` types them; adjust raw to force a non-bool, e.g. `pinned: "true"`.)

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `validate`** using `yaml.safe_load`, `isinstance` checks, and `note_store._parse_iso`. Do NOT route through `parse_markdown` (it silently coerces — defeats the gate, P1-1).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(note_draft): strict commit-time validator (id immutable, typed fields)`.

---

### Task 3: `write_draft` + `discard` + `recover`

**Files:** Modify `note_draft.py`; Test `tests/test_note_draft.py`.

**Interfaces:**
- Consumes: `core.paths.atomic_write_text`, `_norm`, `build_draft_text`.
- Produces:
  - `write_draft(md_path, front_matter_text, body_text) -> bool` — atomic-write the draft; returns `True`/`False`, never raises (P2-5).
  - `discard(md_path) -> None` — `unlink(missing_ok=True)`; real `OSError` propagates (P2-4).
  - `class RecoverResult` (e.g. dataclass: `status: "none"|"recoverable"`, `draft_text: str|None`, `disk_diverged: bool`); `recover(md_path) -> RecoverResult` — total, content-keyed (P1-2, P1-3, P2-1, P2-11): no draft → none; `.md` absent → discard orphan, none; draft `_norm` == md `_norm` → discard, none; else recoverable.

- [ ] **Step 1: Write failing tests** covering: write+read-back; discard removes draft; discard of missing is a no-op; recover none when no draft; recover discards an identical orphan and returns none; recover returns recoverable when draft differs; recover with `.md` absent discards draft and returns none (never recreates).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.** `write_draft` wraps `atomic_write_text` in `try/except OSError: return False`. `recover` reads both files (guard `FileNotFoundError`), compares via `_norm`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(note_draft): write/discard/recover (content-keyed, total)`.

---

### Task 4: `detect_external_change`

**Files:** Modify `note_draft.py`; Test `tests/test_note_draft.py`.

**Interfaces:**
- Produces: `detect_external_change(md_path, baseline_hash) -> str` ∈ `{"unchanged","changed","source_missing"}` — re-read `.md`, compare `content_hash` to `baseline_hash`; wrap stat/read in `try/except OSError → "source_missing"` (P2-8, P2-9). Never raises.

- [ ] **Step 1: Write failing tests:** unchanged when hash matches; changed when file content differs from baseline; `source_missing` when the path is deleted.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(note_draft): content-hash external-change detector`.

---

### Task 5: `promote` orchestration + `NoteStore.reload_note` + draft-aware `purge`

**Files:** Modify `note_draft.py`, `serenity/core/note_store.py`; Test `tests/test_note_draft.py`, `tests/test_note_store.py` (or the existing notes store test file).

**Interfaces:**
- Consumes: `NoteStore.get/update/create`, `validate`, `discard`, `parse_markdown`, `serialize`, `atomic_write_text`.
- Produces:
  - `class NoteSourceMissing(Exception)`, `class NoteWriteFailed(Exception)`.
  - `promote(store, note_id, front_matter_text, body_text, fm_edited: bool) -> Note` — spec §3.1 steps 1-6: validate → store re-get (None → `NoteSourceMissing`, P1-10) → field-merge (body always; if `fm_edited` apply edited keys, else carry `pinned`/`color`/`tags` from live; preserve `live.deleted`, P2-16) → corrupt-original `.corrupt-<ts>` backup (P1-7) → `store.update(live)` (only `atomic_write_text` OSError → `NoteWriteFailed`; index step non-fatal, P3-1) → `discard` the draft LAST (P2-1).
  - `NoteStore.reload_note(id) -> None` — re-read `.md` → refresh `_notes[id]` + index row; missing → drop both (P1-11).
  - `NoteStore.purge` — add `Path(n.path + ".draft").unlink(missing_ok=True)` beside the existing `.md` unlink (P1-3).

- [ ] **Step 1: Write failing tests:** promote on a purged id raises `NoteSourceMissing` and does NOT recreate the file; promote with `fm_edited=False` carries pin/color/tags from the live note even if the draft's fm is stale (P2-16); promote preserves `live.deleted`; promote deletes the draft only after a successful write; `reload_note` re-syncs after an external `.md` edit; `reload_note` drops a note whose `.md` vanished; `purge` removes the sibling `.draft`. Use real `tmp_path` stores.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** `promote` (gitnexus impact `promote`/`NoteStore.purge`/`update` upstream first — report blast radius), `reload_note`, and the one-line `purge` addition. The corrupt-backup uses a fixed-suffix timestamp passed in or `datetime.now()` (mirror the existing `.corrupt-<ts>` pattern).
- [ ] **Step 4: Run, verify pass; run full suite green.**
- [ ] **Step 5: Commit** — `feat(note_draft): promote orchestration + NoteStore reload_note/purge draft`.

---

### Task 6: `platform_win.dock_left_of`

**Files:** Modify `serenity/ui/platform_win.py`; Test `tests/test_ui_expanded.py` (new, offscreen).

**Interfaces:**
- Produces: `dock_left_of(panel, anchor, width: int | None = None) -> bool` — place `panel` flush LEFT of `anchor`, full height of the **anchor's current screen** (`anchor.screen()` / `QGuiApplication.screenAt(...)`, fall back to `primaryScreen`); clamp the left edge and reduce width to keep the header on-screen (P2-13). Mirrors `dock_right`'s structure + `try/except → False`.

- [ ] **Step 1: Write failing test** (offscreen): given a shell-like widget at a known geometry, `dock_left_of` sets the panel's `x() == anchor.x() - panel.width()` when room exists, and clamps `x() >= screen.left()` (width reduced) when it would go off-screen.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** mirroring `dock_right` (platform_win.py:51-66), anchored to the live screen with the left clamp.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(platform): dock_left_of (screen-aware, left-clamped)`.

---

### Task 7: `ExpandedPanel` foundation

**Files:** Create `serenity/ui/expanded_panel.py`; Test `tests/test_ui_expanded.py`.

**Interfaces:**
- Produces: `class ExpandedPanel(QWidget)` — frameless `Qt.Tool` themed window; `__init__(self, title, content: QWidget, anchor, parent=None)`; header row (title `QLabel` + close `QPushButton`); `closeRequested = Signal()`; `set_title(str)`; on show, `platform_win.dock_left_of(self, anchor)`. Close routing: X button and `keyPressEvent(Key_Escape)` both emit `closeRequested` (P2-12, the dirty check lives in the content widget's handler, see Task 8). Restore-focus on close guarded: `if anchor and anchor.isVisible(): anchor.activateWindow()` in `try/except RuntimeError` (P3-5).

- [ ] **Step 1: Write failing smoke tests** (offscreen): builds with a dummy content widget; docks left of an anchor (width clamp); Esc emits `closeRequested`; close button emits `closeRequested`; close with a torn-down anchor doesn't raise.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the widget (header block; `theme.COLORS`; frameless flags like the shell at shell.py:201-203; `keyPressEvent` for Esc — frameless widgets have no auto-Esc).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(ui): ExpandedPanel left-docked pop-out foundation`.

---

### Task 8: `NoteEditorPanel`

**Files:** Create `serenity/ui/note_editor_panel.py`; Test `tests/test_ui_expanded.py`.

**Interfaces:**
- Consumes: `core.note_draft.*`, `ExpandedPanel` (host), `NoteStore`.
- Produces: `class NoteEditorPanel(QWidget)` — body `QPlainTextEdit`, a toggled raw-YAML `QPlainTextEdit` (seeded from the loaded note's serialized fm on open, P1-6), header buttons Save / Front-matter / Open-in-OS, a dirty indicator, a child single-shot debounce `QTimer(self)` (P2-3), `committed = Signal(str)`, `note_id` attr.
- Behaviour wired to `note_draft`:
  - edits → restart debounce → `write_draft`; `write_draft` False → dirty indicator → warning state (P2-5).
  - `commit()` (Ctrl+S / close→Save): `self._timer.stop()` FIRST (P2-3) → `promote(...)` in `try/except (NoteDraftInvalid → inline error, keep open; NoteSourceMissing → offer save-as-new; NoteWriteFailed/OSError → keep draft+open+inline msg, P2-10)`; on success emit `committed(note_id)`, delete handled inside promote.
  - close handler (from `ExpandedPanel.closeRequested`): dirty → `QMessageBox` Save/Discard/Cancel (default Cancel, P2-12); plain close never deletes the draft; Discard → `note_draft.discard` (propagate real OSError → keep open, P2-4).
  - on open: seed fm editor; capture baseline hash; `recover()` → prompt only on `recoverable` (declining = discard, P2-2).
  - focus-in (`changeEvent`/`focusInEvent`): stop debounce; `detect_external_change(...)`; precedence on the live dirty flag (P2-14): not-dirty+changed → reload; dirty+changed → 3-way Keep-mine/Load-disk/Keep-both (Keep-both writes `<note>.conflict-<ts>.md`, P1-9); source_missing → inline Re-save/Discard (P2-9). After a reload from disk, refresh the baseline.
  - Open-in-OS: dirty → 3-way Save&open / Open-without-saving(keep draft) / Cancel (P1-8); capture `QDesktopServices.openUrl` bool BEFORE closing, only close on True, gate the off-Windows note on `is_windows()` (P3-3); after the OS-editor flow, `store.reload_note(id)` (P1-11).

- [ ] **Step 1: Write failing smoke tests** (offscreen, mock `QDesktopServices.openUrl`): builds for a stored note; typing flips dirty; `commit()` writes via store + emits `committed` + deletes draft; invalid YAML in the fm editor keeps the panel open with an error; close-while-dirty shows the prompt (monkeypatch `QMessageBox`); recover prompt fires when a differing draft exists; open-in-OS hand-off only closes when openUrl returns True; same-id state. Keep each test to one behaviour.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.** Keep ALL decisions delegated to `note_draft`; the panel only renders choices + wires signals.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(ui): NoteEditorPanel (draft/commit/recover/external-change wired)`.

---

### Task 9: `NoteCard` expand entry button

**Files:** Modify `serenity/ui/notes_view.py`; Test `tests/test_ui_notes.py` (existing) or `tests/test_ui_expanded.py`.

**Interfaces:**
- Produces: an expand (⤢) `QPushButton` on each `NoteCard`, emitting an `expand_requested = Signal(str)` (note id) — wired up to the shell in Task 10. The existing inline snippet↔full expand stays untouched.

- [ ] **Step 1: Write failing test:** a `NoteCard` exposes the ⤢ button; clicking it emits `expand_requested` with the note id.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — gitnexus impact `NoteCard` upstream first; add the button beside the existing view-raw/pin buttons, matching their style. Bubble the signal up through `NotesView`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(ui): NoteCard expand-to-pop-out button`.

---

### Task 10: Shell wiring — single-instance, refresh, lifecycle

**Files:** Modify `serenity/ui/shell.py`; Test `tests/test_ui_expanded.py`.

**Interfaces:**
- Consumes: `NotesView.expand_requested`, `ExpandedPanel`, `NoteEditorPanel`.
- Produces:
  - `Shell._open_expanded(note_id)` — SINGLE INSTANCE: if a panel is open for the same id → `raise_()/activateWindow()` and return (P3-7); if open for a different id and dirty → resolve first (route through its close handler); else build `ExpandedPanel(NoteEditorPanel(note, store), anchor=self)`, keep `self._expanded` ref.
  - connect `NoteEditorPanel.committed → notes_view.refresh()` (mirror `_on_note_saved`); in Text-search mode also `semantic.index(all_active)` before rebuild if a `SemanticIndex` is wired (P2-15, P3-6).
  - lifecycle: in `set_window_mode`, on leaving FULL hide `self._expanded`; on return to FULL re-anchor + show (P3-4); clear `self._expanded` on panel close; ensure the dock-close/`_quit` path tears the panel down.

- [ ] **Step 1: Write failing tests** (offscreen): `expand_requested` opens a panel; opening the same id twice reuses (one panel); committing in the panel refreshes the notes list; mode-switch to mini hides the panel and back to full re-shows it.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — gitnexus impact `set_window_mode`/`Shell.__init__` wiring upstream first; reuse the existing tab-refresh + `_on_note_saved` patterns.
- [ ] **Step 4: Run, verify pass; run the FULL suite green; `npx gitnexus analyze` then `gitnexus detect_changes` (expect low risk / only the new+touched symbols).**
- [ ] **Step 5: Commit** — `feat(ui): wire Notes-expand into the shell (single-instance + refresh + lifecycle)`.

---

## Self-Review

**Spec coverage:** P1-1/5/6/7/10 → Tasks 2,5; P1-2/3/11 → Tasks 3,5; P1-4/8/9 → Task 8; P2-1/2/4/11 → Tasks 3,8; P2-3/5/10/12/14 → Task 8; P2-6/7/17 → Task 2; P2-8/9 → Tasks 4,8; P2-13 → Task 6; P2-15/16 → Tasks 5,10; P2-16 → Task 5; P3-1 → Task 5; P3-2 → Task 8; P3-3 → Task 8; P3-4/5 → Tasks 7,10; P3-6 → Task 10; P3-7 → Task 10; P3-8 → tracked separately (no task). All P1/P2 mapped.

**Placeholder scan:** test bodies in Tasks 3-10 are described by behaviour list rather than full code — acceptable here because the spec §3.1 + §7 give the exact contracts and the assertions are enumerated; the implementer writes one assert per listed behaviour. Tasks 1-2 (the trickiest gate logic) carry full test code.

**Type consistency:** `promote(store, note_id, front_matter_text, body_text, fm_edited)`, `recover() -> RecoverResult`, `detect_external_change() -> str`, `committed/expand_requested = Signal(str)`, `dock_left_of(panel, anchor, width=None)` — used consistently across tasks.
