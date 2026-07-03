# 5 — Interaction Flows & Safety-Net Audit

This document is a consolidated, code-verified audit of Serenity's user-facing interaction flows and the interruption / failure points hiding inside them. For each of the seven functional areas — todos, notes, capture & voice, activity & mascot, lifecycle & window, settings, and AI maintenance — every flow was walked step-by-step against the *real* source (file + line references throughout), each interruption was classified **OK** (already handled / acceptable degrade) or **GAP** (a real exposure), and every GAP was given a minimal proposed safety net plus a Priority (P1 = data loss / irreversible / unreachable app, P2 = silent inconsistency or freeze, P3 = polish / cosmetic / niche) and Effort (S/M/L). It was produced by reading the codebase directly rather than from design docs, so several catalog assumptions were *corrected* against the code (e.g. graceful quit DOES flush todos; `undo_seconds` is coerced upstream; TodoStore persists per-mutation, not only at quit). The recurring root cause across areas is the non-atomic `write_text` shared by every JSON store — one atomic-write helper closes the largest family of P1s.

## Table of Contents

1. [Prioritized safety-net gaps](#prioritized-safety-net-gaps)
2. [Area: todos](#area-todos)
3. [Area: notes](#area-notes)
4. [Area: capture](#area-capture)
5. [Area: activity](#area-activity)
6. [Area: lifecycle](#area-lifecycle)
7. [Area: settings](#area-settings)
8. [Area: ai_maint](#area-ai_maint)
9. [Area: states-contexts (Phase C)](#area-states-contexts-phase-c)

## Prioritized safety-net gaps

114 gaps total: **16 P1**, **45 P2**, **53 P3**. Sorted P1 → P2 → P3.

| Area | Flow | Interruption | Priority | Effort | Proposed safety net |
|------|------|--------------|----------|--------|---------------------|
| todos | Cross-cutting (Flows 1,4,5,6,7,8,9,10,11) | Crash / power-loss / OS-kill during TodoStore.save() leaves todos.json truncated/half-written (non-atomic write_text). | P1 | S | Make save() atomic: write to todos.json.tmp then os.replace() onto todos.json (os.replace is atomic on same filesystem). Single ~5-line change in TodoStore.save (todo_store.py). |
| todos | Cross-cutting / Flow 2 (launch + render) | Corrupt/partial todos.json at launch is silently swallowed to an empty list — all todos appear lost, no backup, no recovery. | P1 | M | On a decode failure in reload(), rename the bad file to todos.json.corrupt-<ts> (keep one backup) before degrading to [], so the data is recoverable instead of overwritten by the next save(). ~6 lines in reload() (todo_store.py). |
| todos | Flow 9 (start/stop timer) | save() fails on stop_timer: elapsed is banked in-memory but timer_running_since (set by an earlier saved start) stays on disk -> the same span re-accrues on restart = double-counted time. | P1 | S | Covered structurally by the atomic-write net (no torn state). Residual double-count needs no extra code once save() is atomic: stop banks + clears in one atomic write, so disk is all-or-nothing. No separate change required beyond the P1 atomic-write fix. |
| notes | 9. Soft-delete — memory/disk divergence resurrects the note on restart | _write OSError after n.deleted=True was set in memory | P1 | M | In the guarded _write, on OSError restore the pre-write field on the Note object (or write before mutating) and propagate the error so the UI keeps the card; covered by the guarded-write fix |
| notes | 10. Restore — mirror divergence resurrects the note INTO Trash on restart | _write OSError after n.deleted=False was set in memory | P1 | S | Same guarded-write fix (restore the flag + propagate on OSError) |
| notes | 11. Purge — no confirm dialog on an irreversible delete | User misclicks the red 'Delete forever' button in Trash | P1 | S | Add a QMessageBox.question('Delete forever? This cannot be undone', default Cancel) in TrashRow.purge handler before calling purge |
| notes | 11. Purge — swallowed unlink error orphans the file → resurrection | Path.unlink fails (locked/permission) during purge | P1 | S | If unlink raises, do NOT remove the row / pop _notes; surface the failure so the user/app knows the file is still there (or retry). Minimal: catch separately and skip the _notes/db removal on failure |
| notes | 17. Merge — non-atomic two-note write can silently duplicate content | Crash/OSError between store.update(keep) and store.soft_delete(drop) in merge_notes | P1 | M | In merge_notes, soft_delete(drop) FIRST (or wrap both and on failure of the second roll back keep's body/tags); at the call site catch the error and show a message + keep the row. Minimal: reorder so the destructive append only commits after the drop is safely trashed, or guard+report. |
| notes | 17. Merge — sibling pruning skipped on a raised merge leaves re-mergeable stale rows | merge_notes raises at step 4 | P1 | S | Same fix as above (guard merge_notes at the call site); once the merge is transactional/guarded, pruning runs only on success |
| notes | 21. Tidy tags — non-atomic N-note bulk rewrite half-applies + stuck dialog | Crash/OSError partway through the consolidate_tag note loop | P1 | M | Wrap the call site in try/except: on failure show a QMessageBox naming partial application and keep the row; minimal data-side net is to catch per-note write errors in consolidate_tag and abort early returning how many were done so the UI can report. (consolidate_tag is already idempotent, so re-run finishes safely.) |
| capture | Cross-cutting — commit (Flows 5/6/7) | Crash / power-loss / disk-full mid-write of todos.json or a .md note | P1 | M | Write to a sibling temp file then os.replace() (atomic rename) in TodoStore.save (todo_store.py) and NoteStore._write (note_store.py); for notes, write the .md before the sqlite commit (already ordered) — make the file write temp+replace so a crash never leaves a truncated .md. |
| activity | Cross-cutting / flows 4,7,9,14 — persistence | Crash / power-loss / kill mid-write of activity.json (non-atomic write_text) | P1 | S | Write to a sibling .tmp then os.replace(tmp, self.path) (atomic on same FS) in ActivityStore.save. |
| lifecycle | All persisting flows (1 seed-save, 9 mute, 11 mode, 20 quit-tray-save-path, 21 quit, 23 board marker, 24 activity) | Crash / power-loss / disk-full mid-write during any settings.json / todos.json / activity.json save | P1 | S | Add an atomic write helper (write to <file>.tmp in the same dir, flush, then os.replace onto the target) and route Settings.save / TodoStore.save / ActivityStore.save through it. One small helper, three one-line call-site changes. |
| settings | 19. Remove a cloned voice | A single (mis)click on 'Remove selected clone' permanently unlinks the user-supplied reference clip and rewrites clones.json immediately; Close does not undo it. | P1 | S | Add a QMessageBox Yes/No confirm in _remove_clone before clones.remove(voice_id). |
| settings | 31. Save all settings (crash mid-write) | A crash/power-loss/full-disk mid-write truncates settings.json; next launch Settings.load swallows the corrupt file and resets ALL settings to defaults (total silent loss). | P1 | S | Write to a .tmp sibling then os.replace (atomic rename) in Settings.save; mirror in CloneRegistry.save. |
| ai_maint | 1.3 / 2.5 — board auto-open marker write + every store write | Crash / power-loss / disk-full DURING a write rewrites the WHOLE file via plain write_text; a torn write corrupts the file; ActivityStore.reload() then silently resets to an EMPTY log on JSONDecodeError -> all tracked-time history + the Friday board marker lost. | P1 | S | Add an atomic write helper (write to <path>.tmp then os.replace onto the target) and route ActivityStore.save / TodoStore.save / NoteStore._write through it. Minimal: one _atomic_write(path, text) + swap the three write_text calls. |
| todos | Flow 3 & Flow 9 (live timer across close) | Timer left running when app is killed/quit: timer_running_since persists but elapsed is only banked by stop_timer, so live_timer_seconds() accrues the entire offline gap (hours/days) with no cap. | P2 | M | Cap the live run: in live_timer_seconds (models.py) clamp the in-flight delta to a sane max (e.g. one working session), OR on app start in TodoStore.reload() bank+clear any timer_running_since older than a threshold. Prefer the reload-side reconciliation (~5 lines, todo_store.py). |
| todos | Flow 4 & Flow 5 (done-grace across close) | App quit/crash during the done-grace window silently drops the user's completion (grace timer is in-memory, _quit does not fire it). | P2 | S | On _quit, flush pending grace: before save, call self.todos_view flush that completes any todo currently in _grace_timers (or cancels them) so the user's tick is honored deterministically. Small handler in shell._quit + a flush method on TodosView (todos_view.py / shell.py). |
| todos | Flow 9 & Flow 8 (timer span on complete/soft-delete) | Completing or soft-deleting a todo while its timer runs silently discards the in-flight span (running_since cleared without banking). | P2 | S | Bank-on-clear: in complete() and soft_delete(), if timer_running_since is set, add the elapsed to timer_seconds before nulling it (mirror stop_timer's banking). ~3 lines each (todo_store.py). |
| todos | Flow 1 (add a todo) | parse_capture raising (dateparser import/locale-internal failure) propagates out of returnPressed; Qt swallows it and the todo is silently never created. | P2 | S | Wrap the parse_capture call in _add in try/except; on failure fall back to a plain Todo(title=text) so the todo is always created. ~4 lines (todos_view.py). |
| todos | Flow 2 & Flow 10 (refresh / drag reentrancy) | A grace/tick timer firing during refresh() teardown or during the blocking QDrag.exec triggers a nested refresh() that touches deleteLater'd cards -> RuntimeError on a deleted C++ object. | P2 | M | Add a reentrancy guard flag on TodosView (e.g. self._refreshing) checked at the top of refresh() and in _tick/_grace_fire, deferring re-entrant refreshes via QTimer.singleShot(0,...). ~6 lines (todos_view.py). |
| todos | Cross-cutting (external edits) | External edit to todos.json while the app runs is invisible until restart, and the next in-app save() silently clobbers it (last-writer-wins, whole-file overwrite). | P2 | M | Stamp the file mtime at load and re-check it before each save(); if the on-disk mtime is newer, reload-and-merge or at least back up the external version before overwriting. ~10 lines (todo_store.py). |
| todos | Flow 3 (live tick) | _tick hitting one deleted card (RuntimeError) aborts the whole loop and skips _sync_tick_timer -> tick timer stuck on/off. | P2 | S | Wrap the per-card card.tick(now) in try/except RuntimeError (skip dead cards) so one bad card cannot abort the loop. ~3 lines (todos_view.py). |
| notes | 1 & 2 & 7 & 9 & 10. NoteStore._write OSError is uncaught | Disk full / read-only vault / permission / path-too-long during any create/update/set_pinned/soft_delete/restore | P2 | M | Wrap the write_text in _write in try/except OSError: do NOT mutate self._notes/index and do NOT leave the passed Note's deleted/pinned flag changed on failure; raise a typed NoteWriteError. Catch it at the UI call sites (modals._save, shell._commit_capture, _on_delete, NoteCard._toggle_pin, TrashView restore) and show one QMessageBox. Single fix covers the whole family. |
| notes | 2. Voice-routed note create — _commit_capture OSError | _write OSError while persisting a voice-routed note (no dialog) | P2 | S | Covered by the guarded-write fix above; in _commit_capture catch NoteWriteError and have the mascot say a failure line instead of the success line |
| notes | 5. Meaning search — first-use model load freezes the UI thread | User switches to Meaning (or types) and the embedding model loads/downloads synchronously | P2 | M | Show a transient 'Indexing…' state (disable the toggle / cursor-wait) around the index() call; a full fix is to move index() off-thread, but the minimal net is a visible busy state |
| notes | 5. Meaning search — silent keyword degrade after a mid-session model-load failure | Embedding model fails to load AFTER SemanticIndex was constructed available=True | P2 | M | After index()/search() detect a no-op load (e.g. embedder._model() returned None / available flipped) and surface the existing notice; minimal: have FastEmbedBackend expose the cached failure and let SemanticIndex.available reflect it, then call _update_notice() post-refresh |
| notes | 6. Expand card — lazy Related model load freezes the UI thread | First expand of any card in Meaning-capable mode triggers semantic.index on the main thread | P2 | M | Same busy-state treatment as flow 5 (shared if index() is wrapped once) |
| notes | 7. Pin/unpin — _write OSError silently fails the toggle | _write OSError during set_pinned | P2 | S | Covered by the guarded-write fix; NoteCard._toggle_pin should catch NoteWriteError and revert the visual pin |
| notes | 14. Ask (RAG) — UI-thread inference with no busy state + empty-question no-op | User clicks Ask (long llm.generate / model load) or submits a blank question | P2 | M | Disable the Ask button + show 'Thinking…' while _ask runs (covers freeze perception and double-fire); on blank question set the answer_label to a prompt instead of a bare return |
| capture | Flow 2/3/4/5 — slot-filling & commit | _pending/_pending_slot never initialized, never cleared, overwritten unconditionally — mid-conversation mic-OFF or a stray answer mutates/commits the wrong capture or double-commits | P2 | S | Initialize self._pending=None/self._pending_slot=None in Shell.__init__; set both to None at the end of _commit_capture; in _demo_capture, refuse to overwrite (or explicitly discard with a voice line) when a _pending slot is still in flight. |
| capture | Flow 3/4/5/6/7 — any voice line during a pending slot | mascot.says() hides the slot-fill answer box while _pending stays alive → in-progress capture becomes unreachable and is silently abandoned | P2 | S | In SpeechBubble.set_text, do NOT hide the answer box if it is currently visible (a question is pending); only ask()/_send() control its visibility. Or guard in mascot.says to preserve a pending answer box. |
| capture | Flow 3/4 — slot-filling UI | User is trapped in the question box: no Esc, no cancel, only type+Enter | P2 | S | Add keyPressEvent on SpeechBubble: Esc clears the box, hides it, and emits a cancel signal the shell uses to drop _pending/_pending_slot. |
| capture | Flow 4 — answer a date slot | Date answer that parse_natural_date can't parse → identical prompt re-asked forever, no skip / give-up | P2 | S | Track a per-slot retry count on the shell; after N (e.g. 2) failed date parses, drop the date requirement (commit without due) or abandon the capture with a clear voice line. |
| capture | Flow 4 — _send empty answer | Pressing Enter on an empty/whitespace box hides it and emits nothing → _pending set, box gone, no re-prompt → abandoned capture | P2 | S | In _send, if text is empty do NOT hide the box (keep the question on screen) and optionally flash placeholder; only hide on a non-empty submit or explicit cancel. |
| capture | Flow 5 — note commit | Parsed tags are silently dropped from the committed note | P2 | S | Pass tags=cap.tags to note_store.create in _commit_capture (one-line fix). |
| capture | Flow 2/5/8 — commit / confidence | All-slots-filled (and low-confidence) captures commit straight to disk with zero confirmation | P2 | M | Before _commit_capture, when cap.confidence < 0.55 show a lightweight confirm (reuse the speech-bubble ask, or a small confirm dialog) instead of committing silently. |
| capture | Flow 6/7 — modal save raises | note_store.create / todo_store.add raises (read-only FS, permission denied, vault dir removed at runtime, disk full) → exception bubbles uncaught out of _save to Qt, modal stuck, nothing saved, no user-facing error | P2 | S | Wrap the create/add call in QuickNoteDialog._save and QuickTodoDialog._save in try/except OSError; on failure keep the modal open and surface a short inline error label instead of letting it raise. |
| capture | Flow 8 — date parse in slot answer | parse_natural_date raising on exotic input crashes _on_slot_answer with the box already hidden and _pending set → inconsistent stuck state | P2 | S | Wrap the dateparser.parse call in parse_natural_date in try/except returning None on failure (treat exotic input as 'unparseable', feeding the date-retry net). |
| activity | 7 / 13 — restore span at launch | Restored span has a parseable start but a present-yet-corrupt end field | P2 | S | In reload, when a row has start but an unparseable (non-None) end, clamp end=start (a 0-second closed span) instead of leaving it open. |
| activity | 4 / 5 — pick activity / Idle | activity_store.start()/stop() raises mid-save (disk full / read-only vault / disconnected drive) | P2 | S | Wrap the start/stop calls in _on_activity in try/except OSError and on failure show a one-line mascot notice so the failure is not silent. |
| activity | 6 — pick activity from Mini mascot then switch to Full | Mode switch to Full after picking on the mini mascot | P2 | S | In set_window_mode(MODE_FULL) after show_dock(), sync the full mascot pose from activity_store.running() using the ACTIVITIES label->state map (silent=True). |
| activity | 9 — weekly board auto-open latch | set_last_board_open save raises during the Fri 17-18h window | P2 | S | Wrap the set_last_board_open call in _maybe_auto_open_board in try/except OSError: return (skip this cycle on write failure). |
| activity | 9 — weekly digest generation | generate_digest raises (model OOM / corrupt GGUF) | P2 | S | Wrap generate_digest in refresh() in try/except Exception and fall back to the board's deterministic hint (same string the degrade path uses), keeping digest_text() non-empty. |
| activity | 13 — break-time tick AC probe | detect_on_ac() (psutil probe) raises with the [power] extra installed | P2 | S | Move state = self._derive_break_state() to INSIDE the existing try block in _break_tick (one-line move). |
| activity | 11 — pose swap | Pose webp missing or corrupt (incomplete install / packaging drop / wrong poses_dir) | P2 | S | Guard with QMovie.isValid() (or path exists) in _play_pose; if invalid keep the current self._movie rather than swapping to a broken one so the avatar never blanks. |
| activity | 14 — quit | activity_store.save() / todo_store.save() raises during _quit | P2 | S | Wrap each save in _quit in its own try/except Exception: pass so a failed save never blocks teardown. |
| lifecycle | 1 (launch), 11 (set_window_mode HIDDEN), 18 (hide to tray), 20 (close no-tray) | Window hidden into HIDDEN mode (persisted, or via eye-off / tray) on a system where the tray failed to show | P2 | S | In set_window_mode, when target is HIDDEN and `not self.tray.isVisible()`, fall back to MINI (or FULL) instead of hiding — never hide the only reachable surface. Guard is local to set_window_mode. |
| lifecycle | 10 (Open Settings) | User changes vault_path in Settings and clicks Apply | P2 | M | In _apply_settings, detect a vault_path change and either re-open the stores against the new path (re-run the constructor block from __init__ and refresh the views) or, minimally, show a 'restart required' notice so the user isn't silently split. |
| lifecycle | 11 (set_window_mode MINI), 12 (cycle), 13 (tray radio) | MiniWindow construction raises on first entry into MINI (e.g. MascotStage init fails) | P2 | S | Reorder to build/show the mini BEFORE hiding the main window (build mini, show it, only then hide main), or wrap _ensure_mini in try/except that reverts to FULL on failure. Local to the MINI branch. |
| lifecycle | 23 (Weekly-Board auto-open) | set_window_mode/switch_tab/digest_text raises after the day was already marked opened, OR a user's HIDDEN/MINI preference is silently overwritten to FULL | P2 | S | Mark last_board_open AFTER the board is successfully shown (move the set_last_board_open call to the end), and call set_window_mode(MODE_FULL, persist=False) for the auto-open so the user's persisted mode survives. |
| lifecycle | 20 (close, no tray) | Window closed on a system with no tray | P2 | S | In closeEvent, when the tray is NOT visible, call _quit() (real quit) instead of e.accept() — closing the only surface on a tray-less system should exit, not orphan. |
| settings | 31. Save all settings (partial apply) | Any exception partway through _save leaves the live shell settings half-mutated while save()/applied/accept are all skipped; app runs on an unpersisted, unapplied half-config and the language-cache/mute symptoms (flows 10,23) follow. | P2 | M | Build edits into a local dict (or snapshot the live fields), wrap mutate+save in try/except, and only commit to the live object after save() succeeds; on failure restore and keep the dialog open. |
| settings | 31. Save all settings (concurrent windows) | Gear and tray can each open a Settings window, each with its own CloneRegistry; two saves -> last-writer-wins on settings.json and clones.json, silently dropping the other's changes (also the stale-clone-ref in flows 13/16/18/19). | P2 | M | Keep a single SettingsWindow instance on the shell; in open_settings, if one is open, raise/focus it instead of constructing a second. |
| settings | 1 & 12. Open the Settings window / Kokoro folder scan | An OSError from scan_kokoro_voices on an unreadable voices_dir mount (or a raising semantic/tts import) propagates out of _general_tab build -> the whole Settings window fails to open, so the user cannot reach the toggle that would disable the broken backend. | P2 | S | Wrap scan_kokoro_voices in try/except (treat as no extras found) and guard the _general_tab optional imports so a broken/half-installed extra degrades the section instead of bricking the dialog. |
| settings | 5. Change the vault path | A manually typed vault path that does not exist / is not writable is accepted verbatim; failure only surfaces at next Shell.__init__ when the stores can't be built; meanwhile the field shows the new path but writes still go to the old vault. | P2 | M | Validate the typed path is an existing/creatable, writable dir at _save; warn-and-keep-old if not, plus a one-line note that a vault change applies on restart. |
| settings | 18. Add (clone) a voice | clones.add copies the clip (shutil.copyfile, non-atomic) then save()s; a failure between the two, or a crash mid-copy, leaves an orphaned/truncated clip that exists() reports as valid (broken-but-listed clone). Re-adding the same name+lang overwrites a working clip in place with no backup. | P2 | M | In CloneRegistry.add, copy to a temp dest then atomic-rename, and persist save() atomically, so a failure leaves no half-written clip. |
| ai_maint | 4 / 5 / 6 / 9 — first heavy backend load on the synchronous break tick | The break tick runs synchronously on the Qt main thread. The first real run cold-loads a multi-GB GGUF and/or downloads+loads the e5 model and/or makes up to 5 generate() calls. The UI fully freezes for seconds-to-minutes; the user may force-quit. | P2 | M | Smallest safe net WITHOUT the full QThread move: before running HEAVY jobs in _break_tick, set the mascot to a thinking/working state so a freeze reads as deliberate work. The principled fix is to run tick() on a QThread with a single guarded VectorStore connection (L effort). Recommend the mascot-state hint now (S) and track the QThread move separately. |
| ai_maint | 4 / 5 / 10 — sticky load-failure not reflected in availability or status | available is computed ONCE at construction as file-exists+import-OK. A first-use load failure sets _shared=False STICKY, never retried. The Settings panel _probe_status builds a fresh throwaway instance reading file-exists -> shows Active for a model that actually fails to load. | P2 | M | Expose the real load outcome: add a class-level load_failed flag set when _shared=False and have _probe_status read it for the shell's live engine (pass self.llm into SettingsWindow rather than constructing a throwaway). Minimal honest fix: probe the SHELL's self.llm instead of a fresh instance, label it 'model present but failed to load' when _shared is False. |
| ai_maint | 7 / 11 — user-driven slots that omit _touch() | _on_todo_started, _on_todo_completed, _on_focus_phase, _on_quick_todo, _on_note_saved do NOT call _touch(); the idle clock keeps accruing while the user is actively clicking -> a HEAVY break job can fire mid-use and freeze the UI. | P2 | S | Add a single self._touch() call at the top of each of the five slots. Trivial one-liners restoring the any-interaction-looks-busy invariant. |
| ai_maint | 1.3 — board auto-open marker write raises (permission / disk-full), not caught | set_last_board_open(now)->save() can raise (permission / disk-full) and is NOT wrapped at the call site; the exception propagates out of the 60s QTimer slot; the marker is not persisted -> the board re-fires every 60s for the whole 17-18h window. | P2 | S | Wrap the set_last_board_open(now) call so that on write failure an in-memory same-day guard (self._board_opened_date = now.date()) is still set and checked alongside the persisted marker, so a failed persist does not cause minute-by-minute re-opens. |
| todos | Flow 11 (prep-note link) | Crash/failed store.update between writing the note .md and appending linked_note_ids leaves an orphaned note in the vault; a re-click creates a second orphan. | P3 | M | Append linked_note_ids and store.update FIRST (cheap, atomic via the save() net), then create the note .md; or wrap so a failed link cleans up the just-created note. Reorder + small guard (todos_view.py). |
| todos | Flow 10 (drag-to-reorder) | Reordering within the urgent band has no visible effect (ranking sorts tiers 2/3 by deadline, ignoring the written order) -> user perceives the drag as broken. | P3 | S | UX-only: suppress/disable the grip drag for cards in an urgent tier, or show a brief 'urgent items sort by deadline' hint. Small guard in TodoCard._begin_drag (todos_view.py). |
| todos | Flow 10 (drag-to-reorder) | Repeated reorders via src.order = tgt.order - 1 produce duplicate/negative order values; ties break arbitrarily -> manual order degrades to non-deterministic/sticky. | P3 | M | Add a renormalization step after reorder: reassign sequential order values (0,1,2,...) to active todos before save. ~8 lines (todos_view.py or a TodoStore.renumber helper). |
| todos | Flow 6 (add a subtask) | Enter-spam: the first add refreshes and replaces the add-subtask QLineEdit; a second Enter on the now-deleted old editor calls editor.text() on a dead C++ object -> RuntimeError, second subtask dropped. | P3 | S | Guard editor access in _add_subtask with try/except RuntimeError (or check shiboken isValid) and no-op on a dead editor. ~3 lines (todos_view.py). |
| todos | Flow 7 (inline edit) | editingFinished fires twice (Enter then focus-out): the first commit's refresh() deletes the editor, the second editingFinished fires on the deleted editor -> RuntimeError. | P3 | S | In commit(), disconnect the signal (or set a committed flag) before calling changed.emit()/refresh so the second emission is a no-op. ~3 lines per editor (todos_view.py). |
| todos | Flow 8 (recurring spawn) | An unrecognized recurring label (e.g. externally-set 'bi-weekly') makes next_due return None -> every completion spawns another undated clone -> slow orphan accumulation. | P3 | S | In _spawn_recurrence, skip the spawn when next_due returns None (or log/normalize the label) so an unknown rule does not breed undated clones. ~3 lines (todo_store.py). |
| todos | Flow 8 (recurring spawn) | Reopen/restore of an already-completed recurring todo does not remove its already-spawned clone -> duplicate next-occurrences. | P3 | M | On reopen of a recurring todo, detect and remove the most-recent un-touched spawned clone (match title+recurring+done=False+empty timer), or skip — acknowledge as known minor. ~10 lines (todo_store.py). |
| todos | Flow 11 (prep-note link) | A linked note trashed/purged externally leaves its dead id in linked_note_ids; a re-click appends a new id, so dead ids accumulate unbounded across trash/recreate cycles. | P3 | S | In _on_note_btn, before creating a new note, prune linked_note_ids of ids whose note is missing/deleted. ~3 lines (todos_view.py). |
| notes | 1. Quick-note create — empty-guard returns without accept() | User has only tags/title (body cleared) and the empty-body+empty-title guard fires | P3 | S | Show an inline hint (or keep focus + status label) when both fields are blank instead of a bare return; only block when truly empty |
| notes | 1. Quick-note create — Esc/close discards draft | User presses Esc or closes the app mid-compose | P3 | S | On reject() when title/body/tags are dirty, ask a discard confirm (QMessageBox); optional, low value for quick-capture |
| notes | 8. View raw .md — footer claims 'on disk' but shows memory on read failure | Path(note.path).read_text raises OSError (file deleted/permission) | P3 | S | Have read_raw signal the fallback (return a flag or raise) and let RawFileDialog swap the footer to 'showing the in-memory copy; the file could not be read' |
| notes | 12 & 13 & 15. Related/cited/linked chip opens a ghost (deleted/merged/purged) note | The note a chip/row captured at build time is deleted or purged before the click | P3 | M | In ReadNoteDialog.__init__, re-get the note by id from notes_provider/store; if absent, show a small 'This note has been deleted' banner instead of presenting a ghost as live |
| notes | 14. Ask (RAG) — degrade line hidden after a mid-session LLM load failure | LLM loaded-then-failed; no answer comes back but available is stale-True | P3 | S | Show the degrade line whenever result.answer is empty but sources exist, regardless of the available flag (rely on the actual empty answer, not the flag) |
| notes | 16. Find duplicates — UI-thread index() + O(n^2) scan in __init__ with no feedback | User clicks 'Find duplicates' on a large vault | P3 | M | Show a busy cursor / 'Scanning…' around the index()+dialog construction; minimal net is the visible busy state (off-thread scan is the larger fix) |
| notes | 16. Find duplicates — footnote mislabels the scan method | Semantic path is available but degraded to tokens internally (empty/unindexed store) | P3 | S | Key the footnote on whether the semantic path produced any pairs (or on _index_populated), falling back to the 'text overlap' wording |
| notes | 21. Tidy tags — confirm shows a stale count and the real count is discarded | Vault changed between scan-on-open and Apply, or the typed canonical changes the variant set | P3 | S | Use consolidate_tag's return value to show a brief 'Renamed N note(s)' confirmation (status label or transient message) after Apply |
| notes | 22. Edit canonical — free-text canonical can silently merge two unrelated tag namespaces | User types a canonical that collides with an existing unrelated tag not in the group | P3 | M | When the typed canonical is NOT one of group.all_tags but DOES already exist elsewhere in the vault/arsenal, add a one-line warning to the confirm dialog ('"X" is already used by other notes; they will be combined') |
| capture | Flow 1 — mic ON cheatsheet | CheatsheetDialog orphaned / stacked: opened modeless with no stored handle; mode-switch/hide-to-tray never closes it; repeated ON spawns multiple stacked dialogs | P3 | S | Store the dialog on self._cheatsheet; on a second ON raise/reuse the existing one instead of creating another; close it on mic OFF and on hide_to_tray. |
| capture | Flow 1 — recording state | recording stays ON (pink mic) after hide-to-tray / mode switch; nothing is being captured | P3 | S | On hide_to_tray and set_window_mode(HIDDEN/MINI), reset the capture bar recording state to OFF (call a CaptureBar.reset()). |
| capture | Flow 6/7 — empty modal save | Save with empty title (todo) or empty title+body (note) is a silent no-op; modal stays open with no feedback, user may think it saved | P3 | S | Add a brief inline hint label / field highlight on the empty-save path so the user sees why nothing happened. |
| capture | Flow 7 — quick todo parse | Date/tag tokens in the title field bleed into the due date while the literal title is also stored (e.g. 'Call Monday team' → title kept verbatim AND due=Monday) | P3 | S | Parse only the `when` field for date/recurring/tags (parse_capture(when)) rather than title+when, so the title field never bleeds into the due date. |
| capture | Flow 4 — slot title | Title slot accepts any string (no length cap); flows into store and the note filename slug | P3 | S | Cap/trim the slot title length in _on_slot_answer (e.g. first ~200 chars) before assigning. |
| activity | 2 / 3 — close selector | A bubble click and an avatar/empty re-click land in the same event-loop pass | P3 | S | In close_selector, before deleteLater, b.clicked.disconnect() (or b.setEnabled(False)) so a queued click cannot reach _on_pick. |
| activity | 3 — close selector via Esc | User presses Esc to dismiss the selector (the documented gesture) | P3 | S | Either fix the docstring to 'click-away / re-click closes', or add a 3-line keyPressEvent calling close_selector() on Qt.Key_Escape. Doc fix is smaller. |
| activity | 4 / 8 — running chip lifecycle | The chip's span is closed elsewhere (Idle via mini / new activity) but the chip is not refreshed | P3 | S | In ActivityChip.tick, if self._entry.end is not None call self.clear() and return — self-heals a stale chip on the next 1s tick. |
| activity | 4 — pick Focus while already focusing | User re-picks Focus during an in-progress Pomodoro block | P3 | S | In FocusWidget.start, if self.pomo.phase != Phase.IDLE just show()+_render() (resume the existing session) instead of re-starting. |
| activity | 5 — pick Idle when nothing is running | Repeatedly picking Idle with no running span | P3 | S | In ActivityStore.stop, only save() when entry is not None (one-line guard). |
| activity | 9 — auto-open mode flip | Friday auto-open forces and persists MODE_FULL over a user-chosen Hidden/Mini | P3 | S | Call set_window_mode(MODE_FULL, persist=False) in the auto-open path so the temporary review pop does not overwrite the chosen mode. |
| activity | 9 — auto-open latch ordering | Crash between set_last_board_open and the board actually showing | P3 | S | Move set_last_board_open(now) to after switch_tab('board') so the latch reflects an actually-shown board. |
| activity | 7 — restore parsing | A persisted row has a corrupt/truncated start (or the whole file is partially corrupt) | P3 | S | Emit a stderr log/print when a row is dropped in reload so silent history loss is at least observable (no recovery logic). |
| activity | 11 — custom state map | User authors a state_map with empty/missing idle (e.g. 'idle':[]) | P3 | S | In set_state, when fname is None fall back to a hardcoded known-good idle filename so the avatar always has a frame. |
| activity | 6 — mini mode tracking cue | User starts a span in Mini mode and forgets it is running | P3 | M | Optional tiny 'tracking <cat>' label on the mini strip driven from activity_store.running() in refresh_todo. Arguably by-design (Mini is intentionally minimal) — defer. |
| activity | 8 — chip timer on hide | Dock hidden to tray / Mini while a span is running | P3 | S | Pause the chip timer when the full dock is hidden (or add a public pause). Low priority — self-corrects, no data/UX impact. |
| activity | 10 / 14 — daemon TTS thread at quit | A synth daemon thread is mid-cache-write when the process exits | P3 | M | Belongs to TtsCache write atomicity (out of this area's scope) — note for the tts_cache owner; no activity-log impact. |
| lifecycle | 2 (second launch) | User double-clicks the (windowed) exe while an instance is already running | P3 | M | Optional: have the running instance listen (QLocalServer) and the second launch send a 'show' message before exiting, so a re-launch surfaces the existing window. Larger; acceptable to leave as-is for a tray-resident app. |
| lifecycle | 3 (autostart reconcile) | HKCU Run key write fails (group policy / locked-down registry), or the exe was moved/renamed | P3 | M | Optional: surface a one-time non-blocking notice when get_autostart()!=setting after a write attempt, or compare the stored command string to the expected one so a moved-exe stale key is detected and rewritten. |
| lifecycle | 8 (toggle always-on-top) | User toggles the pin, then quits/crashes | P3 | S | Optional: add an `always_on_top` bool to Settings and persist it in toggle_on_top, restoring it on launch. Only if consistency with the other title-bar toggles is wanted. |
| lifecycle | 14 (lazy mini creation), 26 (docking) | dock_right fails on first mini creation (no screen / exception), or the docked monitor is unplugged / resolution changes while running | P3 | M | Optional: re-dock the mini on each MINI entry (call dock_right in the MINI branch, not just _ensure_mini), and connect QGuiApplication primaryScreenChanged / screen geometryChanged to re-run dock_right. Recoverable via tray→FULL today, so low priority. |
| lifecycle | 22 (minimize) | User clicks minimize on a frameless Qt.Tool window (may not show in taskbar) | P3 | S | Optional: route the minimize button through hide_to_tray (HIDDEN) instead of showMinimized so tray-click restore is consistent, or have _on_tray_activated restore on a minimized window too. |
| lifecycle | 24 (activity / Focus) | User picks Focus while a Focus Pomodoro is already running | P3 | S | Optional: in FocusWidget.start (or the Focus branch of _on_activity), no-op / keep the running session if a Pomodoro is already active instead of restarting. UX only, no persisted data at risk. |
| lifecycle | 25 (break-time tick) | A maintenance job runs long, or fails, during a synchronous break tick | P3 | L | Optional (already flagged as future hardening in the docstring): move tick() onto a QThread after vetting SemanticIndex/sqlite-vec thread-safety, and record a failed-job result in the except branch so the panel reflects failures. |
| settings | 6. Toggle autostart | On Windows with an unwritable/locked HKCU, set_autostart(True) returns False silently; JSON says autostart ON but the Run key was never written, so 'start on login' silently never works (shell retries next launch but can keep failing). | P3 | S | Check set_autostart's return value in _save (Windows only) and show a one-line warning when enabling failed. |
| settings | 3. Edit the state->pose map | Typos / all-invalid keys for a state are silently discarded; that state falls back to the default pose with no feedback, and a deliberately-blanked state also reverts to default (cannot silence a pose). | P3 | S | If _save discarded any typed key, show a one-line inline warning naming the affected state(s). |
| settings | 24. Change the theme accent | An invalid color string (e.g. 'notacolor') is persisted and fed to the stylesheet; Qt silently ignores it -> garbled/unstyled accent with no error. | P3 | S | Validate with QColor(text).isValid() at _save; keep-old and warn if invalid. |
| settings | 7. Edit the global capture hotkey | Free text is unvalidated; a blank empties the hotkey entirely (disabling global capture, inconsistent with the keep-old behavior of most other fields), and a bad/conflicting combo silently never binds with no feedback. | P3 | S | Keep-old on blank for consistency, and/or a note that an invalid combo will not bind. |
| settings | 12. Kokoro voice (all-languages toggle) | Toggling 'show all languages' off when the current pick is not in the new list silently falls the selection back to af_heart/first row; a subsequent Save persists the fallback, not the user's intent. | P3 | S | Minor: surface a brief note when the prior Kokoro pick is unavailable in the current list so a Save isn't a silent change. Low priority. |
| settings | 10. Toggle master TTS on/off | If tts_enabled changes out-of-band (tray/hotkey mute) between opening Settings and clicking Save, _save overwrites it with the stale checkbox value seeded at open time, silently reverting the out-of-band change (masked by _sync_mute_icon). | P3 | S | Narrow timing window; lowest-cost handling is to accept/document. Optional: only write tts_enabled if the checkbox was actually toggled. |
| ai_maint | 3 / 6 — silent swallowing of all break-tick / digest failures | _break_tick wraps the whole tick in try/except: pass with no logging; a persistently-raising job or perf/record error produces NO user-visible signal except a JobResult string in the Settings panel. Combined with the sticky load-fail, a dead AI backend is invisible. | P3 | S | Replace the bare pass with a logging.exception (or debug log) so failures are at least recorded; do NOT add user-facing alerts (would violate quiet-degrade). One-line change inside the except. |
| ai_maint | 2 / 7 / 12 — digest warm-cache not invalidated on language switch | _board_sig keys the digest cache ONLY on board numbers, omitting language. _apply_settings clears task_lines on a language change but NOT board_view._digest/_digest_sig -> the Friday flow speaks a new-language intro + old-language digest. | P3 | S | In _apply_settings, when _lang != settings.language, also reset the board digest cache (self.board_view._digest_sig = None or a small invalidate_digest() on the view) right beside the existing task_lines.clear(). One added line/call. |
| ai_maint | 3 — digest CARD shown (duplicating hints) when LLM is Active-but-load-dead | When available is True but the model fails to load at generate time, generate_digest returns the fallback hint text, but refresh() reads ai=available=True and shows the Serenity's-note card AND the hints card with the SAME sentences -> duplicated text on one screen. | P3 | M | Have generate_digest signal fallback-vs-authored (return a flag, or have the view compare _digest against board fallback / track an authored bool set in the cache block) and gate the digest card on authored rather than on available. |
| ai_maint | 9 / 11 — stale per-task voice line after a todo title edit | A personalized line is keyed by todo.id and is only invalidated on a language change, never on a title edit. If the user renames a todo after a line was authored, _on_todo_started speaks the line nodding to the OLD title. | P3 | M | On a todo edit that changes the title, drop its cached line: add a per-id delete (pop(todo_id)) to TaskLineStore and call it from the todo-edit slot. Low value (a full regenerate happens next break anyway). |
| ai_maint | 5 — orphaned partial fastembed download re-fails every launch | If a first-run model download is interrupted, fastembed can leave a half-downloaded model in the per-user cache; the next load raises -> sticky _shared=False, and the corrupt cache is NOT cleaned up -> it re-fails on every launch until the user manually clears the cache. | P3 | S | Out of scope for a minimal net (depends on fastembed cache internals). Document the manual-clear recovery in the Settings status detail string ('keyword-search fallback - clear model cache and restart to retry') so the user has a recovery action. |
| ai_maint | 6 / 10 / 13 — AC / perf psutil probe on the UI/main thread | detect_on_ac() runs psutil.sensors_battery() on the main thread every break tick and again in the Settings dialog build. A hung sensor read blocks the tick / freezes the open Settings dialog. | P3 | S | Low priority given rarity. Minimal mitigation: cache the AC result across ticks (probe once per N ticks instead of every tick and every dialog open); or accept as-is since it never raises and slow battery sensors are rare. Recommend deferring unless observed. |
## Area: todos

## Todos area — audited interruption / failure analysis

Read against real code: `serenity/core/todo_store.py`, `serenity/ui/todos_view.py`, `serenity/core/models.py`, `serenity/core/ranking.py`, `serenity/core/recurrence.py`, `serenity/core/parser.py`, `serenity/core/note_store.py`, `serenity/ui/shell.py`, `serenity/core/settings.py`.

### Substrate facts CONFIRMED in code
- **`TodoStore.save()` is non-atomic** (`todo_store.py:58-61`): `self.path.write_text(json.dumps(...))` — truncate-then-write in place, no temp+`os.replace`. CONFIRMED. Whole-list serialize every call.
- **`reload()` swallows corruption to `[]`** (`todo_store.py:41-48`): `JSONDecodeError`/`OSError` → `data = []`, no backup, no surfaced error. CONFIRMED.
- **All grace timers in-memory** (`_grace_timers`, `todos_view.py:489`); `_tick_timer` in-memory. CONFIRMED.
- **No re-`reload()` after construction** in this view → external edits invisible + clobbered by next `save()`. CONFIRMED.

### Two briefing assumptions CORRECTED against code
1. **Graceful quit DOES flush.** `_quit()` calls `self.todo_store.save()` (`shell.py:792-793`). So a *normal* close persists in-memory state including a running timer's `timer_running_since`. Only a **hard crash / OS-kill** loses unsaved state. The briefing's "app closed discards everything" is only true for the crash/kill path, not the menu-quit path. (`closeEvent` defaults to hide-to-tray, `shell.py:784-790`, so the app rarely truly closes.)
2. **`undo_seconds` cannot make `_arm_grace` raise.** `Settings.load()` coerces it to int with a try/except fallback to 5 (`settings.py:97-100`) BEFORE it ever reaches the UI. The `max(0, int(self.settings.undo_seconds))` in `_arm_grace` (`todos_view.py:563`) is redundant-safe. `undo_seconds = 0` → 0 ms single-shot = effectively instant complete (no undo window) — a config choice, not a bug. Classified OK.

---

### Flow 1 — Add a todo
- **`parse_capture` raises** — `_add` (`todos_view.py:496-509`) has NO try/except. dateparser normally returns `None` on bad input (does not raise), but import/locale-internal failures can raise; exception would propagate out of `returnPressed`, Qt swallows it, todo silently never created. Real but low-probability. **GAP** (P2, S).
- **Past/ambiguous parsed date** — future-bias + `_normalize_uhr` (`parser.py:166-172`) handle the common cases; a new todo landing in tier-3 is cosmetic, not data loss. **OK.**
- **`store.add` → `save()` crashes mid-write** — `add` appends in-memory (`todo_store.py:86`) THEN `save()` (`:88`). A failed/torn write means the card shows after `refresh()` but is not persisted, OR torn write corrupts the whole file → all todos lost next `reload()`. Root cause = non-atomic save + silent-corruption reload. **GAP** (P1, M) — covered by the cross-cutting atomic-write + backup net.
- **settings.save() fails after todo saved** — `_add` (`:504-506`) saves todo first, then settings (two separate files). Orphaned tags are recoverable on next add; no todo loss. **OK** (acceptable).
- **Title becomes only date tokens** — `_clean_title` → `""`, then `Todo(title=cap.title or text, ...)` falls back to raw text (`:501`). Surprising title, not lost. **OK.**
- **Esc / click-away mid-typing** — no capture, benign. **OK.**

### Flow 2 — Render / rank
- **Empty in-memory list after bad reload** — `refresh()` shows empty silently. Surfaced only as emptiness; no warning/backup. **GAP** (P2, S) — a "todos.json was unreadable" surfacing; folded into the reload-backup net.
- **Card build raises mid-loop** — `_build` reads `ranking.*`; `from_dict` already null-guards `due`/lists (`models.py:122-142`), so malformed fields are coerced. A raise would half-build the list and skip `_sync_tick_timer`. Low probability given coercion. **OK** (defended by `from_dict` coercion).
- **Grace fires during teardown / nested `refresh()`** — `_grace_fire` → `_on_completed` → `refresh()` re-entrant while outer refresh mid-loop. `_grace_timers` keyed by id survives rebuild and `show_grace_pending` re-applies state (`:530-531, 277-283`), but a nested refresh during teardown can touch `deleteLater`'d C++ objects → RuntimeError. Real reentrancy hole. **GAP** (P2, M).
- **deleteLater'd cards receiving queued signals** — Qt mostly drops events to deleted objects; can throw "wrapped C/C++ object deleted". Low impact. **OK** (Qt-handled, cosmetic).

### Flow 3 — Live tick
- **Crash while timer running** — `timer_running_since` persisted at start (`todo_store.py:144,147`); only `stop_timer` banks elapsed (`:154-156`). On *crash* relaunch the timer is still "running" and `live_timer_seconds(now)` accrues the entire offline gap, with NO cap and NO "was-app-open" check (`models.py:86-92`). Inflated/garbage elapsed; banked permanently if later stopped. (Graceful quit re-saves but does not stop, so even a clean quit leaves it running across the closed interval.) **GAP** (P2, M).
- **`_tick` hits a deleted card** — `_tick` loop (`todos_view.py:542-547`) has no per-card try/guard; one deleted C++ object aborts the whole loop and skips `_sync_tick_timer` → tick stuck on/off. **GAP** (P2, S).
- **Clock backward / DST** — `live_timer_seconds` clamps with `max(0,...)` (`models.py:91`) — safe. `_due_label`/heat use raw deltas — cosmetic only. **OK.**

### Flow 4 — Complete via done-grace
- **App closed during grace window** — `_grace_timers` in-memory; `_quit` does NOT fire pending completions (no flush of grace state). On quit/crash the "done" tick is silently dropped, todo stays active. Favors not-losing the task; contradicts the user's tick. **GAP** (P2, S).
- **Crash during `_grace_fire`→`complete`→`save()`** — torn write corrupts whole file. `_spawn_recurrence` appends clone in-memory (persist=False, `todo_store.py:179`) and the single `save()` (`:108`) flushes done+clone together (no half-spawn) — but still rides the non-atomic write. **GAP** (P1) — covered by atomic-write net.
- **Concurrent edit during window** — `_grace_fire` re-fetches by id via `store.get` (`:574`), completes consistently. Un-tick after edit's rebuild routes through `show_grace_pending`+`grace_cancelled`. **OK** (designed for).
- **Soft-delete vs purge during window** — purge → `store.get` None → `_grace_fire` no-ops (`:575`), clean. Soft-delete → completes a deleted todo (done+deleted, stays in Trash once), consistent. **OK.**
- **`undo_seconds` misconfigured** — coerced upstream (see correction #2). `0` = instant complete by design. **OK.**

### Flow 5 — Toggle subtask / auto-complete
- **`store.update`→`save()` fails** — `st.done` set in-memory before save (`:286-287`); failed write → UI shows ticked, not persisted; torn write → whole-file corrupt. **GAP** (P1) — atomic-write net.
- **Closed between subtask save and auto-complete grace firing** — subtask `done` IS saved; grace is in-memory → on restart all subtasks done but todo not completed (looks finished, sits active). Inconsistent. **GAP** (P2, S) — same root as Flow 4 grace-not-persisted.
- **Un-tick different subtask during window** — `_on_subtask` else-branch unchecks the box → `_cancel_grace` (`:301-305`). Correct; brief un-reverted strikethrough is cosmetic, resolves on refresh. **OK.**
- **In-place repaint / `subtask_count` None** — guarded (`:296`). **OK.**
- **Rapid double-tick** — two `save()` calls, second wins, no corruption beyond widened torn-write window. **OK** (subsumed by atomic-write net).
- **Stale `self.todo` resurrect via `update`** — only reachable if a reload path is added; not currently reachable. **OK** (latent; note it).

### Flow 6 — Add a subtask
- **Empty input** — returns (`:309-310`). **OK.**
- **append→`save()` fails** — appended in-memory before save (`:311-312`); failed/torn write → lost/corrupt. **GAP** (P1) — atomic-write net.
- **Enter-spam on deleteLater'd editor** — `changed.emit()`→`refresh()` rebuilds card + replaces the add-subtask QLineEdit; a second Enter on the old (deleted) editor → `editor.text()` on dead C++ object → RuntimeError, second subtask dropped. Real fast-typing edge. **GAP** (P3, S).
- **Invalid surrogate text → `json.dumps` raises** — would throw in `save()` → not persisted + possible partial write. Very rare. **OK** (subsumed by atomic-write net; partial-write avoided once writes are atomic).

### Flow 7 — Inline edit title / subtask
- **Click-away auto-commits** — `editingFinished` on focus-out commits (`:336,366`). Empty/unchanged commits are no-ops (`:331,361`); only a non-empty changed text overwrites. Accidental partial-edit overwrite possible (old title replaced, not lost-to-nothing). Behavioral, low harm. **OK** (acceptable Qt convention).
- **`editingFinished` fires twice (Enter then focus-out)** — first `commit()`→`refresh()` destroys the editor; second `editingFinished` fires on the deleted editor → RuntimeError. Known Qt commit-deletes-its-own-widget footgun; present in both `_edit_title` and `_edit_subtask`. **GAP** (P3, S).
- **Save fails on commit** — in-memory before `store.update` (`:332-333`); reverts on restart / torn-write corrupts. **GAP** (P1) — atomic-write net.
- **Subtask row not found (stale lab)** — `target is None` → returns (`:350-351`), benign. **OK.**
- **Closed mid-edit (uncommitted)** — text lost; expected for an open editor. **OK.**

### Flow 8 — Recurring spawn
- **Crash between spawn and `save()`** — clone appended persist=False (`:179`), shared single `save()` (`:108`) → all-or-nothing (no half-spawn). Torn write still corrupts whole file. **GAP** (P1) — atomic-write net; spawn logic itself **OK.**
- **`next_due` None (unknown rule)** — `recurrence.py:47-63` returns None for unmatched labels (e.g. externally-set `"bi-weekly"`). Clone gets `due=None` → undated clone, and every completion spawns another undated one → slow orphan accumulation. Only reachable via external/corrupt `recurring` value (the parser only emits known labels). **GAP** (P3, S).
- **`_add_month` invalid base** — `calendar.monthrange`+`min(day,last_day)` clamps (`recurrence.py:42-44`) — Jan-31→Feb-28 safe. Naive-datetime DST shift is cosmetic. **OK.**
- **Recurring completed while timer running** — `complete` sets `timer_running_since=None` without banking (`:104`); in-flight span silently discarded. Consistent with Flow 9 (only `stop_timer` banks). **GAP** (P2) — same root as Flow 9 unbanked-span.
- **Duplicate clones on re-complete/restore** — `_grace_timers.pop` prevents double-fire of the same window; reopen of a completed recurring todo does not remove its already-spawned clone → possible duplicate next-occurrences. **GAP** (P3, M).

### Flow 9 — Start / stop timer
- **Crash/quit while running** — biggest hazard, same as Flow 3: persisted `timer_running_since`, only `stop_timer` banks, no cap/no app-open check. **GAP** (P2, M) — single net with Flow 3.
- **`save()` fails on stop** — `stop_timer` banks `timer_seconds += elapsed` in-memory before save (`:154-160`). Failed stop-write → banked span not on disk, but `timer_running_since` still set from the earlier saved start → on restart the same span re-accrues = **double-count / time-accounting corruption** from one failed write. **GAP** (P1, M) — atomic-write net reduces torn-write; the double-count specifically needs clearing `timer_running_since` and banking in one atomic write.
- **Complete/soft-delete before stop** — `complete`/`soft_delete` clear `timer_running_since` without banking (`:103-104,127-128`) → in-flight span silently lost. **GAP** (P2, S) — bank-on-clear.
- **Two stale cards interleave start/stop** — `start_timer` guards `if not t.timer_running` (`:143`); shouldn't reset timestamp. Post-refresh single-card invariant holds. **OK.**
- **Mascot side-effect failure** — `_on_todo_started` (`shell.py:422-430`) degrades to catalog line when voice/LLM absent; timer already persisted, only the reaction lost. **OK** (degrade pattern).

### Flow 10 — Drag-to-reorder
- **Drop on empty space** — no `dropEvent` → no `reorder` emit; silent no-op, expected. **OK.**
- **Source/target purged mid-drag** — `_on_reorder` (`:578-585`) no-ops if either lookup None. But a *completed* target stays in `all()`, so `src.order = tgt.order - 1` lands relative to a trashed target → odd placement, not data loss. **OK** (acceptable; minor).
- **`save()` fails after reorder** — `src.order` in-memory before `save()` (`:583-584`); torn write corrupts. **GAP** (P1) — atomic-write net.
- **Reorder within urgent band has no effect** — ranking sorts tier 2/3 by deadline first (`ranking.py:88-96`); the written `order` is ignored → user sees drag as broken. Confusing, no corruption. **GAP** (P3, S).
- **Order collisions / negative orders** — `tgt.order - 1` can collide/go negative over many reorders; no renormalization. Sticky/non-deterministic manual order over time. **GAP** (P3, M).
- **QDrag.exec blocks event loop; tick/grace fire mid-drag** — a grace timer firing during the blocking drag → `_on_completed`→`refresh()` tears down the dragged card → drop targets a deleted card → RuntimeError/dropped event. Real reentrancy hazard. **GAP** (P2, M).

### Flow 11 — Prep-note / protocol link
- **Two non-atomic writes across stores** — `note_store.create()` writes the `.md` first (`note_store.py:160,207-208`), THEN `linked_note_ids.append` + `store.update` writes `todos.json` (`todos_view.py:411-413`). Crash/failed update between them → `.md` exists but unlinked = orphan note; a second click creates a second orphan. **GAP** (P2, M).
- **`note_store.create` itself fails** — `_write` raises `OSError`, propagates, no link appended, no todo write → clean (no orphan), silent click failure; retry works. **OK.**
- **Filename collision (6-char id prefix)** — ~1-in-16M; second `_write` could overwrite the first `.md`, leaving a dangling link. Extremely rare. **OK.**
- **Linked note trashed/purged externally then clicked** — `_linked_note` skips deleted/missing ids (`:389-397`), button reverts to "Prep note", a click creates a NEW note leaving the dead id in `linked_note_ids` permanently → unbounded dead-id growth across trash/recreate cycles. **GAP** (P3, S).
- **`open_note.emit`→switch tab while grace/edit pending** — grace timer is view-owned and keeps running on TodosView (`shell.py:459-463`); fires while user is on Notes tab → todo silently completes in background. Consistent with the user's tick but surprising. Mid-edit click auto-commits title first, note inherits committed title. **OK** (consistent; behavioral).
- **`protocol_template()` raises** — `_on_note_btn` aborts before create → no orphan, silent failure. **OK.**
- **NoteStore absent** — button not built (`:122`), `_linked_note` None (`:391`). Degrade-safe. **OK.**

### Cross-cutting
- **Language switch mid-flow** — parser auto-detects de+en per call; spoken line uses current `_lang`, cosmetic. **OK.**
- **External edit to `todos.json` while running** — invisible until restart, next `save()` silently clobbers (last-writer-wins, whole-file). No merge/conflict detection. **GAP** (P2, M) — mtime check before save.
- **Corrupt/partial `todos.json` at launch** — silently degrades to `[]` (`reload`, `:45-46`); all todos appear lost, no backup/recovery. Combined with non-atomic `save()` = an unrecoverable total-loss path. **GAP** (P1, M) — the keystone net.
- **No atomic write anywhere** — every save()-terminating flow (1,4,5,6,7,8,9,10, indirectly 11) shares the torn-write exposure. **GAP** (P1, S) — one fix covers them all.

---

## Area: notes

## Notes area — interruption audit (against the real code)

Read: `core/note_store.py`, `core/dedup.py`, `core/tagsync.py`, `core/semantic.py`, `core/phase2_stubs.py`, `core/rag.py`, `ui/notes_view.py`, `ui/modals.py`, `ui/ask_dialog.py`, `ui/duplicates_dialog.py`, `ui/tag_consolidation_dialog.py`, `ui/maintenance_dialog.py`, `ui/trash_view.py`, `ui/shell.py`.

**Verified facts that drive the verdicts:**
- `NoteStore._write` (note_store.py:207-211) has **no try/except**; `create/update/set_pinned/set_color/soft_delete/restore/merge/consolidate` all funnel through it. `write_text` is the only durability primitive (truncate-then-write).
- **No `sys.excepthook` / no `qInstallMessageHandler` anywhere in `serenity/`** (grep returned nothing). So an `OSError` in a Qt slot is an uncaught exception: PySide6 prints a traceback and aborts the slot — **no user-facing dialog, list not refreshed, dialog left open**. This is the mechanism behind every "stuck/silent" write gap below.
- `reindex` runs **only in `__init__`** (note_store.py:73,85). Filesystem is source of truth, so a divergent-on-disk note **wins on next restart**.
- `SemanticIndex.available` is set **once at construction** (phase2_stubs.py:267) from the embedder's `available`; `_ensure_store` can only ever flip it *False* (dim-0 case, line 288), never re-confirm a later model-load failure. `FastEmbedBackend._shared=False` (semantic.py:252) caches the failure and never retries. So a **load-fail-mid-session leaves `available` True** → silent keyword degrade with the Meaning pill still lit and no notice.
- All flows run on the single Qt main thread → the doc's "dict changed during iteration" worries (flow 4) **cannot occur**; confirmed OK.
- `merge_notes` (dedup.py:250-251) = `store.update(keep)` then `store.soft_delete(drop_id)` = **two separate `_write`s, no transaction, no try/except** at the call site (duplicates_dialog.py:248).
- `consolidate_tag` (tagsync.py:333-352) loops `store.all_active()` and `store.update(note)` per changed note = **N separate `_write`s, no transaction**; call site (tag_consolidation_dialog.py:217) has no try/except and **discards the return count**.
- `purge` (note_store.py:199-205) swallows `unlink` OSError then unconditionally pops `_notes` + deletes the row + commits.

---

### 1. Quick-note create (capture bar)
- **Empty-guard (modals.py:141-142):** both blank → `return`, `accept()` NOT called → dialog stays open, no feedback. **Today:** confirmed exactly as flagged. **GAP (P3)** — purely a feedback omission; data is safe.
- **Esc / close mid-compose:** `exec()` modal (shell.py:608), `reject()` discards title/body/tags, no draft. **Today:** confirmed, no draft persistence. **GAP (P3)** — acceptable for a quick-capture; minimal net would be a discard-confirm only when fields are dirty.
- **`create`→`_write` OSError (perm/disk-full/read-only vault):** uncaught → `saved.emit`/`accept` skipped, dialog stuck, **no note, no error**. **Today:** confirmed (no try/except anywhere on this path). **GAP (P2)**.
- **`settings.save()` after create raises:** note already on disk, exception propagates, `saved.emit`/`accept` skipped → dialog stuck, **note orphaned from the confirmation/refresh path**. **Today:** confirmed (modals.py:145-148 ordering). **GAP (P2)**.
- **Concurrent refresh after create:** `refresh` reads `all_active()` fresh → new card appears. **OK.**

### 2. Voice/parser-routed note create (no dialog)
- **Empty `cap.title`:** `create` defaults to `"Untitled"` (note_store.py:150). **OK.**
- **`_commit_capture` `create`→`_write` OSError (shell.py:598):** uncaught → mascot `voice_routed_note` line + `notes_view.refresh()` never run → **user thinks nothing happened, note may or may not be on disk**. **Today:** confirmed, no try/except in `_commit_capture`. **GAP (P2)** — same root cause as 1; one guard covers both.
- **Language toggle mid-flow:** only affects spoken line. **OK.**
- **Double refresh with flow 1:** wasted work only. **OK.**

### 3. Mic cheatsheet
- `dlg.show()` non-modal (shell.py:550), static content, no state. **OK.** No gaps.

### 4. Text search (default)
- **180ms debounce then teardown:** `_search_timer` is a child `QTimer(self)` (notes_view.py:351); Qt cancels child timers on widget delete. **OK.**
- **Async `deleteLater` double-refresh:** transient duplicate widgets pending GC, visually fine. **OK.**
- **`store.search` concurrency:** single-thread → no interleave. **OK.** No gaps.

### 5. Meaning search + degrade notice
- **First-use model load on UI thread (notes_view.py:446):** synchronous freeze / first-run download blocks the main thread. **Today:** confirmed — `refresh` calls `self.semantic.index(active)` inline; `index`→`embed_documents` loads the model. **GAP (P2)** — no loading state; freeze.
- **Model fails to load mid-session → silent keyword degrade with Meaning still lit, no notice:** **Today:** confirmed via the `available`-set-once + `_shared=False`-cached facts above. `_update_notice` (notes_view.py:432-434) keys on `_semantic_on()` = `available` which stays True. **GAP (P2)** — mis-signalled degrade.
- **Partial model download on forced close:** fastembed's cache, not handled here; out of app scope. **OK** (degrades on next load).
- **Empty query in meaning mode:** `notes = active`. **OK.**
- **Switch to Text mid-load:** queued behind the same-thread load. Same freeze as above; covered by the loading-state gap.

### 6. Expand/collapse card (+ lazy Related)
- **`_ensure_related` first expand model load (notes_view.py:292-293):** synchronous UI-thread freeze on first expand. **GAP (P2)** — same freeze class as flow 5.
- **`_related_built=True` set before the index/related call (notes_view.py:286):** if `related_notes` raised, the section is permanently empty for this card. **Today:** confirmed flag-set-first. But `related_notes` degrade is total (returns [] on any failure), so in practice it does not raise. **OK** (defensive, no realistic trigger).
- **Stale `self.note` snapshot anchor:** Related computed against live `notes_provider()` but anchored on stale note. Cosmetic. **OK** (doc agrees).
- **Concurrent soft-delete while expanded:** card persists until refresh; chip can open a trashed note. Same ghost-read class as flow 12 — see that gap.

### 7. Pin/unpin
- **`set_pinned`→`update`→`_write` OSError:** uncaught → pin not persisted, `changed.emit`/refresh skipped → **pin appears unchanged, silent failure**. **Today:** confirmed. **GAP (P2)** — same `_write` root cause; one guard at `_write` covers 1,2,7,9,10.
- **Double-click stale `note.pinned`:** possible lost toggle / no-op write, but `_write` always persists a consistent boolean → no corruption. **OK.**
- **Merged-away/purged note:** `get(id)` None → no write, `changed.emit` still refreshes. **OK.**

### 8. View raw .md
- **`read_raw` OSError fallback to `serialize(note)` (note_store.py:132-136):** shows the in-memory serialization, but the footer says "Filesystem is the source of truth - this is the note's markdown on disk." (notes_view.py:69). **Today:** confirmed mismatch — when the disk read fails the footer is misleading. **GAP (P3)** — cosmetic/labelling.
- Otherwise read-only. **OK.**

### 9. Soft-delete (Trash)
- **`soft_delete`→`update`→`_write` OSError:** `n.deleted=True` set in memory (note_store.py:184) BEFORE `_write`; on OSError `_notes`/index not updated but the **mutated object** `n` already has `deleted=True`, while the disk file still says `deleted: false`. `_on_delete` (notes_view.py:460-463) continues to `refresh()` + emit regardless. → list drops the card, but **next restart `reindex` reads `deleted: false` → note resurrects**. **Today:** confirmed memory/disk divergence + resurrection. **GAP (P1)** — silent un-delete on restart (data-state corruption).
- **Double-fire:** idempotent. **OK.**
- **No undo prompt on misclick:** delete is immediate, but recoverable via Trash. **OK** (trash-not-purge, by design).

### 10. Restore from Trash
- **`restore`→`update`→`_write` OSError:** mirror of flow 9 — in-memory `deleted=False`, disk still `deleted: true` → list drops it from Trash, **restart resurrects it INTO Trash**. **Today:** confirmed. **GAP (P1)** — same `_write` divergence root cause as 9.
- **Concurrent purge before restore:** `get(id)` None → no-op, `TrashView.refresh` (trash_view.py:109-111) drops the row. **OK** (silent but harmless).
- **Stale row after concurrent merge-into-trash:** next click no-ops. **OK.**

### 11. Purge (delete forever)
- **No confirm dialog (trash_view.py:49-53, `_purge_note`):** **Today:** confirmed — `pb.clicked.connect(self.purge.emit)` straight to `note_store.purge`, no `QMessageBox`. A misclick on the red button is irreversible. **GAP (P1)** — irreversible loss, no guard.
- **`unlink` OSError swallowed but `_notes`/row removed anyway (note_store.py:199-205):** orphaned `.md` on disk → **next restart `reindex` re-scans it → the "purged" note reappears**. **Today:** confirmed. **GAP (P1)** — silent resurrection of a forever-deleted note.
- **Crash mid-purge (file gone, row present):** next reindex rebuilds from disk → consistent. **OK.**
- **Dangling snapshot in another open dialog:** hits stale-guard / `get→None`. **OK.**

### 12. Related-note chip (chainable read)
- **Eager Related + `semantic.index` model load on UI thread (notes_view.py:121-122):** freeze inside a nested modal. **GAP (P2)** — same freeze class as 5/6.
- **Stale chip target (deleted/merged/purged since render):** opens `ReadNoteDialog` on the stale snapshot, body shown is a now-trashed note, **no "deleted" indication**. **Today:** confirmed — chip closes over `rel_note` captured at build (notes_view.py:127,300). **GAP (P3)** — ghost read; cosmetic, not corrupting (its own Related uses live provider).
- **Deep chaining nested `exec()` (notes_view.py:132-135), no depth limit:** UI annoyance only, reaped with parent. **OK.**

### 13. Open linked note from Todos
- **`open_note`→`refresh()`→`get(note.id) or note` (notes_view.py:471-472):** deleted/purged linked note → falls back to the passed-in snapshot → opens read dialog on a stale/deleted note, no warning. **Today:** confirmed `or note` fallback. **GAP (P3)** — same ghost-read class as 12; one indicator covers both.
- **`switch_tab` mid-flow:** harmless. **OK.**

### 14. Ask-Your-Vault (RAG)
- **Empty question (ask_dialog.py:141-143):** `return`, answer area keeps prior text, no feedback. **Today:** confirmed. **GAP (P3)**.
- **`semantic.index` + `llm.generate` block the UI thread, Ask has no disabled/loading state (ask_dialog.py:93-96, 134-155):** long inference = app looks hung; double-click Ask runs `_ask` twice (serialized, not corrupting). **Today:** confirmed no busy state. **GAP (P2)** — freeze + double-fire.
- **`llm.generate` wrapped try/except in `answer_question` (rag.py:237-239), and `WarmCache.ask` routes through it:** inference error degrades to sources-only. **OK** — confirmed protected on both paths.
- **Citations resolved against the ask-time `notes` snapshot (ask_dialog.py:160-161):** internally consistent even if vault drifts. **OK.** (clicked-chip-now-gone handled in flow 15.)
- **Degrade line keys on `self.llm is None or not available` at render (ask_dialog.py:174-175):** an LLM that loaded-then-failed mid-session has `available` stale-True → degrade line hidden though no answer came back. **Today:** confirmed same pattern as the embedder. **GAP (P3)** — mis-signalled, low frequency.
- **Language mismatch:** quality issue, not a failure. **OK.**

### 15. Open cited source note
- **Stale citation snapshot (ask_dialog.py:195,201):** deleted/merged/purged-since → ghost read, no indication. **Today:** confirmed. **GAP (P3)** — same ghost-read class as 12/13.
- Model load inside nested dialog; app-close reaps cleanly. **OK.**

### 16. Find duplicates — scan + view
- **`semantic.index` before the dialog opens, on UI thread (notes_view.py:498-500):** button click feels hung with no feedback. **GAP (P2)** — freeze class.
- **O(n²) detection synchronously in `__init__` (dedup.py:138-205 via duplicates_dialog.py:91):** large vault blocks dialog construction; no input cap (only 30-row output cap). **Today:** confirmed. **GAP (P3)** — only bites very large vaults; effort to fix is real, frequency low.
- **Footnote keys on `idx is not None` (duplicates_dialog.py:128), not on whether semantic actually produced pairs:** if semantic path degraded-to-tokens internally (dedup.py:97), footnote still says "meaning + text". **Today:** confirmed mislabel. **GAP (P3)** — cosmetic.
- **Rows capture live Note `a,b` at open:** concurrent delete → stale row, handled by the merge stale-guard (flow 17). **OK.**
- **`exec()` close → `NotesView.refresh()` (notes_view.py:505).** **OK.**

### 17. Merge a duplicate pair
- **Stale guard re-gets both ids, checks None/deleted (duplicates_dialog.py:229-235):** **OK** — good coverage for the already-merged case.
- **Guard does NOT check content changed since detection:** merge appends a now-different body; "% similar" hint stale. Still a valid union, not corruption. **OK** (doc agrees) — acceptable.
- **Confirm default Cancel (duplicates_dialog.py:244), Esc/click-away/app-kill before Yes = no merge.** **OK.**
- **`merge_notes` not atomic across the two notes (dedup.py:250-251), no try/except at call site (duplicates_dialog.py:248):** `update(keep)` succeeds then `soft_delete(drop)` fails/crashes → **keep holds merged body+tags AND drop is still ACTIVE = silent content duplication, drop never trashed**. Re-running re-suggests them, and the stale guard would NOT catch it (drop not deleted) → a second merge **double-appends drop's body**. **Today:** confirmed — worst data-state in the area. **GAP (P1)**.
- **Sibling pruning never runs if step 4 raised (duplicates_dialog.py:253-258):** stale rows remain clickable → the double-append path above. **GAP (P1)** — same root cause; one guard (try/except + abort-on-partial) covers both.

### 18. Toggle "Keep the other note instead"
- Pure UI state read at merge time (duplicates_dialog.py:223). Stale-guard at 17 still fires on whichever id is the drop. **OK.** No gaps.

### 19. Dismiss a duplicate pair
- Session-only; last-row → empty-state toggle (maintenance_dialog.py:49-51). Re-surfaces next scan by design. **OK.** No gaps.

### 20. Tidy tags — scan + view
- **`suggest_tag_groups` O(n²) over the distinct tag set, model-free (tagsync.py:262-295):** tiny, no freeze. `getattr(settings,"tags",[])` tolerates None (tag_consolidation_dialog.py:91). **OK.**
- **Rows stash `group` + editable combo; `note_count`/members computed at open:** stale if the vault changes before Apply — see flow 21. **OK** here (read-only).
- **Empty state:** clean. **OK.** No gaps in the read path.

### 21. Apply a tag consolidation (irreversible)
- **No undo; confirm is the only guard (tag_consolidation_dialog.py:205-215).** Confirm present, default Cancel. **OK** (by design).
- **Blank canonical → info box, return (tag_consolidation_dialog.py:191-193).** **OK.**
- **Esc/click-away/app-kill before Yes = no write.** **OK.**
- **`consolidate_tag` N separate `_write`s, no transaction, no try/except at call site (tagsync.py:349-352; tag_consolidation_dialog.py:217):** crash/OSError mid-loop → **partially-applied consolidation** (some notes renamed, some not), no undo → mixed vault. OSError → uncaught → row not removed, `applied.emit` not fired → **dialog stuck, vault half-rewritten, no message**. **Today:** confirmed. **GAP (P1/P2)** — partial bulk rewrite is the data risk (P1), the stuck dialog is the UX symptom (P2).
- **`settings.save()` after the note loop raises (tagsync.py:358-364):** notes already rewritten, arsenal stale → next session re-offers; `consolidate_tag` is idempotent (only writes changed notes) so re-apply is a safe no-op. **OK** — acceptably idempotent, noisy at worst.
- **Stale `note_count` in the confirm (tag_consolidation_dialog.py:209) vs the real count `consolidate_tag` returns and the UI discards (line 217):** confirm number can be wrong; no "N changed" feedback. **Today:** confirmed return value discarded. **GAP (P3)** — feedback accuracy.
- **Concurrent second dialog:** Apply runs against live notes (correct, idempotent); other dialog's rows stale (no stale-guard like duplicates). Idempotent no-op at worst. **OK.**

### 22. Edit the canonical tag before applying
- **Free-text combo (tag_consolidation_dialog.py:147):** typing a canonical that collides with an unrelated existing tag folds the group into it — **merges two distinct tag namespaces, no warning**; confirm only counts the group's notes, not notes already using the typed canonical elsewhere. **Today:** confirmed `consolidate_tag` maps any matching variant to the canonical regardless of prior usage. **GAP (P3)** — niche, irreversible-but-user-typed; the bigger P1 is the partial-write in 21.
- Whitespace-only → blank guard; trailing/leading → `.strip()` (tagsync.py:322); case-only variant → `canon_lower` handles. **OK.**

### 23. Dismiss a tag group
- Session-only; last-row empty-state toggle; re-scan resurfaces. **OK.** No gaps.

### 24. Dialogs refresh the list on dismiss-only close
- **Find-duplicates / Tidy-tags call `NotesView.refresh()` unconditionally after `exec()` (notes_view.py:505,517):** if a merge/consolidation half-wrote (flows 17/21), the post-close refresh renders the half-mutated store as truth with no flag. **Today:** confirmed — but this is a *symptom* of the 17/21 partial-write GAPs, not a separate defect; once those are guarded the store is never half-mutated. **OK** (no independent net needed).
- **Ask dialog has no post-close refresh** (never mutates notes). **OK.**
- **App-close instead of dialog-close:** the post-`exec` refresh never runs (window tearing down). **OK.**

---

## Summary of the root causes
1. **`_write` has no try/except + no global excepthook** → every write-OSError is silent and can leave memory/disk diverged. Drives gaps in 1, 2, 7, 9, 10. A single guarded-write (catch OSError, do NOT mutate `_notes`/the in-memory object, re-raise a typed error the UI can catch → one error toast) fixes the whole family. **P1 for 9/10 (resurrection on restart), P2 for 1/2/7.**
2. **Multi-write mutations are non-atomic + uncaught** → merge (17) and consolidate (21) can half-apply, the merge case silently duplicating content. **P1.**
3. **Purge has no confirm + swallows unlink errors while removing the row** → irreversible misclick + silent resurrection. **P1.**
4. **`available` flag is set once at construction and never re-checked after a mid-session model-load failure** → silent keyword degrade with the Meaning pill lit / RAG degrade line hidden. **P2 (search), P3 (RAG line).**
5. **Synchronous model load + heavy scan on the UI thread, no loading/busy state** → freezes in 5, 6, 12, 14, 16. **P2.**
6. **Snapshots in chips/rows + reindex-only-on-open** → ghost reads (12, 13, 15) and a misleading raw-file footer (8). **P3.**

---

## Area: capture

## Capture & Voice — Interruption audit (verified against code)

### Confirmed cross-cutting facts
- **Non-atomic store writes.** `TodoStore.save` = `self.path.write_text(json.dumps(...))` (`todo_store.py:58-61`, with `mkdir` first). `NoteStore._write` = `Path(note.path).write_text(serialize(note))` then `self._db.commit()` (`note_store.py:207-211`). Both truncate-then-write, no temp+`os.replace`, no fsync, no backup. **GAP confirmed.**
- **`_pending`/`_pending_slot` never initialized in `__init__`** (grep: only assigned at `shell.py:557,561,583`, read via `getattr(...,None)` at `568-569`) and **never cleared** after commit (`_commit_capture` ends at `602`, no reset). **GAP confirmed.**
- **`says` hides the answer box.** `mascot.says → bubble.set_text` (`mascot_stage.py:283-284`) → `set_text` calls `self.answer.hide()` (`mascot_stage.py:106`). Any voice line from any flow wipes a pending slot box while `_pending` survives. **GAP confirmed.**
- **Answer box has only `returnPressed`** (`mascot_stage.py:90`); no Esc/cancel/focus-out; `_send` drops empty input silently (`mascot_stage.py:117-121`). **GAP confirmed.**
- **`recording` is a CaptureBar-only bool** (`capture_bar.py:32,75-78`); `hide_to_tray`/`set_window_mode`/`closeEvent` never reset it (read `shell.py:716,728-754,784-790`). **GAP confirmed.**

---

### Flow 1 — Mic toggle ON (cheatsheet + listening line) — `shell.py:545-550`
- **Cheatsheet orphan/stacking** — `dlg = CheatsheetDialog(self); dlg.show()` (`549-550`), no handle kept. Confirmed: no `_cheatsheet` field anywhere. Every ON spawns a new modeless dialog; mode-switch/hide never closes it. **GAP (P3).**
- **No idempotency on `recording`** — `_toggle_mic` is a raw NOT (`capture_bar.py:76`), no guard. Double-fire flips ON→OFF→ON, the OFF re-enters `_demo_capture` and overwrites `_pending`. **GAP** — covered by the shared `_pending` guard (Flow 2/3).
- **`listening_start` via `says`** wipes a pending box (`548`). **GAP** — covered by the shared `says`-guard net.
- **Recording stays ON across tray-hide** — confirmed no reset. **GAP (P3)** cosmetic-only (Phase-1 demo has no real audio loop), folded into the recording-reset net.

### Flow 2 — Mic toggle OFF (canned demo) — `shell.py:551-564`
- **Hard-coded utterance, no failure branch** — always `parse_capture("Erinnerung Zahnarzt anrufen")` (`553,556`); `didnt_catch` unreachable. Phase-1 stub by design; **OK for now** (real STT not shell-wired — see Flow 9). Note for wiring.
- **`self._pending = cap` overwrites unconditionally** (`557`) — drops a half-filled prior capture. **GAP confirmed (P2).**
- **All-slots-filled path commits with no confirm** (`563-564`), and **confidence `<0.55` is computed but never checked** by the shell (`parser.py:225` vs shell only reads `cap.missing`). Confirmed. **GAP (P2).**

### Flow 3 — Slot-filling ask — `shell.py:558-562,580-584`; `mascot_stage.py:288-291`
- **No Esc/cancel** in the answer box (`mascot_stage.py:87-90`). Confirmed. **GAP (P2).**
- **Any `says`/`set_state` hides the box, leaves `_pending` set** → unreachable/abandoned capture. Confirmed. **GAP (P2)** — the central hazard.
- **Concurrent mic-OFF overwrites `_pending` mid-ask.** Confirmed. **GAP** — covered by `_pending` guard.
- **Hide-to-tray mid-ask** abandons silently (box hidden state not restored, `_pending` in memory only). Confirmed. **GAP (P2)** — covered by `_pending` clear-on-hide / box-restore net.

### Flow 4 — User answers a slot — `mascot_stage.py:117-121`; `shell.py:566-586`
- **Empty answer silently dropped** — `_send` strips, hides, emits only if truthy (`118-121`); box gone, `_pending` set, no re-prompt. Confirmed. **GAP (P2).**
- **Unparseable date → endless same re-ask** — `cap.date=parse_natural_date(answer)`; None ⇒ "date" stays in `missing` ⇒ identical prompt (`573-576,580-584`). No attempt counter / skip. Confirmed. **GAP (P2).**
- **Early-return on falsy `_pending` (`570-571`) does not clear `_pending_slot`**; no guard that slot matches the live capture. Confirmed. **GAP** — folded into `_pending` lifecycle net.
- **Title branch: no validation/length cap** (`578`) — accepts any string; flows to store + note filename slug (`note_store.py:158`). Confirmed; non-fatal. **GAP (P3).**

### Flow 5 — Commit routed capture — `shell.py:588-602`
- **Todo branch non-atomic write** (`591` → `todo_store.save` 58-61) — crash/disk-full truncates the whole `todos.json`. Confirmed. **GAP (P1).**
- **Note branch two-phase write** (`598` → `_write` 207-211) — file write then `commit()`; crash between desyncs file ↔ sqlite index. Confirmed. **GAP (P1).**
- **Parsed tags dropped from the note** — `note_store.create(cap.title, body=cap.raw)` passes **no `tags=`** (`598`) yet `cap.tags` go to settings (`601-602`). The `create` signature accepts `tags=` (`note_store.py:143`). Silent data drop. **GAP (P2) confirmed.**
- **`_pending` not cleared after commit** (ends at `602`) → stray `answered` can re-mutate/double-commit. Confirmed. **GAP (P2).**
- **Commit voice line via `says`** hides any unrelated pending box (`594,600`). Confirmed. **GAP** — covered by `says`-guard.
- **Settings save after store write** (`601-602`) — if store ok but settings save raises, tags out of sync. Minor. **GAP (P3).**

### Flow 6 — Quick note modal — `shell.py:604-608`; `modals.py:66-148`
- **Esc/reject discards unsaved title/body/tags** (QDialog default; `dlg.exec()` at `608`). No discard guard. **GAP (P2).**
- **Empty title AND empty body → silent no-op** (`modals.py:141-142`) — modal stays open, no feedback. **GAP (P3).**
- **`note_store.create` raise propagates uncaught out of `_save`** (`143`) — OSError (read-only FS / permission / vault dir removed at runtime) bubbles to Qt, no user error. `notes_dir` IS created in `__init__` (`note_store.py:66-67`) so missing-dir is unlikely unless deleted post-launch. **GAP (P2)** narrower than annotation (mkdir already in ctor).
- **`saved.emit` then `accept()`** order fine (`147-148`); `_on_note_saved` `says` hides pending box (`shell.py:610-612`). **GAP** — covered by `says`-guard.
- Concurrent same-note edit / cross-process: single-instance enforced; always `create` (new id). **OK.**

### Flow 7 — Quick todo modal — `shell.py:614-618`; `modals.py:151-197`
- **Esc/reject discards typed title+when silently.** **GAP (P3).**
- **Empty title → silent no-op** (`185-187`), modal stays open, no feedback. **GAP (P3).**
- **Title fed to parser → date/tag bleed** — `combined=f"{title} {when}"` (`189`), but stored todo uses **raw `title`** (`191`) while `due=cap.date` is taken from the combined parse → "Call Monday team" stores literal title AND a Monday due. Confirmed silent wrong-data. **GAP (P3).**
- **`todo_store.add` raise propagates uncaught** (`193`) — `save()` does `mkdir` (`todo_store.py:59`) so missing-dir handled; permission/disk-full/read-only still bubbles to Qt, todo not added, no user error. **GAP (P2).**
- **`added.emit` then `accept()`; `_on_quick_todo` `says`** hides pending box (`shell.py:620-623`). **GAP** — covered by `says`-guard.

### Flow 8 — Deterministic parse — `parser.py:181-235`
- **Empty/whitespace → `missing=["title"]`** (`188-190`). Defensive; callers guard. **OK.**
- **`parse_natural_date` can raise/return surprising value** (`86-96`, no try/except). An exotic input that makes dateparser raise propagates into `_demo_capture`/`_on_slot_answer`/`_save`. In the slot-answer date branch (`shell.py:573-574`) this crashes the handler with the box already hidden by `_send` and `_pending` set → inconsistent. Confirmed. **GAP (P2).**
- **Confidence `<0.55` computed but never gated by shell** (`225`). Confirmed. **GAP (P2)** — same net as Flow 2/5 no-confirm.
- No store writes here. **OK** otherwise.

### Flow 9 — STT → capture seam (tested, not shell-wired) — `stt.py:185-202`
- **Dep/model absent → real transcriber `""` → `transcribe_to_capture` returns `None`** (`198-201`). Graceful by design. **OK** for the seam; **GAP-on-future-wiring:** caller must (a) surface "didn't catch" feedback and (b) delete the temp audio on the None path. Not wired today → **note, not an active GAP.**
- **Stub keys on file stem → garbage title** for empty/garbage stem (`stt.py:64-94`). Stub-only, never in real path. **OK.**
- **LLM router engine present but hangs has no timeout** (`phase2_stubs.py` `_ask_llm`) — would freeze the Qt main thread once shell-wired. Not wired today. **Note, not an active GAP.**
- **Confidence bumped ≥0.75 on valid merge** could bypass a future confidence gate. Design note. **OK** for now.
- Once wired, the seam inherits all Flow 2-5 `_pending`/no-confirm/non-atomic hazards. Already captured above.

---

### Summary of confirmed GAPs (deduped — shared nets fix many flows at once)
1. **Non-atomic store writes** (P1) — `todo_store.save`, `note_store._write`.
2. **`_pending` lifecycle** (P2) — never init / never cleared / overwritten unconditionally; one net (init in `__init__`, clear after commit, guard overwrite while a slot is pending) fixes Flows 1/2/3/4/5.
3. **`says` wipes the pending answer box** (P2) — guard in `SpeechBubble.set_text` (skip hide while answer visible/pending) or in `mascot.says`; fixes Flows 3/4/5/6/7.
4. **No Esc/cancel + endless date retry** (P2) — Esc-to-cancel in `SpeechBubble`, attempt cap on date slot in `_on_slot_answer`.
5. **Silent drops with no feedback** (P2/P3) — empty slot answer, empty-modal save, tags dropped from notes (one-line `tags=` fix), no-confirm/low-confidence commit.
6. **Uncaught store/parse exceptions in modals + slot-answer** (P2) — wrap `create`/`add`/`parse_natural_date` calls.

---

## Area: activity

## Area: activity — Mascot & activity tracking — AUDIT (interruption -> current handling -> OK/GAP -> minimal safety net)

### Cross-cutting facts (verified against code)

- **Non-atomic write — CONFIRMED, codebase-wide.** `ActivityStore.save` (`activity_store.py:91`) is a bare `self.path.write_text(...)`. `grep` over `serenity/core/` shows NO `os.replace`/temp-file/fsync anywhere — `todo_store.py:61`, `settings.py:113`, `note_store.py:208`, `voice_clones.py:118` are all the same plain `write_text`. A crash/power-loss/kill mid-write can truncate `activity.json`. `reload` (`activity_store.py:62-65`) catches only `JSONDecodeError`/`OSError` -> `data={}` -> **entire log + `last_board_open` silently reset to empty.** Real, P1.
- **save() has no try/except — CONFIRMED.** `start`/`stop` (`activity_store.py:102-110`) and `set_last_board_open` (`activity_store.py:116-118`) call `save` unguarded; callers `_on_activity` (`shell.py:432-447`), `_maybe_auto_open_board` (`shell.py:473`), `_quit` (`shell.py:793-794`) do NOT wrap it. A raising write (disk full / read-only vault / disconnected network drive) propagates into the Qt slot. Real.
- **No Esc handler — CONFIRMED.** `MascotStage` defines only `mousePressEvent` (`mascot_stage.py:223`); no `keyPressEvent`. The docstring "Esc / re-click closes" (`mascot_stage.py:9`) is **false.** Doc/behavior mismatch.
- **`_on_pick` optimistic-close-before-persist — CONFIRMED.** `_on_pick` (`mascot_stage.py:254-259`) sets `current_activity`, `close_selector()`, `set_state()`, then `activity_changed.emit()` — pose/UI commit before the shell persists.
- **Two `MascotStage` instances share one `ActivityStore` but NOT pose state — CONFIRMED.** Full dock (`shell.py:340`) + mini (`mini_window.py:106`) each have their own `current_activity`/`current_state`/`PoseSelector._last` and their own `_tts`/`_cache`/`_player`. No sync on mode change.
- **Daemon TTS/prewarm threads fire-and-forget — CONFIRMED.** `_speak` (`mascot_stage.py:318`) and `_kick_prewarm` (`mascot_stage.py:359`) spawn `daemon=True` threads; `_quit` (`shell.py:792-801`) never joins/cancels them.

---

### 1. Open the activity selector — AUDIT
- **Concurrent `says()` retargets layout mid-open.** All on the Qt main thread; a `says()` and `open_selector` cannot truly interleave (the only cross-thread work is `_speak`'s synth, which never touches layout — `_play` only sets `self._player`). Worst case is two sequential `_relayout` passes -> harmless re-arc. **OK.**
- **Resize/mode-switch mid-open while hidden to tray.** `set_window_mode(MODE_HIDDEN)` just `self.hide()`s (`shell.py:744`); `_selector_open`/`_bubbles` persist, so on re-show the stale arc is intact (same widgets, no leak). Cosmetic-only. **OK.**
- **Double-open guard.** `open_selector` early-returns if open (`mascot_stage.py:238-239`); fast double-click toggles open-then-closed (flash). Cosmetic. **OK.**
- **Orphaned `_bubbles` if stage destroyed while open.** Bubbles are children of the stage; they die with the parent. Not a true leak. **OK.**

### 2. Close selector by re-clicking avatar — AUDIT
- **Queued `clicked` race (bubble click + avatar re-click same instant).** `close_selector` calls `b.deleteLater()` (`mascot_stage.py:250`) which is deferred; a `clicked` already queued for that bubble can still invoke `_on_pick` after close -> unintended activity start + persist. Real but very low probability. **GAP (P3).** Minimal net: in `close_selector`, before `deleteLater`, `b.clicked.disconnect()` and/or `b.setEnabled(False)` so a queued click cannot reach `_on_pick`.

### 3. Close by clicking empty stage — AUDIT
- **Same queued-`clicked` race** as flow 2 — same single GAP (covered once below).
- **Esc does not close — CONFIRMED.** No `keyPressEvent`; pressing Esc (the documented gesture) is silently ignored, selector stays open. **GAP (P3).** Minimal net: either fix the docstring (`mascot_stage.py:9`) to "re-click / click-away closes", OR add a 3-line `keyPressEvent` that calls `close_selector()` on `Qt.Key_Escape`. Doc fix is the smaller of the two.
- **Mini title-strip empty-space = drag, not close.** Confirmed `MiniWindow.mousePressEvent` (`mini_window.py:138-141`) only starts a drag on the strip; the embedded stage handles its own region. **OK.**

### 4. Pick a real activity (start/replace span) — AUDIT
- **Optimistic UI before persist — CONFIRMED GAP (P2).** If `activity_store.start()` raises (`shell.py:440`), pose already swapped + selector closed, but `activity_chip.show_running`/focus branch/`mascot.says` never run, and `ActivityLog.start` already mutated `_entries` in memory (`activity.py:144-147`) while disk keeps the old state -> silent memory/disk divergence + mascot shows new pose with no chip/voice. Minimal net: wrap the `start`/`stop` calls in `_on_activity` (`shell.py:436-441`) in `try/except OSError` that, on failure, surfaces a one-line mascot notice (e.g. `voice` "could not save" line / `says(...)`) so the divergence is not silent. Do NOT add per-store retry logic.
- **Close-then-append within one `start` call.** Verified atomic in memory (single `ActivityLog.start` does `stop`+append, `activity.py:142-147`) before one `save`. A crash *during* the single `save` corrupts the whole file (cross-cutting atomic-write GAP, P1, below). The in-memory transactionality itself is **OK**; the file write is the GAP.
- **Chip keeps ticking a finished span (`tick` never re-checks `end`).** Confirmed `tick` only guards `self._entry is None` (`activity_chip.py:104`); but `seconds()` uses `finish = self.end or now` (`activity.py:51`) so a closed span **freezes** at its final value rather than counting up. The chip just stays visible showing the frozen value until `clear()`/`show_running`. Stale indicator, not a runaway counter. **GAP (P3).** Minimal net: in `ActivityChip.tick` (`activity_chip.py:103-106`), if `self._entry.end is not None` call `self.clear()` and return — self-heals a stale chip on the next 1s tick.
- **Focus reset on re-pick.** Confirmed `_on_activity` calls `focus_widget.start()` every time Focus is picked (`shell.py:444` -> `focus_widget.py:103-109` -> `pomo.start(now)`), silently discarding an in-progress block; picking non-Focus -> `set_active(False)` -> `stop()`. Lost progress with no warning. **GAP (P3).** Minimal net: in `FocusWidget.start` (`focus_widget.py:103`), if `self.pomo.phase != Phase.IDLE` just `self.show()` + `_render()` and DON'T re-`start` (resume the existing session instead of resetting). Small, contained to the widget.
- **TTS thread plays old voice after a settings race.** Engine snapshotted as local `engine` (`mascot_stage.py:308`) before `refresh_tts` swaps `self._tts`. Cosmetic (worst case one line in the old voice, or a swallowed exception in the daemon). **OK** (acceptable, by design the thread is fire-and-forget).
- **Concurrent two-mascot pick -> 0-second orphan span.** Both stages can be alive and both wired to `_on_activity` (`shell.py:363,759`); two queued `activity_changed` -> two `start` -> first new span immediately closed by second (`activity.py:144`) -> a 0-second span persisted. Minor data noise, harmless to aggregation (`aggregate_seconds` skips `secs<=0`, `activity.py:93`). **OK.**

### 5. Pick "Idle" — stop tracking — AUDIT
- **`stop` save raises -> chip not cleared.** `_on_activity` (`shell.py:437-438`): if `activity_store.stop()` raises, `activity_chip.clear()` never runs -> chip keeps showing the now-closed span. Same root as flow 4. Covered by the flow-4 `try/except` net (P2).
- **Idle when nothing running still calls `save`.** Confirmed `ActivityLog.stop` returns None harmlessly (`activity.py:149-155`) but `ActivityStore.stop` ALWAYS `save`s (`activity_store.py:108-109`) -> a redundant full-file rewrite (extra corruption window). **GAP (P3).** Minimal net: in `ActivityStore.stop` (`activity_store.py:107-109`), only `save()` when `entry is not None`. One-line guard, removes a needless write window.

### 6. Pick activity from the Mini-window mascot — AUDIT
- **Mode-switch -> full dock shows IDLE pose while chip shows running — CONFIRMED GAP (P2).** Picking on mini calls only the mini mascot's `set_state`; the full mascot's `current_state`/pose are untouched (separate instances, verified). The full dock's `activity_chip` IS correct (shared store, restored at `set_window_mode`? — no: chip only updated in `_on_activity`, which DID run). So chip = running, full mascot pose = idle. Pose/tracking divergence between the two mascots. Minimal net: in `set_window_mode(MODE_FULL)` (`shell.py:751-754`), after `show_dock()`, sync the full mascot pose from the running span — e.g. `r = self.activity_store.running(); self.mascot.set_state(<state for r.category> or "idle", silent=True)`. Small; reuses the `ACTIVITIES` label->state map.
- **Mini has no chip — CONFIRMED.** No `ActivityChip` in `MiniWindow` (only the avatar + one todo card). In Mini mode the user has no running-elapsed cue and can forget a span is running. Break-time gating still treats it correctly as work. **GAP (P3), polish.** Minimal net: optional tiny "tracking <cat>" label on the mini strip driven from `activity_store.running()` in `refresh_todo`. Low priority — defer; arguably by-design (Mini is intentionally minimal).
- **`activity_changed` wired once.** Confirmed `_ensure_mini` connects once (`shell.py:759`); no double-wire. **OK.**

### 7. Restore a span open at last quit — AUDIT
- **Silent drop of bad rows + whole-file reset.** Confirmed `_parse` returns None on bad `start` -> row `continue`d (`activity_store.py:70-72`); `JSONDecodeError` -> `data={}` (`activity_store.py:64-65`). Partial/total silent history loss at launch. Root cause is the non-atomic write (P1 below) plus silent drop. The silent **per-row** drop itself: **GAP (P3)** — minimal net is a `print`/log to stderr when a row is dropped so corruption is at least observable (no recovery logic). Low priority vs. fixing the write.
- **Corrupt `end` resurrects a finished span as open — CONFIRMED GAP (P2).** `end` is `_parse`d independently (`activity_store.py:76`); a garbled `end` -> `end=None` -> `running()` returns it (`activity.py:157-162`). The chip ticks from an old `start` (huge elapsed), AND `_derive_break_state` (`shell.py:534-538`) hard-overrides `on_break=False` forever -> **HEAVY maintenance silently disabled for the whole process.** Stuck, hard to notice. Minimal net: in `ActivityStore.reload` (`activity_store.py:70-77`), when a row has a `start` but a present-yet-unparseable `end`, treat it as a closed span by clamping `end = start` (a 0-second span) rather than leaving it open. Localizes the fix to the parser; prevents the phantom-open-span cascade.
- **Clock skew on restored `start`.** `seconds()` clamps to >=0 (`activity.py:50-52`); chip shows 0:00. Benign by design. **OK.**
- **Concurrent first save at startup.** Single-threaded at launch; `_maybe_auto_open_board` (`shell.py:239`) and the read-only restore can't conflict. **OK.**

### 8. Running-activity chip lifecycle — AUDIT
- **`tick` never re-validates `end`.** Same as flow 4 — verified the span FREEZES (not runs away) but the chip stays visible as "tracking". Single GAP (P3), net in flow 4.
- **Timer survives hide-to-tray/Mini.** Confirmed `clear()` is NOT called on hide; `_timer` keeps firing 1/s doing `setText` on an invisible label (`activity_chip.py:103-106`) — wasted wakeups, battery only, no data issue. **GAP (P3), polish.** Minimal net: in `Shell.hide_to_tray`/`set_window_mode(MODE_HIDDEN|MODE_MINI)`, the full dock is hidden — could pause the chip timer, but the chip has no public pause and it self-corrects; defer. Lower priority than the others.
- **`show_running(None)/finished/Idle` all funnel to `clear`.** Confirmed robust (`activity_chip.py:85-87`). **OK.**

### 9. Weekly Board auto-open + digest read-aloud — AUDIT
- **Latch persists via raise-prone save -> re-fires every minute — CONFIRMED GAP (P2).** `set_last_board_open` -> `save` (`activity_store.py:116-118`); if it raises, the exception leaves `_maybe_auto_open_board` (`shell.py:473`, unguarded) AND the latch is never set -> `should_auto_open_board` stays True -> the 60s `_board_timer` re-fires the whole 17-18h window: repeated board pop + repeated digest read-aloud + repeated failing save. Minimal net: wrap the `set_last_board_open` call in `_maybe_auto_open_board` (`shell.py:473`) in `try/except OSError: return` (skip this cycle on a write failure) so a bad disk does not turn into a per-minute pop/voice storm.
- **Latch set BEFORE board shown.** Confirmed `set_last_board_open` (`shell.py:473`) precedes the show/switch (`shell.py:477-478`); a crash between them persists the latch with the user never seeing the board -> misses until next Friday. Silent, rare. **GAP (P3).** Minimal net: move `set_last_board_open(now)` to AFTER `switch_tab("board")` (`shell.py:478`) so the latch reflects an actually-shown board. Tiny reorder.
- **Digest = multi-second main-thread LLM inference.** Confirmed `refresh()` calls `generate_digest(board, self.llm)` synchronously (`weekly_board_view.py:140`) on the Qt thread; the auto-open path freezes the UI for seconds with a real `LlamaCppLLM`. The signature cache (`weekly_board_view.py:138-139`) only helps on repeat opens. This is a known, documented perf tradeoff (the class docstring + the cache comment call it out) and degrades fine without an LLM. **OK** (by design / already documented; moving inference off-thread is the noted future hardening, out of scope here).
- **`generate_digest` raises (OOM/corrupt GGUF) -> unguarded into the timer slot.** Confirmed `refresh()` has no try/except around `generate_digest`; it propagates through `switch_tab("board")` into `_maybe_auto_open_board` into the `_board_timer` slot. **GAP (P2).** Minimal net: wrap the `generate_digest` call in `WeeklyBoardView.refresh` (`weekly_board_view.py:139-141`) in `try/except Exception:` that falls back to the deterministic board hint (the same string the degrade path uses) — keeps `digest_text()` non-empty and the board build from throwing into the event loop.
- **Auto-open forces MODE_FULL and persists it — CONFIRMED.** `set_window_mode(MODE_FULL)` (`shell.py:475-476`) persists `window_mode=full` (`shell.py:735-737`); a user who deliberately ran Hidden/Mini is silently switched to Full permanently even after dismissing. Surprising. **GAP (P3).** Minimal net: in the auto-open path call `set_window_mode(MODE_FULL, persist=False)` (`shell.py:476`) so the temporary review pop does NOT overwrite the user's chosen mode.
- **Friday/clock-jump edge.** `should_auto_open_board` reads wall-clock each tick (`shell.py:470`); same-day latch keys on `date()` (`activity.py:124`). A clock jump can skip/double-eligible. Rare, benign (worst case one extra pop). **OK** (acceptable edge; guarding clock jumps is out of scope).

### 10. Mascot speaks a line (`says`) — AUDIT
- **Daemon synth thread outlives quit -> half-written cache wav.** Confirmed `_speak` daemon (`mascot_stage.py:318`) runs `synth_cached`; on `_quit` it is abandoned mid-write. Cache integrity is `TtsCache`'s responsibility (out of this area's scope). Within this area: the thread is just abandoned. **GAP (P3)** but the fix belongs to `TtsCache` atomicity — note it, don't fix here. Lowest priority.
- **Engine snapshot vs `refresh_tts` race.** Confirmed `engine` local snapshot (`mascot_stage.py:308`); `refresh_tts` does `self._tts.stop()` + swap (`mascot_stage.py:365-366`). A daemon between snapshot and `engine.speak` may use a stopped engine; any exception in `_run` is swallowed (no `try`, daemon just dies). Worst case = one dropped/old-voice line. **OK** (acceptable for fire-and-forget voice).
- **`_player`/`_audio_out` overwritten -> first line clipped.** Confirmed `_play` reassigns both (`mascot_stage.py:327-328`); two rapid `says()` GC the first player mid-sentence. Audible truncation only. **OK** (cosmetic; per-mascot, no data).
- **Empty/None text.** Confirmed `_speak` no-ops on empty (`mascot_stage.py:302`); empty bubble shows silently. **OK.**
- **`says` after mute leaks one line.** Confirmed a `says` already past the `tts_enabled` check still plays. One line. **OK** (negligible).

### 11. Mascot pose swap (`set_state`) — AUDIT
- **Missing/corrupt pose file -> blank avatar, no guard — CONFIRMED GAP (P2).** `_play_pose` (`mascot_stage.py:275-281`) does `QMovie(path)` + `start()` with NO existence/validity check; a missing/corrupt webp (incomplete install, packaging drop, wrong `poses_dir()`) silently blanks the avatar with no fallback. Minimal net: in `_play_pose`, guard with `QMovie.isValid()` (or `os.path.exists(path)`); if invalid, keep the previous `self._movie` (don't swap to a broken one) so the avatar never goes blank. Small, contained.
- **Empty/invalid custom `state_map` -> stuck pose.** Confirmed `pick(state)` returns None for unknown/empty (`poses.py:84-85`); `set_state` falls back to `pick("idle")` (`mascot_stage.py:269-270`), but a custom map with `"idle":[]`/no idle -> `pick("idle")` also None -> `fname=None` -> no pose change (keeps previous). Requires the user to author a broken `state_map`. **GAP (P3)** but low — minimal net is a hardcoded ultimate fallback to a known-good idle filename in `set_state` when `fname` is None. Low priority (needs deliberate bad settings input).
- **Old QMovie churn on rapid `set_state`.** Stopped + reassigned + GC'd normally (`mascot_stage.py:276-278`). Just churn. **OK.**
- **`refresh_selector` mid-pick resets `_last`.** Confirmed (`mascot_stage.py:262-264`); only effect is a possible immediate pose repeat. Cosmetic. **OK.**

### 12. Reaction-state poses driven by other subsystems — AUDIT
- **Settings-apply order: `refresh_tts` `stop()` vs in-flight daemon.** Confirmed `_apply_settings` order (`shell.py:639-641`) and `refresh_tts` `self._tts.stop()` (`mascot_stage.py:365`) is a cross-thread call on the engine while a daemon may be using it, no lock. Worst case = dropped line / rare backend hiccup swallowed in the daemon. **OK** (engine-impl-dependent; acceptable for fire-and-forget voice, not this area's data).
- **Language switch clears `task_lines`.** Confirmed guarded (`shell.py:636-638`); a per-task line in the old language is correctly dropped before repopulate. **OK.**
- **Reaction `set_state` while selector open.** Confirmed `_selector_open` untouched (`shell.py:418`); pose swaps under the still-valid arc. Cosmetic. **OK.**
- No persistence in this flow. **OK.**

### 13. Break-time gating reads the running span — AUDIT
- **`_break_tick` swallows everything in a bare except.** Confirmed (`shell.py:513-518`): a failing job/sampler/scheduler bug is silently ignored every 3 min. By design (defensive, never break the UI loop) and documented in the docstring. **OK** (acceptable; surfacing maintenance failures is a separate observability feature, out of scope).
- **Resurrected-open-span disables HEAVY forever.** Confirmed: links flow 7's corrupt-`end` GAP — `running()` returns the phantom span -> `_derive_break_state` (`shell.py:535-538`) overrides `on_break=False` permanently. Fixed at the root by the flow-7 `reload` clamp (P2); no separate net needed here.
- **Read-only here.** Confirmed `running()` just scans `_entries` (`activity.py:157-162`); all on the Qt main thread. **OK.**
- **`_detect_on_ac()` raises OUTSIDE the try/except.** CONFIRMED GAP (P2): `_derive_break_state` is called at `shell.py:512` BEFORE the `try` (`shell.py:513`), and it calls `self._detect_on_ac()` (`shell.py:538,542`) unguarded. On a base install `detect_on_ac()` returns None safely, but with `[power]`/psutil installed a probe hiccup throws straight into the `_break_timer` slot -> unhandled in the event loop. Minimal net: either move `state = self._derive_break_state()` INSIDE the existing `try` block in `_break_tick` (`shell.py:512` -> after `shell.py:513`), OR wrap `self._detect_on_ac()` in `_derive_break_state` in `try/except Exception: None`. The one-line move into the existing try is the smallest fix.

### 14. Quit / close — persist the activity log — AUDIT
- **Final save can raise and abort quit — CONFIRMED GAP (P2).** `_quit` (`shell.py:792-801`): `todo_store.save()` then `activity_store.save()`, NO try/except. A raising write aborts before `note_store.close()`, `_break_timer.stop()`, `_mini.close()`, `QApplication.quit()` -> app hangs in tray, break timer keeps firing, mini orphaned. Minimal net: wrap each save in `_quit` in its own `try/except Exception: pass` so a failed save never blocks teardown/quit. Small.
- **Crash mid-write loses everything (cross-cutting).** Confirmed non-atomic; the very save meant to preserve the open span is the one most likely interrupted by OS shutdown. Root cause = the atomic-write GAP (P1 below). The open-span-survives-quit guarantee is defeated by it.
- **closeEvent routes to tray, not quit.** Confirmed (`shell.py:786-789`): window-close hides to tray, does NOT save. But mutations save eagerly (flows 4/5) and `last_board_open` always saves on change, and a running span's `end` is correctly NOT written on close-to-tray (still open, by design). **OK.**
- **Daemon TTS/prewarm abandoned at quit.** Confirmed `_quit` doesn't join/cancel them (`mascot_stage.py:359,318`). Same TtsCache-atomicity GAP as flow 10 — note, don't fix here. **OK** for log integrity (no activity-log impact).
- **Two-store partial save ordering.** Confirmed `_quit` saves `todo_store` first (`shell.py:793`); if it raises, `activity_store.save` is skipped — but activity was already flushed on the last mutation, so only a re-serialization is skipped. Low impact, and the per-save try/except net above isolates the two stores. **OK** once the per-save guard lands.

---

### THE ONE P1 (root cause behind 4/7/9/14 data loss)
**Non-atomic `ActivityStore.save`.** A crash/power-loss mid-`write_text` truncates `activity.json` -> next `reload` resets the whole log + the Friday latch to empty. This is the single highest-value fix and also hardens the open-span-survives-quit guarantee. Minimal net: write to `self.path.with_suffix(".json.tmp")` then `os.replace(tmp, self.path)` (atomic on the same filesystem) inside `ActivityStore.save` (`activity_store.py:81-92`). (The same pattern would help `todo_store`/`settings`/`note_store`, but per the request scope this gap is filed for `activity_store` only.)

---

## Area: lifecycle

## Lifecycle & Window — Audited Against Real Code

Verified the actual source for every interruption. Two cross-cutting facts hold up; one headline claim in the catalog is **wrong** and is downgraded below.

### Cross-cutting verification

- **Non-atomic JSON writes — CONFIRMED.** `Settings.save` (`settings.py:108-114`), `TodoStore.save` (`todo_store.py:58-61`), `ActivityStore.save` (`activity_store.py:81-92`) all do a bare `write_text(json.dumps(...))`: truncate-then-write, no temp + `os.replace`. A crash mid-write truncates the file; every loader catches `JSONDecodeError`/`OSError` and resets to defaults (`settings.py:86-91`, `todo_store.py:43-48`, `activity_store.py:62-65`) → silent loss of the **whole file**, not just the in-flight change. This is the one true P1.
- **TodoStore per-mutation durability — CATALOG CLAIM REFUTED.** Flow 20 claims "TodoStore only flushes on `_quit`" and calls it "the single biggest data-loss exposure." **False.** Static-checked every public mutation: `add`/`update`/`complete`/`reopen`/`soft_delete`/`purge`/`start_timer`/`stop_timer` all call `self.save()`; `restore` → `reopen` → saves; `_on_reorder` calls `store.save()` explicitly (`todos_view.py:584`). The `_quit` save is a redundant final flush. **Close-to-tray loses no todo data.** Classified OK below. (The shared truncate-write corruption window is the real risk, not "unsaved at close".)
- **NoteStore two-step write — CONFIRMED but low-risk.** `_write` writes the `.md` then `commit()`s the sqlite index (`note_store.py:207-211`). A crash between desyncs index from vault, BUT the index is fully rebuilt from the markdown (source of truth) on every launch (`reindex`, `note_store.py:85-102`) → self-heals. OK.
- **Single-instance guard — CONFIRMED as described.** `attach`→`detach`→`create` (`__main__.py:34-39`) is non-atomic and the second launch only `print`s; it never focuses the running instance (the docstring at line 7 overstates). 
- **Voice `says()` fire-and-forget — CONFIRMED.** `_speak` early-returns when `tts_enabled` is off and runs synth on a daemon thread (`mascot_stage.py:301-318`); a synth failure can't reach the caller. Degrade-safe.

---

### Per-flow audit (CURRENT HANDLING → OK / GAP)

**1. App launch (manual)**
- Step 4 store-open on a bad/unwritable vault: `NoteStore.__init__` does `notes_dir.mkdir(...)` + `sqlite3.connect` (`note_store.py:67-69`) with **no guard**, before any UI and outside the only try/except (which wraps autostart at `shell.py:218-222`). An unwritable vault → uncaught exception → **launch aborts, no window, no tray**. **GAP.**
- Step 4 seed-tags `settings.save()` (`shell.py:196-197`): first write of session; a read-only config dir raises uncaught → abort. Same family as above. **GAP** (folded into the store/settings-open guard).
- Step 9 persisted `hidden` mode + broken tray → running invisible unreachable process. Real, but a compound of the no-tray gap (see flow 11/18). **GAP** (tracked once, below).
- Step 6 `switch_tab` refresh on corrupt-but-loaded data: would abort launch — but loaders already coerce to safe shapes (`todo_store.py:51-55`), ranking handles empty/garbage. Low. OK.

**2. Second-launch guard**
- Confirmed: second instance prints + returns 0, running instance untouched (`__main__.py:37-39`). User double-clicking a windowed exe sees nothing. **GAP** (P3 — confusing, no data risk).
- attach/detach race defeating the guard: real but extremely narrow (two launches within the same few-ms window). **GAP** (P2, but very low likelihood; minimal fix is large — leave as note).

**3. Autostart reconcile**
- Fully wrapped `try/except: pass` (`shell.py:218-222`); a locked-down HKCU silently swallows and **retries the failing write every launch** (never converges). No data risk; invisible no-op. Confirmed. **GAP** (P3).
- Moved/renamed exe → stale Run-key, `get_autostart()` returns True so reconcile never rewrites it. Confirmed by `get_autostart` only checking value existence (`platform_win.py:104-124`). **GAP** (P3).

**4. Boot launch (login)**
- `--autostarted` detection (`__main__.py:46`) cosmetic-only. Boot greeting silent-drops if voice absent — degrade path. OK.

**5. Standby/resume re-greet**
- `int(message)` inside blanket `try/except: pass` (`shell.py:676-688`) → bad message = no greeting. OK.
- 5s monotonic debounce (`shell.py:699-702`), `getattr(..., 0.0)` default → first resume works, double-fire collapsed. OK.

**6 & 7. Frameless drag (full / mini)**
- `_drag` in-memory, reset on release (`shell.py:153-154`, `mini_window.py:148-149`); hidden mid-drag leaves stale `_drag` but it's overwritten on next press and nothing persists. No loss. OK.

**8. Toggle always-on-top (pin)**
- `toggle_on_top` (`shell.py:706-714`) is **not persisted** — confirmed, diverges from mute/mode which persist. By design but inconsistent. **GAP** (P3, optional).

**9. Toggle voice mute**
- `settings.save()` (`shell.py:651`): truncate-write corruption window (cross-cutting). Covered by the atomic-write net.
- Settings dialog is modal `exec` so the title-bar button can't race it. After apply, `_sync_mute_icon` reconverges (`shell.py:643`). OK.
- `refresh_tts` rebuild on a bad voice id: `make_engine` is documented + verified **never raises** — degrades down to `NoopEngine` (`tts.py:791-826`); model loads lazily, constructors are cheap. The toggle cannot half-complete into a broken engine. OK.

**10. Open Settings**
- **SettingsWindow mutates `self.settings` ONLY in `_save()`** (`settings_window.py:755-800`), which then `save()` + `applied.emit()` + `accept()`. Esc/X reject runs none of it → in-progress edits dropped cleanly, no in-memory mutation leaks. The catalog's "worth verifying" → **OK**.
- **vault_path change does NOT re-open stores.** `_apply_settings` (`shell.py:631-643`) re-themes, re-langs, refreshes mascot — but never reconstructs `todo_store`/`note_store`/`activity_store`/`semantic`/`llm`. They keep pointing at the OLD vault while Settings shows the new path → new writes go to the old vault, silent split state until restart. **GAP** (P2 — confirmed real).

**11. set_window_mode (core)**
- Step 2 persist: truncate-write window (covered by atomic net).
- Step 4 HIDDEN with no tray + Step 5 MINI build-after-hide: `set_window_mode` sets `self._mode`+persists, `self.hide()`, THEN `_ensure_mini().show()` (`shell.py:746-749`). If `MiniWindow()` raises, the main window is **already hidden** and `_mode`/settings are **already MINI** → stuck invisible, and relaunch re-enters MINI and re-hits the failure. Order bug confirmed (hide-then-build). **GAP** (P2).
- No-tray HIDDEN → no `_on_tray_activated` path back. **GAP** (P2 — the no-tray escape hatch, tracked once).

**12. Cycle window mode (grip)** — inherits 11; Hidden never cycles (`shell.py:772-774`). Reinforces no-tray stuck state; no new gap.

**13. Tray radio group** — exclusive `QActionGroup` (`shell.py:376-387`); `_sync_mode_controls` re-checks after a switch (`shell.py:765-770`), so a failed switch (11.5) leaves the radio claiming the wrong mode. Cosmetic, recovered by next action. OK (minor; folded into 11.5 fix).

**14. Lazy mini creation** — `_ensure_mini` docks **only on creation** (`shell.py:756-763`); later MINI entries just `show()`+`raise_()` (no re-dock). A failed initial `dock_right` (returns False, `platform_win.py:65-66`) leaves the mini at default (0,0) for the session. Cosmetic placement. **GAP** (P3, optional).

**15. Mini top-todo refresh** — `refresh_todo` (`mini_window.py:116-124`) calls `mini_todos` in `showEvent`/timer; if it raised on malformed data a throwing `showEvent` could abort the show. But the loaders sanitize data and `mini_todos` is read-only ranking. Stale-up-to-30s read is benign. OK.

**16. Mini → full restore** — `set_window_mode(FULL)` → `show_dock` → `dock_right`; on no-screen, window shows at stale geometry but visible/recoverable. OK.

**17. Mini activity pick** — shared `ActivityStore`; `start()` auto-saves and closes the prior span (`activity.py:142-147`) → last-wins, no orphan. OK.

**18. Hide to tray (eye-off)** — `hide_to_tray` → `set_window_mode(HIDDEN)` then `if self.tray.isVisible()` balloon (`shell.py:716-720`). On a no-tray system the window hides with no restore path. Same no-tray hazard. **GAP** (P2 — the consolidated no-tray net).

**19. Tray single-click** — only acts on `Trigger` (`shell.py:776-782`); some Linux trays don't send Trigger on single-click. Platform-specific; the context menu (Quit/mode radios) still works as the fallback path. **GAP** (P3, platform — low priority since menu exists).

**20. Close-to-tray vs quit**
- Tray visible → `e.ignore()` + `hide_to_tray()` (`shell.py:784-790`). Does NOT call `_quit`, BUT every store auto-saves per mutation (verified above) → **no unsaved todo data**. Catalog's P1 here is **refuted → OK.**
- No tray → `e.accept()` with `setQuitOnLastWindowClosed(False)` (`__main__.py:28`): window closes, app keeps running with **no window and no tray** → invisible orphan; and the final `_quit` flush never runs (though per-mutation saves already persisted everything). **GAP** (P2 — orphan process, not data loss).

**21. Quit (tray menu)** — three sequential non-atomic saves (`shell.py:792-795`). A crash between them = partial persistence; a crash *within* one corrupts that file. Covered by the atomic-write net. `note_store.close()` is just `_db.close()` (writes already committed eagerly) → OK. Break-tick stopped after the saves (step ordering nit) — different files, low risk. OK.

**22. Minimize** — `showMinimized` (Qt). `_mode` stays FULL, so a later tray single-click *hides* rather than restores (flow 19) → two clicks / confusing on Tool-window platforms. No data loss. **GAP** (P3).

**23. Weekly-Board auto-open (Fri 17-18h)**
- `set_last_board_open(now)` saves **before** the board is shown (`shell.py:473`); if the subsequent `set_window_mode`/`switch_tab`/`digest_text` raises, the day is already burned and the board won't retry (the 60s poll re-checks `should_auto_open_board`, which now returns False for today — `activity.py:124`). Mark-after-show would be safer. **GAP** (P2 — silent miss).
- `set_window_mode(MODE_FULL)` defaults `persist=True` (`shell.py:476`, `728`) → a user's deliberate HIDDEN/MINI preference is **silently overwritten** to full and never restored. **GAP** (P2 — clobbered preference).
- `digest_text()`/LLM call has no local try (`shell.py:483`); an LLM raise throws on the Qt loop after the day is already marked. Compounds the burned-day miss. **GAP** (P2 — fold into the same auto-open hardening).

**24. Activity from full stage**
- `start`/`stop` auto-save each mutation (`activity_store.py:104,109`); fast A→B picks close the prior span first (`activity.py:142-147`) → no orphan. Crash mid-save = cross-cutting corruption (covered). OK.
- Step 3: picking Focus during an existing Focus calls `focus_widget.start()` which does `pomo.start(now)` (`focus_widget.py:103-106`) → **resets the in-progress Pomodoro elapsed silently**. By design (selecting Focus = fresh session) but loses elapsed without warning. **GAP** (P3, optional — UX only, no persisted data).

**25. Idle / break-time gate**
- `_break_tick` runs jobs **synchronously on the Qt main thread** (`shell.py:499-518`); the docstring admits a long re-embed blocks the UI, and a `_quit` mid-tick queues behind it → app appears hung. Whole tick wrapped in `try/except: pass` (`shell.py:513-518`) so any maintenance failure is swallowed; if the throw precedes `record_job_results` the Settings panel shows nothing for a job that died. **GAP** (P3 — known future-hardening, base install no-ops so low live impact).
- Idle clock: `max(0.0, (now - last).total_seconds())` clamps backward jumps (`shell.py:539`); running-span hard override protects active work (`shell.py:535-538`). A forward clock jump / post-standby first tick could fire HEAVY maintenance early, but re-embed is idempotent and `_touch` re-gates. Low harm. OK.

**26. Cross-platform docking**
- `dock_right` is called only on launch / `show_dock` / mini creation — **not** on a screen-geometry-changed signal (`platform_win.py:51-66`). Unplugging the docked monitor strands the window off-screen until the next FULL re-entry (which calls `show_dock`); mini never re-docks. Recoverable via tray→FULL; no data loss. **GAP** (P3).
- `setGeometry` failure returns False silently → stale geometry, visible. OK. The `+1` flush-right pixel is cosmetic. OK.

---

### GAP summary (deduped)

The single P1 is the shared non-atomic write across all three JSON stores — one safety net (write-temp-then-`os.replace`) fixes every flow that persists (1, 9, 11, 21, 23, 24). The recurring P2 is the no-tray / hidden-mode unreachable-window family (1.9, 11.4, 18, 20) — one guard makes HIDDEN refuse when the tray isn't visible. Remaining P2s are independent (vault-path stores, MINI hide-before-build order, Friday board mark-before-show + preference clobber). P3s are polish/UX.

---

## Area: settings

## Settings — interruption audit (verified against real code)

Read: `serenity/ui/settings_window.py` (`_save` :755-800, build :68-428, clone helpers :721-748, kokoro :645-687), `serenity/core/settings.py` (`load` :82-106, `save` :108-114), `serenity/core/voice_clones.py` (`add` :133-156, `remove` :158-172, `save` :115-119), `serenity/ui/shell.py` (`__init__` stores :163-182, autostart reconcile :218-222, `open_settings`/`_apply_settings`/`toggle_mute` :626-653), `serenity/ui/platform_win.py` (`set_autostart` :69-101, `get_autostart` :104-124). Every line ref below was confirmed.

### Cross-cutting facts — re-verified
- **F-A (live object, no snapshot) — CONFIRMED.** `open_settings` passes live `self.settings` (`shell.py:627`); `_save` mutates it field-by-field (`:756-794`) with NO defensive copy and NO try/except, then `save()` (`:798`). A throw mid-`_save` leaves the live object half-changed while `settings.json` is untouched → **GAP**.
- **F-B (non-atomic writes) — CONFIRMED.** `Settings.save` (`settings.py:113`) and `CloneRegistry.save` (`voice_clones.py:118`) are bare `write_text`, no temp+rename. `Settings.load` swallows a corrupt file → resets to ALL defaults (`:86-89`); `CloneRegistry.load` swallows corrupt → drops every clone (`:101-104`) → **GAP**.
- **F-C (autostart before save) — CONFIRMED.** `set_autostart` (`:797`) runs before `save()` (`:798`); `set_autostart` is fully guarded and CANNOT raise (returns False on any Exception, `platform_win.py:100-101`). Shell reconciles toward the SETTING next launch (`shell.py:218-222`) → after a failed save the old on-disk setting wins, silently reverting a registry change. Mostly safe; one narrow GAP (silent no-op when registry unwritable).
- **F-D (no concurrency guard / dual registry) — CONFIRMED.** Shell holds NO `CloneRegistry`; each `SettingsWindow` builds its own (`settings_window.py:78`). Nothing prevents two open windows → **GAP** (last-writer-wins on both `clones.json` and `settings.json`).
- **F-E (deferred-vs-immediate split) — CONFIRMED.** All fields deferred to Save except clone add/remove which hit disk at click (`_add_clone` :734 → `voice_clones.py:155`; `_remove_clone` :747 → `:171`) → **GAP** (Close doesn't roll them back; remove has no confirm).

---

### 1. Open the Settings window
- **CURRENT.** `__init__` builds all tabs eagerly. `_general_tab` does `from ..core.semantic import ...` (`:192`) and `from ..core.tts import ...` (`:228`) at build time, NOT wrapped. `_probe_status` is per-row try/excepted (`:444-487`), so the AI tab is safe, but a raising semantic/tts IMPORT inside `_general_tab` propagates out of `__init__` → `dlg.exec()` never runs.
- **CLASSIFY: GAP (P2).** Per the degrade contract, imports of optional modules should never hard-fail the only UI that can disable them. The modules themselves import lazily, so this is low-likelihood, but a half-installed extra (module present, sub-dep broken) would brick Settings.
- **Concurrent open (F-D): GAP (P2)** — see flow 31.

### 2. Render scale
- **CURRENT.** Combo index → `["S","M","L"]` (`:756`), assigned FIRST. Close discards (no write). Crash later in `_save` leaves live object with new scale, unpersisted.
- **CLASSIFY: OK** for Close (deferred, benign). The partial-apply risk is the F-A GAP folded into flow 31; no separate net needed here.

### 3. State→pose map
- **CURRENT.** `_save` keeps only keys in `POSE_FILES` (`:791`); `if keys:` drops a state whose every key is invalid (`:792`), then `state_map()` falls back to default for it (`settings.py:128-129`). Silent — no feedback, and a deliberately-blanked state also reverts to default (cannot blank to silence a pose).
- **CLASSIFY: GAP (P3).** Cosmetic personalization only, no data loss. Minimal net: a one-line inline warning label when `_save` discarded any typed key.

### 4. Image library (read-only)
- **CURRENT.** `.exists()` guard (`:147`); missing file → no icon; `QPixmap` on a corrupt file yields a null pixmap, `.scaled` is a no-op → blank icon, no crash. No writes.
- **CLASSIFY: OK** (graceful degrade).

### 5. Vault path (mid-session)
- **CURRENT.** `_save` writes `vault_path` (`:757`) + persists, but `_apply_settings` (`shell.py:631-643`) does NOT rebind `todo_store`/`note_store`/`activity_store`/`semantic` (built once `shell.py:165-182`). So the field shows the new path while all writes still go to the OLD vault until restart. Blank keeps old (`:757`, intended). NO existence/writability validation; a bad typed path is accepted and only fails at next `Shell.__init__`.
- **CLASSIFY: GAP (P2).** Two issues: (a) silent mid-session inconsistency (headline caveat) and (b) no validation. Minimal net: validate the path is creatable/writable at `_save` and warn-and-keep-old if not; plus a short note that a vault change applies on restart. No store-rebind needed (out of scope; restart is the documented model).

### 6. Autostart toggle
- **CURRENT.** `set_autostart` fully guarded; off-Windows no-op (`platform_win.py:71`), Windows failure returns False SILENTLY (`:100-101`). Checkbox still persisted to JSON, so JSON can say ON while the Run key was never written; `shell.py:218-222` retries next launch but a persistently-unwritable HKCU means "start on login" silently never works.
- **CLASSIFY: GAP (P3).** Rare, self-healing-on-retry, no data loss. Minimal net: surface a one-line warning when `set_autostart(True)` returns False AND we're on Windows.

### 7. Capture hotkey
- **CURRENT.** Free text, NOT validated (`:759`); blank EMPTIES the hotkey (no keep-old, unlike most fields). Bad/conflicting combo persisted as-is; binding (elsewhere in shell) silently never takes, no feedback in Settings.
- **CLASSIFY: GAP (P3).** No data loss; disables a convenience feature silently. Minimal net: keep-old on blank for consistency, and/or a note that an invalid combo won't bind. Low priority.

### 8. AI / voice stub toggles
- **CURRENT.** Booleans assigned directly (`:760-761`). Close discards. Partial-apply risk is the F-A GAP (flow 31).
- **CLASSIFY: OK** (no separate net).

### 9. Embedding model
- **CURRENT.** `_save` `:765-770`: preset key, or trimmed custom id, keep-old on blank (`:768`). `SemanticIndex`/`FastEmbedBackend` built once (`shell.py:171-174`); `_apply_settings` does NOT rebind → a model change applies only on restart; a bad custom id degrades to keyword search on first Meaning search (per the in-UI hint :215-218). No validation at Save.
- **CLASSIFY: OK.** The hint already tells the user it rebuilds on next use and degrades to keyword search; the degrade path is the documented safety net. Mid-session lag and bad-id are acceptable per the degrade contract. No net.

### 10. Master TTS toggle
- **CURRENT.** `_save` writes `tts_cb.isChecked()` (`:771`). Title-bar mute (`shell.py:645-653`) flips+persists independently. The dialog seeds its checkbox at OPEN; the modal blocks the title bar, but tray/hotkey mute BEFORE opening is reflected. Real hazard: if `tts_enabled` changes out-of-band between open and Save, `_save` overwrites with the stale checkbox → silently reverts that change; `applied`→`_sync_mute_icon` (`shell.py:643`) hides the revert.
- **CLASSIFY: GAP (P3).** Narrow (modal blocks the in-app control; needs tray/hotkey timing). Minimal net: re-seed the checkbox value from `self.settings.tts_enabled` is impractical mid-modal; lowest-cost fix is documentation/accept. Marginal — list as P3.

### 11. English voice engine
- **CURRENT.** `cur_en=="sapi"` pre-selected as kokoro for DISPLAY (`:257-258`); `_save` then writes `kokoro` (`:772`) and mirrors to legacy `tts_engine` (`:775`). A bare open+Save silently migrates stored `sapi`→`kokoro`. `refresh_tts` (`shell.py:640`) rebuilds; absent dep → silent noop (only the status tab surfaces it).
- **CLASSIFY: OK.** Intended migration of a dropped engine to a shipped default (matches the :254-256 comment and commit `726f58b`); silent synth degrade is the documented contract surfaced on the status tab.

### 12. Kokoro voice (+ all-langs toggle, folder scan)
- **CURRENT — two findings.**
  (a) `_rebuild_kokoro_voices` (`:645-687`) preserves `prev` and falls back to `af_heart`/first real row when the prior pick is gone (`:682-684`); if the user then Saves, the FALLBACK is persisted, not their intent. **GAP (P3)** — silent pick change, cosmetic, low likelihood.
  (b) `scan_kokoro_voices(self.voices_dir)` (`:674`) is NOT try/excepted, and `_rebuild_kokoro_voices` is called at BUILD (`:273`). An OSError on an unreadable `voices_dir` mount propagates → toggling the checkbox throws, or the build call throws → whole Settings window fails to open (ties to flow 1). **GAP (P2).**
- `_save` keep-old when combo on a disabled header (data None) (`:776`) — OK.

### 13. English cloned voice
- **CURRENT.** Combo filled from `clones.for_lang("en")` at build (`:278`) / `_refresh_clone_list` (`:709`). Another window (F-D) removing the clone leaves THIS combo still listing it; `_save` writes `currentData() or ""` (`:780`) → persists a `clone:` id whose clip is gone; Chatterbox silently falls back to default at synthesis. No existence re-check at Save.
- **CLASSIFY: GAP (P2)** — part of the F-D dual-registry gap (flow 31). Synthesis degrade is graceful, but the persisted dangling ref is inconsistent state.

### 14. English Piper voice id
- **CURRENT.** Free text, keep-old on blank (`:778`); bad id fails silently at synthesis (degrades).
- **CLASSIFY: OK** (degrade-to-fallback contract; same class as flow 9).

### 15. German voice engine
- **CURRENT.** `cur_de in ("kokoro","sapi")` → display piper (`:306-307`); bare open+Save rewrites stored `kokoro`/`sapi`→`piper` (`:773`).
- **CLASSIFY: OK** (intended migration, matches :304-306 comment).

### 16. German cloned voice
- **CURRENT.** Same as flow 13 (`:781`).
- **CLASSIFY: GAP (P2)** — folded into the F-D gap (flow 31).

### 17. German Piper voice id
- **CURRENT.** Free text, keep-old on blank (`:777`).
- **CLASSIFY: OK** (same as flow 14).

### 18. Add (clone) a voice — IMMEDIATE disk write
- **CURRENT.** `_add_clone` (`:721-740`): empty name/clip → warning+return (`:725-728`); missing clip → warning+return (`:730-732`); `clones.add` wrapped for `OSError` → warning (`:735-737`). `clones.add` (`voice_clones.py:133-156`) does `shutil.copyfile` (`:149`) THEN `save()` (`:155`); a failed save AFTER a successful copy leaves an ORPHANED clip (in-memory entry lost on dialog close; JSON never got it). `shutil.copyfile` is non-atomic → a crash mid-copy leaves a truncated dest that `exists()` reports True → broken-but-listed clone. Re-add same name+lang overwrites the dest in place (`:147-149`) with no backup → a failed re-copy corrupts a working clone. Concurrent add (F-D) → second window's full-file `save()` drops the first's entry. Close does NOT roll back the copy (F-E).
- **CLASSIFY: GAP (P2).** Input validation and OSError are already handled (OK there). The residual gaps are: orphaned/truncated clip on partial failure, and Close-doesn't-undo. Minimal net: write the clip to a temp name then atomic-rename in `voice_clones.py add`, and `save()` (atomic) BEFORE finalizing so a failure leaves no half state. Effort M.

### 19. Remove a cloned voice — IMMEDIATE disk write, NO confirm
- **CURRENT.** `_remove_clone` (`:742-748`): `currentItem() is None` → return (`:744-745`, OK). Otherwise `clones.remove` UNLINKS the clip (`voice_clones.py:168`, guarded to only delete clips inside our own dir) and rewrites JSON immediately — NO confirmation dialog. A misclick permanently deletes a user-supplied reference clip; Close does NOT undo. The removed id may still be the persisted `tts_clone_en/de` (removal doesn't touch Settings) → dangling active selection → silent default-voice fallback at synthesis. Concurrent remove (F-D) can resurrect a zombie catalog entry whose clip is already unlinked (`:704` shows "(clip missing)").
- **CLASSIFY: GAP (P1).** Irreversible deletion of a user-supplied file on one stray click with no confirm = data loss. Minimal net: a `QMessageBox` confirm before `clones.remove` in `_remove_clone` (`settings_window.py`). Effort S. (The dangling-selection + zombie pieces fold into the F-D/F-E gaps.)

### 20. TTS speed
- **CURRENT.** Slider clamped 50..200 (`:373`); `_save` `value()/100` ∈ [0.5,2.0] (`:782`). Close discards.
- **CLASSIFY: OK.**

### 21. TTS volume
- **CURRENT.** Slider clamped 0..100 (`:384`); `_save` `value()/100` ∈ [0,1] (`:783`).
- **CLASSIFY: OK.**

### 22. TTS caching toggle
- **CURRENT.** Boolean (`:784`). Turning OFF doesn't purge `voices/cache` (stale files remain, harmless).
- **CLASSIFY: OK** (stale cache is inert; not data loss).

### 23. UI language EN/DE
- **CURRENT.** `_save` sets `language` (`:785`). `applied.emit()` (`:799`) is AFTER `save()` (`:798`), so a `save()` exception SKIPS the emit → `_apply_settings`'s `task_lines.clear()` (`shell.py:636-637`) never runs while the live `self.settings.language` is already the new value → cached lines stay in the OLD language until restart.
- **CLASSIFY: GAP (P2)** — this is a symptom of the F-A/flow-31 partial-apply (mutate-before-persist with no rollback). Fixed by the flow-31 net; no separate net.

### 24. Theme accent
- **CURRENT.** Free text, keep-old on blank (`:786`); fed to `stylesheet(self.settings.accent)` on apply (`shell.py:632`). An invalid color → Qt silently ignores it → odd/unstyled accent, no crash.
- **CLASSIFY: GAP (P3).** No data loss, purely cosmetic + recoverable (re-edit). Minimal net: validate with `QColor(text).isValid()` at `_save`, keep-old+warn if invalid. Low priority.

### 25. Undo window (seconds)
- **CURRENT.** Slider clamped 5..40 (`:419`); `_save` int (`:787`); `Settings.load` coerces str→int with fallback 5 (`settings.py:97-100`); a hand-edited out-of-range value is clamped by `setValue` on next open.
- **CLASSIFY: OK** (clamped + coerced).

### 26. AI & voice status (read-only)
- **CURRENT.** Per-row try/except (`:444-487`). Constructors (`make_engine`/`LlamaCppLLM`/`FastEmbedBackend`) run at tab-build (`:506`) but are advertised cheap (the `available` flag is a light probe). No writes.
- **CLASSIFY: OK** (matches the degrade/lazy contract; the docstring :432-437 asserts no model loads).

### 27. Last-minute performance (read-only)
- **CURRENT.** `_perf_lines` wraps `recent_samples()`/`job_history()` in try/except (`:540-544`); `perf is None` → placeholder (`:538-539`). No writes.
- **CLASSIFY: OK.**

### 28. About (read-only)
- **CLASSIFY: OK.**

### 29. Check for updates
- **CURRENT.** `QDesktopServices.openUrl(QUrl(RELEASES_URL))` (`:597`); return value ignored → silent no-op if no handler. No writes, no polling.
- **CLASSIFY: OK** (mild; re-clickable; not in scope for a safety net).

### 30. Voice-commands help (read-only)
- **CLASSIFY: OK.**

### 31. Save all settings — the aggregation hazard
- **CURRENT.** `_save` (`:755-800`) mutates ~25 live fields, then `set_autostart`, then `save()`, `applied.emit()`, `accept()` — NO try/except, NO transaction, NO snapshot (F-A). Any throw mid-sequence (e.g. a destroyed widget, an unexpected index) leaves the live shell `self.settings` half-changed, with `save()`/`applied`/`accept()` all skipped → app runs on an unpersisted, unapplied half-config, dialog stays open, restart reverts. A crash mid-`save()` (F-B) truncates `settings.json` → next `load` silently resets ALL settings to defaults. Concurrent windows (F-D) → last-writer-wins, interleaved fields. `set_autostart` before `save()` (F-C) → registry/file disagreement on a save failure.
- **CLASSIFY: GAP (P1).** Three nets:
  1. **Atomic write** in `Settings.save` (`settings.py`): write to `settings.json.tmp` then `os.replace` → kills the corrupt-truncation total-loss path (F-B). Apply the same to `CloneRegistry.save` (`voice_clones.py`). Effort S.
  2. **Snapshot/rollback in `_save`** (`settings_window.py`): take a shallow copy of the live settings fields before mutating (or build into a local dict and assign at the end), and wrap the mutate+save in try/except so a partial throw restores the old live object and the dialog stays usable instead of half-applied (F-A). Effort M.
  3. **Single-window guard** (F-D): have the shell keep one `SettingsWindow`/`CloneRegistry` and re-raise/focus the existing dialog in `open_settings` (`shell.py:626`) instead of building a second. Effort M. Eliminates dual-registry clone loss AND interleaved saves AND the stale-clone-ref (flows 13/16/18/19 concurrent cases).

### 32. Close / cancel without saving
- **CURRENT.** `reject()`/`[X]`/Esc → no `_save`, no write. Correct for all deferred flows. But clone add/remove already wrote at click (F-E) → Close does NOT roll them back; and a prior failed `_save` (flow 31) leaves the live object half-mutated that Close can't restore.
- **CLASSIFY:** Deferred-discard path is **OK**. The two caveats are the F-E gap (flows 18/19) and the F-A gap (flow 31) — both covered above; no separate net for Close itself.

---

## Area: ai_maint

# Area `ai_maint` — audited interruption / failure annotation

Read & verified against real code: `shell.py`, `activity_store.py`, `todo_store.py`, `note_store.py`, `activity.py`, `breaktime.py`, `llm.py`, `semantic.py`, `phase2_stubs.py`, `digest.py`, `maintenance.py`, `task_lines.py`, `perf.py`, `weekly_board_view.py`, `settings_window.py`.

## Cross-cutting facts (all confirmed)

- **Break tick is SYNCHRONOUS on the Qt main thread** (`shell.py:499-518`; comment `504-508`). First real run (cold model load / full re-embed / N `generate()` calls) blocks the UI. Whole tick wrapped in one bare `try/except: pass` (`513-518`) — every error silently swallowed, no logging. CONFIRMED.
- **No atomic writes anywhere in `core/`** — `grep os.replace serenity/core` = 0 hits. `ActivityStore.save()` (`activity_store.py:81-92`), `TodoStore.save()` (`todo_store.py:58-61`), `NoteStore._write()` (`note_store.py:207-211`) are all plain `write_text`. CONFIRMED.
- **`ActivityStore.reload()` silently resets to EMPTY on corrupt JSON** (`activity_store.py:62-65`) → all tracked-time history + the board marker lost on a torn write. CONFIRMED.
- **`TaskLineStore` is pure in-memory by design** (`task_lines.py:73-115`). CONFIRMED, intentional.
- **Sticky-on-failure** — `LlamaCppLLM._shared=False` (`llm.py:183`) and `FastEmbedBackend._shared=False` (`semantic.py:252`) never retried for process lifetime. CONFIRMED.
- **No per-job cooldown** (`breaktime.py:226-231` explicit WARNING). CONFIRMED.
- **`available` computed ONCE at construction** (`llm.py:152`, `semantic.py:226`), never re-probed. CONFIRMED.

---

## 1. Weekly Board auto-open (Fri 17–18h) + spoken digest

1. **Startup race** — immediate `_maybe_auto_open_board()` at `shell.py:239` runs during `__init__`, after `_build_ui`/`_wire`. → **OK** — no crash; harmless ordering.
2. **Gate** `should_auto_open_board` (`activity.py:114-126`).
   - **Corrupt-store de-dup loss:** torn `activity.json` → `reload()` resets marker → board re-opens every 60s through the window. → **GAP** (downstream of the non-atomic write).
   - DST / clock change flipping `date()` equality. → **OK** — silent, low-impact.
3. **Mark opened — WRITE** (`shell.py:473`, `activity_store.py:116-118`).
   - **Crash mid-write:** non-atomic `write_text` of the WHOLE store to stamp one timestamp → torn file → next launch resets → entire activity log + marker lost. → **GAP (P1).**
   - **Permission / disk-full:** `write_text` raises, NOT caught here → propagates out of the QTimer slot → marker not persisted → board re-fires next minute. → **GAP (P2).**
4. **Force-visible** `set_window_mode`+`show_dock` (`shell.py:475-477`). → **OK** — interruption, not data loss.
5. `switch_tab("board")`→`refresh()` (slow LLM blocks UI; marker already written → digest silently dropped on force-quit). → **OK** — acceptable skip; freeze is the flow-4/6 GAP.
6. Build board + digest (flow 3).
7. **Speak** intro+comment (`shell.py:482-486`). Mute mid-flow → still shown in bubble → **OK**. **Mixed-language digest** (cached comment may be old-language) → **GAP (P3)**, see flow 12.

---

## 2. Weekly Board manual open + digest build (warm-cache)

1–4. Tab click → `refresh()` (pure). Rapid tab-switch while digest mid-inference freezes UI; wasted widgets. → **OK** — freeze is the flow-4 GAP.
5. **Warm-cache — WRITES `_digest`/`_digest_sig`** (`weekly_board_view.py:138-141`).
   - **Cache key omits language:** `_board_sig` (`100-115`) keys only on numbers; lang switch not invalidated. → stale old-language digest. → **GAP (P3).**
   - Crash mid-generate: `generate_digest` never raises; both fields set together. → **OK.**
   - Single-threaded snapshot build. → **OK.**
6. **Render cards** (`145-151`): `ai=available` static, no True→True mismatch. → **OK.** (The load-fail-but-flag-True duplication is flow 3 EDGE.)

---

## 3. AI digest generation (`generate_digest`, `digest.py:151-180`)

- Fallback-first; `available` gate; inference `try/except`→fallback (`177-178`). → **OK** — robust.
- Long text: `_sanitize` no length-cap but `max_tokens=120` bounds it. → **OK.**
- **`available` True but load fails at generate:** `generate` returns "" → fallback text, BUT the digest CARD still shows (`ai=available=True`, `145-147`) and the hints card repeats the same text → duplicated text on screen. → **GAP (P3).**
- `notes=` unused. → **OK.**

---

## 4. Model load-on-first-use (`LlamaCppLLM`, `llm.py:190-219`)

- **First load blocks UI** from synchronous tick / board refresh; freezes seconds–minutes. → **GAP (P2)** — the central main-thread risk flagged at `shell.py:507`.
- **Load OOM / corrupt GGUF:** caught (`182-185`) → `_shared=False` STICKY; Settings still shows "Active" → advertised Active, actually dead until restart. → **GAP (P2).**
- Two main-thread callers race: serialized, one load per key. → **OK.**
- File deleted mid-session → same sticky-dead → covered above + never-re-probe GAP.

---

## 5. Model load-on-first-use (`FastEmbedBackend`, `semantic.py:228-298`)

- **First embed downloads weights** off the synchronous tick → network download blocks the main thread; offline → fails. → **GAP (P2)** — same root as flow 4.
- **Download/load fails:** caught → `_shared=False` STICKY → `index()` no-ops forever; degrades to keyword. Silent, never retried. → covered by never-re-probe GAP.
- **Partial/corrupt cache:** half-download → load raises → sticky-fail; corrupt cache NOT cleaned → re-fails each launch. → **GAP (P3).**
- **dim-0 custom model:** `_ensure_store` (`phase2_stubs.py:287-289`) sets `available=False`, returns None → clean degrade. → **OK.**

---

## 6. Break-time scheduler tick (`shell.py:499-518`, `520-542`)

- User quits mid-tick: same-thread, can't interleave; Quit blocked until tick returns (freeze = flow-4 GAP); hard-kill mid-`index()` recoverable (flow 8).
- Corrupt store → `running()` None → HEAVY may fire over a pre-crash span. → **OK** — edge.
- **AC probe on main thread every tick** (`538,542`): hung read blocks. → **GAP (P3)** — rare; shared 6/10/13.
- Perf sample: in-memory, `_probe` guarded. → **OK.**
- Per-job exception → `JobResult(ok=False)` (`breaktime.py:241-243`), queue continues. → **OK** — robust isolation.
- No-cooldown re-run incremental → cheap; sticky-failed e5 runs `needs_embed` SELECTs each tick (pointless). → **OK** — harmless.
- User returns mid-job: long re-embed completes, UI frozen = flow-4 GAP.
- **Whole-tick `try/except: pass`** swallows everything incl. perf errors, no logging; failure visible only in Settings panel. → **GAP (P3)** — silent loss of failure visibility.

---

## 7. `_touch()` re-gates maintenance off (`shell.py:489-497`)

- Slots that DO call `_touch`: `switch_tab`, `_on_activity`, `_on_mic`, `_open_linked_note`, `_open_quick_note`, `_open_quick_todo`, `_on_slot_answer`. CONFIRMED.
- **GAP found & verified:** `_on_todo_started` (`422-430`), `_on_todo_completed` (`417-420`), `_on_focus_phase` (`449-454`), `_on_quick_todo` (`620-623`), `_on_note_saved` (`610-612`) do NOT call `_touch()`. Active todo/focus/note-saved interaction keeps the idle clock running → a HEAVY job can fire mid-use → UI freeze. → **GAP (P2).**
- Backward clock: `max(0.0,…)` (`539`) guards negative; forward jump bounded. → **OK.**

---

## 8. Break-time job: semantic-reindex (HEAVY) (`maintenance.py:52-64`, `phase2_stubs.py:295-316`)

- **Crash/kill mid-index:** each `upsert()` commits per note atomically (`semantic.py:499`); next run re-picks un-written notes; `prune()` after (`316`) → crash-before-prune leaves stale vectors that self-heal next run. → **OK** — recoverable by design.
- Note read mid-edit → garbled embed, corrected next reindex. → **OK** — transient.
- Search + reindex share `_conn` (`semantic.py:338`): both main-thread → serialized today; becomes a real cross-thread sqlite risk IF tick moves to a QThread. → **OK today** (flagged future).
- Disk-full mid-upsert → `commit()` raises → `JobResult(ok=False)`, retried. → **OK.**

---

## 9. Break-time job: task-voicelines (HEAVY) (`maintenance.py:77-89`, `task_lines.py:118-163`)

- Crash mid-pass: in-memory store, regenerated next break. → **OK.**
- Per-todo error / empty reply: caught (`154-160`), pass continues. → **OK** — robust.
- Todo started during generation: click blocked until job returns (freeze = flow 4); then fallback. → **OK.**
- **Todo TITLE edited after authoring:** line keyed by `id`, not invalidated on edit → stale line nodding to the OLD title spoken. → **GAP (P3).**
- Todo deleted: orphan lingers, FIFO-evicted, `get` only for live todos. → **OK.**
- Cap eviction: FIFO 64, pass writes ≤5. → **OK.**

---

## 10. Settings "AI and voice" status panel (`settings_window.py:445-489`)

- **Status lies about LLM health:** `_probe_status` builds a FRESH `LlamaCppLLM(...).available` (`454-462`) = file-exists; does NOT reflect a sticky load failure on the shell's `self.llm` → shows "Active" for a dead model. → **GAP (P2).**
- **AC probe on UI thread** (`479`): hung psutil freezes the dialog. → **GAP (P3)** — rare; shared 6/13.
- Panel + tick share `self.perf` same thread, snapshot copies. → **OK.**
- Modal, synchronous probes. → **OK.**

---

## 11. Started-todo speaks a personalized line (`shell.py:422-430`)

- **No `_touch()`** — flow 7 GAP.
- Store cleared mid-read: `get` None → catalog fallback. → **OK** by design.
- Stale-language: cleared in `_apply_settings`; genuine staleness is title-edit (flow 9). → **OK** here.
- `getattr(self,"task_lines",None)` guard (`427`). → **OK** — defensive.

---

## 12. Language switch clears cached task-voice-lines (`shell.py:631-638`)

- **Does NOT clear the digest cache:** clears only `task_lines` (`636-637`), NOT `board_view._digest`/`_digest_sig` → weekly digest stays old-language until numbers change; Friday flow speaks new-language intro + old-language digest. → **GAP (P3).**
- Apply vs tick same-thread; `generate_task_lines` infers language from the TITLE (`_TASK_SYSTEM` neutral) → clear-on-lang-switch partly cosmetic. → **OK** — minor mismatch.
- `getattr` guard. → **OK.**

---

## 13. AC-power probe (`detect_on_ac`, `breaktime.py:118-146`)

- All paths → None → HEAVY gated off, never raises. → **OK** — degrade-clean.
- **Desktop reports None="unknown"** → HEAVY never runs without `[power]` reporting plugged (conservative `138-142`) → many users silently get no break-time maintenance. → **OK** — documented/intended.
- Slow sensor read on UI thread (flows 6,10). → **GAP (P3)** — shared AC-probe item.

---

## 14. Scheduler registration / dedup (`shell.py:257-270`, `maintenance.py:34-99`)

- Build raises during init: pure closure-wiring, can't realistically raise; if it did → loud launch failure. → **OK.**
- Re-register replaces in place (`breaktime.py:181-186`); only on double-init (single-instance prevents). → **OK.**
- Timer starts LAST (`270`); first tick 180s later, no early-fire race. → **OK.**
- Quit during init: unreachable (single-instance + modal). → **OK.**

---

## Gap summary (deduplicated)

The "UI freezes on first heavy load on the synchronous main-thread tick" symptom across flows 4/5/6/9 is ONE root GAP (heavy break-tick on the Qt main thread). The "advertised Active but actually load-dead / never re-probed" across flows 4/5/10 is ONE root GAP. Listed once each to avoid redundant handling per CLAUDE.md.

## Area: states-contexts (Phase C)

## States & Contexts — interruption audit (flow-hardened BEFORE code, nets shipped WITH the feature)

Method inversion vs the areas above: these flows were mapped and adversarially verified from the
approved design (34 candidates → 30 verified → 16 deduped requirements R1–R16, spec
`docs/superpowers/specs/2026-07-03-phase-c-state-tag-design.md`), and every confirmed gap's net was
built into Phase C itself — so each flow below is **OK-with-net**, citing the requirement that covers
it. Read: `serenity/core/models.py` (`_clean_context`/`_clean_state_tag`), `serenity/core/states.py`
(`key_for_label`/`visible`), `serenity/ui/shell.py` (`stamp`/`_sync_state_chips`/`_sync_context`),
`serenity/ui/state_chip.py`, both list views' `refresh()`, `serenity/core/note_draft.py`
(`validate`/`promote`).

### 1. Create while an activity runs (add-bar / quick dialogs / calendar slot / voice capture)
- Every in-app funnel stamps `(state_tag, context)`; dialogs + add-bar read `stamp()` at **save time**,
  so a mid-dialog activity switch or context flip stamps the values current at commit → OK [R10, R11].
- Voice/NL capture **snapshots** the stamp when `_pending` is set; answering a slot after a flip/switch
  commits the snapshot, never "now" → OK [R10].
- The calendar slot-click dialog gets the stamp threaded through `CalendarWeekPanel`; ICS import stamps
  `context` only (`state_tag=None`), and a re-import UID update never restamps → OK [R11].

### 2. Create while Idle (or under an unmappable label)
- Idle is not a span: `stamp()` yields `state_tag=None` — the legal "no state" stamp; context is always
  concrete. A running label absent from the registry stamps `None` too (chip hides identically), and
  stamping + chip visibility derive from the SAME `key_for_label` result → OK [R2].
- Boot with a span restored from `activity.json`: one shell-level sync at construction drives both
  chips (visible + checked + labeled) without any signal emission → OK [R1].

### 3. Flip the global context (title-bar / bubble / tray / mini)
- The flip never stops a running span; a post-flip creation stamps (running key, NEW context) — an
  explicitly legal cross-context pair → OK [R15].
- Chip: a running state foreign to the new context stays **visible but unchecked** (the resolved R7↔R15
  conflict) — truth without forced foreign-state filtering; re-checks on the next activity start → OK [R7].
- Both list views re-filter via the chip sync; the VISIBLE tab (calendar/graph) re-renders immediately,
  hidden tabs self-heal on entry (`switch_tab` refresh), pop-out + mini always refresh → OK [R13].
- A done-grace window pending across the flip: the card keeps rendering (undo reachable), the timer
  never cancels, and a cross-context completion commits silently (no title narration) → OK [R3].

### 4. The state chip (both list views)
- Auto-selected on every start/switch via one shell sync; manual uncheck lasts exactly the current
  span, per-view; never persisted → OK [R4].
- Post-filter empties a searched/chipped list → count-only "N hidden by context/state filter" notice
  (never titles, never during plain browsing) → OK [R5].

### 5. Hand-edited vault input + registry drift
- `context: banana` / `123` / wrong case → deserialize coerces to None (visible in BOTH contexts);
  non-string `state_tag` → None; `visible()` re-guards at the predicate → OK [R6].
- A `state_tag` whose key was later deleted/renamed in the registry: the item keeps its stamp (filter
  simply never matches it; chip can't show a nonexistent row) — orphaned-but-harmless by design [R2, R9].
- Duplicate labels in a user registry: `key_for_label` deterministically takes the first row → OK [R9].

### 6. Pop-out editor raw-YAML edits of the stamps
- `validate()` rejects `context` outside {business, private, null} and non-string `state_tag` (panel
  stays open with the inline error); `promote()`'s fm-edited merge persists edited stamps exactly like
  an external-editor edit; missing keys keep the live values, explicit null clears → OK [R8].

### 7. Derived creations
- Recurrence clone, prep-note, and recovery re-save INHERIT the parent item's stamp (clone field list
  pinned by test — `ics_uid`/`linked_note_ids` stay deliberately uncopied) → OK [R12].

### 8. Cross-surface consistency
- Calendar tab + week pop-out (grid AND side list) + dependency graph + mini "UP NEXT" apply the
  context axis (state axis never); the graph drops edges with their hidden nodes → OK [R13].
- AI surfaces (related chips, ReadNoteDialog chain, Ask retrieval, duplicates scan) rank over
  context-filtered CANDIDATES while `semantic.index()` keeps the FULL corpus (its `prune(keep_ids=…)`
  would otherwise drop the other context's embeddings per flip); a WarmCache hit requires cited ids to
  resolve within the candidates, so cached answers can't replay across contexts → OK [R16].
- Deliberately context-agnostic: Weekly Board (Phase D), Trash (unfiltered; rows name a stamped item's
  context in the meta label → OK [R14]), tag consolidation (tags only), ranking order.

### Refuted during verification (recorded, no net needed)
- "Todo typed while Idle vanishes on Enter": unreachable race — the only `activity_store.stop()` path
  is the same-thread mascot signal; a mid-`_add` stop cannot interleave.

### 9b. Urgency-peek (follow-up slice on `wf/urgency-peek`)

Flow-hardened before code (14 candidates → 7 deduped requirements R-A..R-H, spec
`docs/superpowers/specs/2026-07-03-urgency-peek-design.md`); every net shipped with the feature.

- **Urgent-but-filtered todo (tier ≥ 2)** now PEEKS instead of hiding: full card when only the
  state axis rejected it, title-free blurred placeholder ("⏰ time-left · 🔒 Private item") when
  the context axis did → OK [design core].
- **A hidden todo crossing into the urgent band over time**: a single-shot boundary timer armed at
  every refresh (earliest `due − WARN_HOURS`, capped 24 h) re-runs refresh(); sleep/resume also
  refreshes (`Shell._on_resume`) → OK [R-A].
- **The blurred countdown going stale**: the placeholder implements the card tick protocol and the
  1 s tick + its gate iterate placeholders too → OK [R-B].
- **Grace × peek collision** (tick done → flip → un-tick): grace-pending ids bypass classification —
  exactly one full card, undo reachable, never counted hidden; on cancel the item re-classifies
  (blurred placeholder if still urgent+cross-context) → OK [R-C].
- **Mis-click on the placeholder during a screen-share**: first click only ARMS a "Switch to
  <ctx>?" prompt (auto-disarms in 3 s); a confirm within the double-click interval is ignored;
  only a deliberate second click flips context → OK [R-D].
- **Due-less urgency (running timer / in-progress)**: dedicated forms ("▶ running" / "● in
  progress"), never "None", never elapsed seconds → OK [R-E].
- **Leak surface**: relative-only time (never absolute clock times), no tooltip/accessibleName,
  no drag affordances on the placeholder → OK [R-F].
- **Mini dock lying "All clear"** while an urgent cross-context todo exists: shows the same
  title-free blurred line (soonest deadline first); clicking it emits the existing context toggle
  (one-click is correct there — the mini IS the toggle surface) → OK [R-H].
- Refuted (recorded): synchronous placeholder self-destruction in its own mouse handler;
  grace-undo-destroyed-on-flip (superseded by R-C).
