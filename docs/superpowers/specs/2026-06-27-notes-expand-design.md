# Notes-expand — design spec (hardened)

_Status: APPROVED design + flow-hardening folded in. Date: 2026-06-27._
_Brainstorm decisions + a 5-slice flow-hardening pass (35 confirmed gaps: 11 P1, 17 P2, 7 P3)._
_Companion future feature (separate spec): Calendar-expand, which reuses the `ExpandedPanel` foundation._

---

## 1. Summary & scope

Add the ability to **expand a note into a large, Serenity-themed pop-out window** docked flush-LEFT
of the right-edge dock, full screen height — a plain-text editor for the note, with a separate
button to view/edit the raw YAML front-matter, and a button to hand the file off to the OS editor.

This feature also builds the **shared `ExpandedPanel` foundation** (frameless themed left-docked
window) that the future Calendar-expand will reuse.

**In scope:** the `ExpandedPanel` foundation; the `NoteEditorPanel`; a Qt-free
`core/note_draft.py` holding all draft/commit/recover/validate/external-change logic; the entry
button on each `NoteCard`; shell wiring (single-instance, cross-surface refresh, lifecycle);
`platform_win.dock_left_of`; small `NoteStore` additions (`reload_note`, draft-aware `purge`).

**Out of scope (explicitly):** Calendar-expand and ICS (separate specs); live Markdown
rendering/preview (plain-text only, per the brainstorm); multi-pane diff/merge UI (we surface a
3-way *choice*, never an inline merge engine); any new optional extra/dependency (`yaml`,
`hashlib`, `QDesktopServices` are already available).

---

## 2. Locked brainstorm decisions

1. **Window layout:** left-docked large panel — flush LEFT of the dock, full screen height,
   ~65% width clamped; dock stays on the right.
2. **Save model:** HYBRID — continuous debounced `.draft` sidecar + explicit commit
   (Ctrl+S / close→Save); crash-recovery offer; discard leaves `.md` untouched.
3. **Edit target:** the **body** in the main editor; a **separate "Front-matter" button** reveals
   an editable raw-YAML sub-editor. The draft captures the *whole* note (front-matter + body).
4. **External editor:** **hand-off** — "Open in OS editor" commits/closes ours and lets the OS
   editor own the file; we also detect outside-Serenity edits and reload.
5. **Editing style:** plain text (`QPlainTextEdit`), no live Markdown render.

---

## 3. Architecture

Mirrors the codebase's `calview`/`calendar_view` split: **all fail-safe logic lives in Qt-free
`core/`, headless-tested; the panel only renders + wires.**

- `serenity/core/note_draft.py` *(new, Qt-free, the heart)* — draft path, draft serialization,
  write/recover/discard, the strict commit-time validator, the content-hash external-change
  detector, and the commit/promote orchestration (store-state guard, field-merge, corrupt-backup).
- `serenity/ui/expanded_panel.py` *(new)* — `ExpandedPanel`: frameless Serenity-themed
  left-docked window foundation (header: title + close; Esc/X close handler; restore-focus). The
  reusable shell for Notes now and Calendar later.
- `serenity/ui/note_editor_panel.py` *(new)* — `NoteEditorPanel`: the note body editor + YAML
  sub-editor + buttons (Save / Front-matter / Open-in-OS), debounce timer, dirty indicator,
  focus-in handler, `committed = Signal(str)`. Hosted inside an `ExpandedPanel`.
- `serenity/ui/platform_win.py` *(edit)* — add `dock_left_of(panel, anchor)`.
- `serenity/core/note_store.py` *(edit)* — add `reload_note(id)`; `purge()` also unlinks the
  sibling `.draft`.
- `serenity/ui/notes_view.py` *(edit)* — add the expand (⤢) button on each `NoteCard`.
- `serenity/ui/shell.py` *(edit)* — `open_expanded(note)` (single-instance), connect
  `committed → notes_view.refresh()`, panel teardown on mode-switch / dock-close / quit.

### 3.1 `core/note_draft.py` — contract (Qt-free)

All functions are pure/file-level and unit-testable headless. Typed errors:
`NoteDraftInvalid` (bad/invalid front-matter), `NoteSourceMissing` (`.md` gone), `NoteWriteFailed`
(durable write raised). The panel catches these and renders the outcome.

- `draft_path(md_path) -> str` → `md_path + ".draft"`.
- `build_draft_text(front_matter_text, body_text) -> str` — **single-sourced** serialization:
  combine the *live* FM text and the *live* body text into the canonical
  `---\n{fm}\n---\n\n{body}\n` shape (same format as `note_store.serialize`). Never source one half
  from the loaded `Note` and the other from a widget. *(P1-6)*
- `content_hash(text) -> str` — cheap digest (e.g. `blake2b`) of the whole `.md` text. *(P2-8)*
- `write_draft(md_path, front_matter_text, body_text) -> Result` — atomic write
  (`atomic_write_text`) of `build_draft_text(...)` to `draft_path`. **Returns a success/failure
  result; does not raise** so the panel's timer slot can never throw into the event loop. *(P2-5)*
- `validate(front_matter_text, loaded_note) -> dict` — the **strict gate**, stricter than
  `parse_markdown`'s silent coercion. Raises `NoteDraftInvalid` on any of: *(P1-1, P1-5, P2-6, P2-7, P2-17)*
  - `yaml.safe_load` raises `YAMLError`;
  - the loaded value is not a `dict`;
  - `id` absent or `!= loaded_note.id` (**id is immutable**);
  - `tags` present and not a list of `str`;
  - `pinned`/`deleted` present and not `bool`;
  - `created`/`updated` present, non-empty, and `_parse_iso(v) is None`.
  On a dropped-but-previously-present `created`, restore the loaded note's value rather than letting
  it commit absent.
- `recover(md_path) -> RecoverResult` — **total** open-time decision, content-keyed, never mtime: *(P1-2, P1-3, P2-1, P2-11)*
  - no `.draft` → `none`;
  - `.draft` exists but `.md` **absent** (purged/deleted) → discard the orphan draft, return
    `none` (never recreate the note, never raise);
  - `.draft` content == `.md` content (normalized via `serialize`/`parse_markdown`) → silent
    discard, return `none` (crash-after-commit orphan);
  - else → `recoverable` (carry the draft text + whether `.md` also diverged from the load
    baseline, so the prompt can name both facts).
- `detect_external_change(md_path, baseline_hash) -> {unchanged|changed|source_missing}` —
  re-read `.md`, compare `content_hash` to the baseline captured at load; wrap stat/read in
  `try/except OSError` → `source_missing` (never raise). mtime/size may be used only as a cheap
  pre-filter, never as the deciding signal. *(P2-8, P2-9)*
- `discard(md_path)` — unlink `draft_path` with `missing_ok=True`; **a real `OSError` propagates**
  (lock/permission) so the caller never reports a false "discarded". *(P2-4)*
- `promote(store, note_id, front_matter_text, body_text, fm_edited) -> Note` — the commit
  orchestration:
  1. `validate(front_matter_text, loaded_note)` → `fm` (raises `NoteDraftInvalid`).
  2. **Store-state guard:** `live = store.get(note_id)`. If `None` → raise `NoteSourceMissing`
     (purged under us); the panel offers "save as a new note" (`create()` with a fresh id). *(P1-10)*
  3. **Field-merge:** start from `live`; set `live.body = body_text`. If `fm_edited` apply only the
     keys the user actually edited; if the FM sub-editor was **never opened**, carry
     `pinned`/`color`/`tags` from `live` untouched (panel owns body, store owns metadata). Preserve
     `live.deleted` (don't silently un-trash). *(P1-10, P2-16)*
  4. **Corrupt-original backup:** before overwrite, re-read the on-disk `.md`; if it *has* a
     front-matter fence but `parse_markdown` yields no usable `id` and the note about to be written
     carries a different id → `os.rename(.md, .md.corrupt-<ts>)` first (preserve original bytes). *(P1-7)*
  5. **Durable write is the sole commit point:** `store.update(live)` (atomic `.md` then index).
     The index/`db.commit` step is non-fatal (disposable cache, self-heals) — wrap in
     `try/except` log-and-continue. Only an `atomic_write_text` `OSError` → raise `NoteWriteFailed`
     and keep the draft. *(P3-1)*
  6. **Delete the draft LAST** (after a successful durable write). *(P2-1)*

`NoteStore` additions: `reload_note(id)` re-reads the `.md` from disk → refresh `_notes[id]` + its
index row (or drop both if the file is gone), restoring "the `.md` is the source of truth" after an
OS-editor edit *(P1-11)*; `purge()` also `unlink(missing_ok=True)` the sibling `.draft` *(P1-3)*.

---

## 4. Data flow

`NoteCard ⤢` → `shell.open_expanded(note)` → single-instance `ExpandedPanel(NoteEditorPanel(note,
store))`. On open: seed the FM sub-editor buffer from the loaded note's serialized front-matter;
capture the load baseline hash; run `recover()` and prompt only on a real divergence. Edits →
debounced `write_draft`. Commit → `promote()` → `committed(note_id)` → `shell` →
`notes_view.refresh()`. Close → resolve (Save/Discard/Cancel) → draft cleanup → restore focus to
the dock.

---

## 5. Fail-safe requirements (folded from the hardening pass)

Each is a MUST unless marked. IDs trace to the hardening output. Many share a fix (content-keying,
the strict validator, the store re-get) — implement the shared mechanism once.

### 5.1 P1 — data-loss / irreversible (all MUST)
- **P1-1** `validate()` rejects invalid/non-dict YAML on commit; keep draft, `.md` untouched.
- **P1-2** Recover vs external-change resolved by **content**, not mtime; when both diverge the
  prompt names both and defaults to keeping the on-disk `.md`. Flush/stop the debounce on commit
  and close.
- **P1-3** `recover()` total for the `.md`-absent branch (discard orphan, no resurrect); `purge()`
  unlinks the sibling `.draft`.
- **P1-4** Focus-in external change with a live draft: content-hash compare → 3 outcomes; the
  both-changed case offers a choice (default non-destructive). The destructive "load disk" branch
  renames the draft to `.draft-conflict-<ts>` (reversible) rather than unlinking it.
- **P1-5** `id` is immutable at commit (`validate` rejects a changed/duplicate id) — structurally
  forbids both duplicate-id annihilation and orphaning.
- **P1-6** The draft captures **both** panes via `build_draft_text(fm_text, body_text)`; both the
  debounce and commit paths call it; FM sub-editor seeded from the loaded note on open. Headless
  test asserts a draft with *both* an FM change and a body change round-trips to both.
- **P1-7** Corrupt-original-on-load: at commit, `.corrupt-<ts>` backup before overwriting a file
  whose front-matter never parsed (may hold the real id).
- **P1-8** "Open in OS editor" with unsaved edits → 3-way (Save&open / Open-without-saving [keeps
  draft] / Cancel, default Cancel); a failed YAML validation aborts the hand-off (panel stays open).
- **P1-9** Focus-in with *both* an external `.md` change and a live draft → 3-way conflict
  (Keep mine / Load external / Keep both). "Keep both" writes the draft to a sibling
  `<note>.conflict-<ts>.md` via `atomic_write_text`, then reloads the external `.md`.
- **P1-10** Store-state-changed-under-the-panel: re-get by id before write; purged → don't
  recreate (offer "save as new note"); preserve the store's `deleted` flag.
- **P1-11** After an OS-editor edit, `NoteStore.reload_note(id)` resyncs the in-memory map + index
  from disk (called from the focus-in guard and on panel close of the OS-editor flow) so a later
  in-app write can't serialize a stale note over the newer file.

### 5.2 P2 — silent inconsistency / freeze (all MUST)
- **P2-1** Crash-after-commit orphan draft → `recover()` content compare → silent delete if
  identical (no false "recover" prompt).
- **P2-2** Declining the recovery prompt **is** a discard (route through `discard()`); a real
  unlink error propagates (no nag loop).
- **P2-3** Debounce timer is a child single-shot `QTimer(panel)`; `stop()` is the **first** line of
  commit / discard / close, before any promote/delete.
- **P2-4** `discard()` unlink: `FileNotFoundError` is the no-op success; a real `OSError`
  propagates → panel stays open with an inline error, never reports success.
- **P2-5** A debounced draft-write `OSError` never raises into the event loop: `write_draft`
  returns a result; the slot wraps `try/except OSError` and flips the dirty indicator to a visible
  "couldn't autosave" warning.
- **P2-6** `validate()` requires `id` present (`== loaded`) and restores a dropped `created`.
- **P2-7** `validate()` shape-checks typed fields (tags list-of-str; pinned/deleted bool;
  created/updated ISO) and rejects naming the bad field — no auto-repair.
- **P2-8** External-change detection keys on a **content hash** of the whole `.md` (not mtime, not
  the `updated:` field); also checked at commit time, not just focus-in; catches body-only edits.
- **P2-9** File deleted/renamed/moved externally → detector returns `source_missing` (no raise);
  panel shows an inline notice (Re-save here / Discard), never a silent stale-path write.
- **P2-10** External-editor lock on Windows: commit wrapped `try/except OSError`
  (`PermissionError`); keep draft, keep panel open, cancel the close, inline message.
- **P2-11** Open-time recover keyed on existence + content divergence (normalized), immune to an
  external save inverting timestamps.
- **P2-12** Close (X **and** Esc) routes through one `closeRequested` handler with a dirty
  Save/Discard/Cancel prompt (default Cancel); Esc wired via `keyPressEvent` (frameless widget has
  no auto-Esc); a plain close never deletes the draft.
- **P2-13** `dock_left_of` computes against the **anchor's current screen** (not `primaryScreen`),
  clamps the left edge, and reduces width so the header/close stay on-screen.
- **P2-14** Focus-in reload precedence on the editor's live dirty flag; cancel/flush the debounce
  first; update the baseline hash on the panel's own writes (don't read our own commit as
  "external").
- **P2-15** Cross-surface refresh: `committed` signal → `notes_view.refresh()` (mirror the existing
  `_on_note_saved` wiring); scope to the list.
- **P2-16** Pin/color/tag clobber prevented by the commit field-merge (P1-10 step 3); reverse
  direction — an in-app sibling write to the open note → reload the panel body if it has no draft.
- **P2-17** Raw-YAML `id` mutation handled by the same immutability rule as P1-5 (consolidated).

### 5.3 P3 — polish (SHOULD; all cheap, include)
- **P3-1** `promote()` treats the disposable index step as non-fatal (only the durable `.md` write
  gates success). *(already in §3.1 step 5)*
- **P3-2** `deleted` flipped false→true via the FM editor → a non-blocking "Moved to Trash — restore
  from the Trash tab" acknowledgment (no refusal, Trash is recoverable).
- **P3-3** "Open in OS editor": capture `QDesktopServices.openUrl` bool **before** closing; only
  close on `True`, else keep open + inline notice; gate the "no-op off Windows" claim on
  `platform_win.is_windows()`.
- **P3-4** Dock mode-switch (mini/hidden) → hide the panel beside `self.hide()`; on return to FULL,
  re-anchor (`dock_left_of`) + show; never close or prompt on a mode switch.
- **P3-5** Restore-focus-to-dock guarded: `if anchor and anchor.isVisible(): anchor.activateWindow()`
  wrapped in `try/except RuntimeError` (deleted C++ object on quit).
- **P3-6** In Text-search mode, call `semantic.index(all_active)` once before the post-commit
  rebuild when a `SemanticIndex` is wired (mirror `_open_duplicates`), so Related/meaning aren't
  stale.
- **P3-7** Same-id reopen → focus/raise the existing panel and return (skip re-running open/recover).
- **P3-8 (note, not new code here)** The existing no-tray `accept()` path (catalogued flow-20 in
  `notes/5_Interaction_Flows.md`) should route through `_quit()` so the panel tears down; track it
  with the existing gap, not as new Notes-expand work.

---

## 6. Files

**New:** `serenity/core/note_draft.py`, `serenity/ui/expanded_panel.py`,
`serenity/ui/note_editor_panel.py`, `tests/test_note_draft.py`, `tests/test_ui_expanded.py`.
**Edit:** `serenity/ui/platform_win.py` (`dock_left_of`), `serenity/core/note_store.py`
(`reload_note`, draft-aware `purge`), `serenity/ui/notes_view.py` (⤢ button),
`serenity/ui/shell.py` (open/teardown/refresh wiring).

---

## 7. Testing

- **Headless `tests/test_note_draft.py` (Qt-free, the bulk of the safety guarantees):**
  build_draft_text round-trips both panes (P1-6); validate rejects each bad case
  (invalid YAML, non-dict, changed/absent id, bad tags/pinned/created types) and accepts the good
  case (P1-1/5, P2-6/7); recover() — none / orphan-purged / identical-orphan / recoverable, content
  not mtime (P1-2/3, P2-1/11); detect_external_change — unchanged/changed/source_missing,
  content-hashed (P2-8/9); discard propagates real OSError (P2-4); promote — purged→raise, field-
  merge carries metadata, corrupt-backup, index-failure non-fatal (P1-7/10, P2-16, P3-1);
  reload_note + draft-aware purge on NoteStore (P1-3/11).
- **UI smoke `tests/test_ui_expanded.py` (offscreen):** panel builds + docks-left + width clamp
  (P2-13); dirty indicator; Ctrl+S commits via store + emits `committed`; X/Esc dirty prompt
  (P2-12); front-matter toggle; open-in-OS hand-off with `QDesktopServices` mocked, bool-gated
  (P1-8, P3-3); recovery prompt; same-id reopen raises existing (P3-7); mode-switch hide/show
  (P3-4).
- **Whole suite stays green** headless (`QT_QPA_PLATFORM=offscreen pytest`); `gitnexus
  detect_changes` low-risk before commit.

---

## 8. Risks / open notes
- `core/note_draft.py` is the heaviest new logic; keeping it Qt-free + exhaustively unit-tested is
  what makes the 28 P1/P2 guarantees verifiable without a display.
- The 3-way conflict prompts (P1-4/8/9) are *choices*, never merges — bounded UI.
- `ExpandedPanel` is built generic enough for Calendar-expand to subclass/host later, but we will
  not speculatively add Calendar hooks now (YAGNI).
