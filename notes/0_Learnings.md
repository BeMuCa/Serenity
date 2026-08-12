# 0 — Learnings

_Design-phase learnings (2026-06). Will grow during implementation._

## Table of contents
1. WSL2 can't host a Windows tray/always-on-top app
2. Local LLM runtime: in-process beats a daemon for a single-user .exe
3. Small models need constrained decoding for valid JSON
4. Local embeddings: avoid PyTorch bloat; mind licenses
5. Notes data model: files + index + embeddings (hybrid)
6. RAG chunking: structure-aware, not blind fixed-size
7. Animated assets: GIF vs WebP
8. Single-active-category time tracking
9. The Protocol-seam + lazy-backend + stub-default degrade pattern
10. Stub-first AI keeps the suite green with zero heavy deps
11. sqlite-vec fast path with a pure-Python cosine fallback
12. The low-RAM-at-idle principle: lazy load + shared-per-process
13. Cosine finds duplicates; containment finds fragments
14. Tag clustering is string-similarity, not embeddings
15. RAG must degrade on every axis (retrieval AND generation)
16. The LLM never writes: validate + merge onto the deterministic baseline
17. Break-time gating: tri-state power probe, fail-safe to "not on AC"
18. One registry, the rest are projections — kill hand-synced duplicate tables
19. Per-context "mood" = one shared Idle + a pose map, not two idle states
20. A persisted settings field is fully untrusted — discard the whole override on any bad row
21. Test isolation: an un-isolated vault leaks a running activity span between tests
22. A warm cache must be marked from the WRITE, not from the intent to write
23. Model size shows up as intent quality, not just fluency (0.6B vs 1.7B)
24. A windowed frozen exe has no stdout — `print()` is fine, `isatty()` is not
25. A QSS `*` colour rule turns every forgotten widget class into white-on-white
26. Wayland forbids self-positioning — anchored UI must be a child widget, not a window
27. Screen y grows downward: an "upper arc" needs +sin, not −sin
28. QPlainTextEdit's documentSize().height() is in LINES, not pixels
29. A test suite inherits the user's real HOME — isolate the vault, not just the config dir
30. Recurrence that clones a todo destroys series identity unless you carry a key

---

### 1. WSL2 can't host a Windows tray/always-on-top app
A system-tray icon that floats over other Windows apps + captures audio must be a **native Windows process**. WSLg apps are sandboxed and have no Windows tray. → Dev in WSL2, but build/run the `.exe` on Windows.

### 2. Local LLM runtime: in-process beats a daemon for a single-user .exe
**in-process `llama-cpp-python` > Ollama** here: no background service/port, one self-contained `.exe`, and the SAME GBNF/json_schema constrained-decoding engine (Ollama is a llama.cpp wrapper). Runtime RAM is similar once a model is loaded — the real wins are "no daemon" + direct in-process JSON control. Cost: PyInstaller native-DLL bundling is fiddly — test the frozen exe early.

### 3. Small models need constrained decoding for valid JSON
Models under ~7B are unreliable at emitting valid JSON by prompting alone. Use **grammar / JSON-schema constrained decoding** (GBNF or `response_format` json_schema). It guarantees schema-shaped TOKENS, not a complete object — set generous max-tokens + Pydantic validate + retry, and validate the grammar at init (fail closed).

### 4. Local embeddings: avoid PyTorch bloat; mind licenses
**fastembed (ONNX, no PyTorch)** keeps the `.exe` lean; store vectors in **sqlite-vec** (same DB file, no extra service). Default model is **paraphrase-multilingual-mpnet-base-v2** (768d, Apache-2.0, best DE+EN), configurable via Settings to a curated preset (MiniLM / multilingual-e5-large) or any fastembed model id. **jina-v3 is CC-BY-NC** → can't ship commercially offline. CORRECTION (real-backend verification): the original `multilingual-e5-base`/`-small` ids are NOT in fastembed's registry, so they raised at load and Meaning search silently degraded to keyword — verify any model id actually loads in fastembed. The `query:`/`passage:` prefixes are e5-ONLY: apply them centrally but conditionally (`needs_e5_prefix`); prefixing a non-e5 model (mpnet/MiniLM) injects noise.

### 5. Notes data model: files + index + embeddings (hybrid)
Not "files OR database" — **both**. Markdown files are the portable source of truth; the app indexes them into SQLite (FTS5 + parsed structured fields) and embeddings. A `## Title` + `- field: value` block is a **reusable table/KB format**: render as table + query structurally + retrieve semantically.

### 6. RAG chunking: structure-aware, not blind fixed-size
Cut at **sense boundaries** (headings / structured blocks), one block = one chunk, with small overlap + provenance metadata (note title + heading path). This avoids "context chaos" far better than fixed-character splitting.

### 7. Animated assets: GIF vs WebP
36% per-frame noise makes every pixel change every frame, so GIF's inter-frame compression can't help (full set ~37 MB). **Animated WebP ~2.5× smaller** at equal quality and **QMovie plays it natively** in PySide6 → prefer WebP. Render the WebP fresh from full-color frames, don't convert from the already-quantized GIF.

### 8. Single-active-category time tracking
Model time tracking as an append-only **event log** (`category, start, end`) with exactly one active entry; clicking a new category closes the old one. Day/week/month breakdowns are then trivial `GROUP BY` queries.

---

_Stage-2 learnings (2026-06). Building the on-device AI behind clean seams._

### 9. The Protocol-seam + lazy-backend + stub-default degrade pattern
Every heavy capability is one shape: a `typing.Protocol` seam (`name` / `available` + the work method) with TWO implementations - a deterministic, dependency-free **Stub** (the default, used by tests + as the always-safe path) and a **real lazy backend** that imports its heavy dep INSIDE its methods and sets `available=False` when the dep/model is absent. `LLMEngine`→`StubLLM`/`LlamaCppLLM`, `Embedder`→`StubEmbedder`/`FastEmbedBackend`, `Transcriber`→`StubTranscriber`/`WhisperTranscriber` all follow it. Callers depend only on the Protocol, so a backend swaps in with zero caller change and absence is a graceful degrade, never a crash.

### 10. Stub-first AI keeps the suite green with zero heavy deps
Because the default of every seam is a deterministic stub, the WHOLE 635-test suite runs with NONE of the `[llm]`/`[semantic]`/`[stt]`/`[power]` extras installed - on stock `sqlite3`, no torch, no ONNX, no model files. The stub's output is stable so a test can assert exact text. Cost: stub-tested ≠ backend-tested - the real backends still need a one-time verification pass on a box that has them (logged in `1_Planning.md`).

### 11. sqlite-vec fast path with a pure-Python cosine fallback
The vector store picks its path at OPEN time: if the `sqlite-vec` extension loads, KNN runs in SQL (the fast path); otherwise it falls back to a pure-Python cosine scan over the same stored vectors. Two layers of degrade above it: no embedder at all → keyword "Text" search. Net: Meaning search works (slower) without the native extension, and the suite needs neither `sqlite-vec` nor `fastembed`.

### 12. The low-RAM-at-idle principle: lazy load + shared-per-process
A personal secretary is resident all day, so nothing heavy may sit in RAM while idle. Each backend loads its model on FIRST use, not at construction, and caches it in a process-wide shared slot (`KokoroEngine._shared`, `FastEmbedBackend._shared`, `LlamaCppLLM._shared`) so the second call is warm without a second copy. Model tiers default SMALL (Qwen3-1.7B, mpnet/MiniLM, Whisper tiny/base) with bigger sizes reachable by a parameter - the always-warm tier stays tiny.

### 13. Cosine finds duplicates; containment finds fragments
Near-duplicate detection (two notes ~the same) is well captured by embedding cosine, but FRAGMENT detection (a short note whose tokens are mostly contained in a longer one) is NOT - containment is a set relation cosine smears. So dedup uses the embedding/cosine path for duplicates (degrading to token-set Jaccard) but ALWAYS uses deterministic token-containment for fragments, in both the model and the degrade path. Merge is recoverable: union tags + append body + soft-delete the dropped note to Trash (never purge) - Trash is the undo.

### 14. Tag clustering is string-similarity, not embeddings
Consolidating variant tags (Work/work/WORK, proj/Proj, plurals, typos) is a SHORT-STRING problem - the note-body embedding index is useless for it. Cluster by a deterministic normalize key (casefold + diacritic-fold + separator-collapse + light singular/plural fold) plus a guarded `difflib` ratio. Over-merge guards matter: short tags (cat/car) must NOT merge, so the ratio path is gated by a min shared prefix + stricter ratio + min length; identical normalized forms bypass the ratio and always merge. Tag edits have NO trash-undo, so the UI must confirm - and the op only ever rewrites `.tags`, is idempotent, and preserves unrelated tags + order.

### 15. RAG must degrade on every axis (retrieval AND generation)
Ask-Your-Vault has two independent heavy parts. Retrieval degrades (semantic index → keyword search) AND generation degrades (no/unavailable LLM → return the retrieved note ids with `answer=None`, and the UI just shows the related notes). Neither absence is a dead end. A warm-cache (mirroring the TTS render cache) precomputes answers for candidate questions and serves one only when the question matches AND the source notes are unchanged (a hash over their content); a drifted source-hash self-invalidates and recomputes.

### 16. The LLM never writes: validate + merge onto the deterministic baseline
Capture routing always runs the deterministic `parse_capture` first to get a baseline, THEN asks the LLM for a small JSON refinement that is validated and MERGED onto that baseline; any LLM/JSON failure degrades to pure `parse_capture`. The model is an enhancer over a guaranteed floor, not the source of truth - so a bad/absent model can never produce a worse capture than the parser, and the result still flows through the confirm + undo path before commit.

### 17. Break-time gating: tri-state power probe, fail-safe to "not on AC"
The break-time scheduler gates maintenance jobs on three injectable signals (on-break/idle, AC power, and a model-TIER policy: LIGHT jobs on a short break, HEAVY jobs only on AC + enough idle). The AC probe (`psutil.sensors_battery().power_plugged`) is lazy + optional and returns a TRI-STATE: True / False / None(unknown). The safe default is to treat unknown as NOT on AC, so a big model never spins up on battery (or when we can't tell). The clock + break/idle + power providers are all injected, so the whole decision is deterministic and unit-tested with no real clock or psutil.

---

_States & Contexts learnings (2026-07). One registry + a global context toggle._

### 18. One registry, the rest are projections — kill hand-synced duplicate tables
Three tables described the SAME activities and were kept in step BY HAND: the mascot's `ACTIVITIES` selector list `(label, key, color)`, the chip's `_ACTIVITY_COLORS` `{label: color}`, and `poses.DEFAULT_STATE_MAP` `{key: [poses]}`. Any add/rename/recolor had to touch all three or they silently drifted. Collapse them into ONE canonical registry (`core/states.py`: frozen `ActivityState{key,label,color,poses,category,context}` + the `DEFAULT_STATES` seed) and make the other three **projections** of it — the selector is `selector_rows(states, context)`, the chip color is `color_for_label(label)`, the pose map is `{s.key: list(s.poses)}` (`poses.DEFAULT_STATE_MAP` / `Settings.state_map()`). One edit point; the consumers can never disagree again. The display `label` stays the log identity (`ActivityEntry.category`), so consolidation needs ZERO data migration.

### 19. Per-context "mood" = one shared Idle + a pose map, not two idle states
The Private↔Business toggle needed a different resting look per context. The tempting model is TWO Idle states; the simpler one is ONE shared Idle activity (`context="any"`, so it shows in both selectors) plus a tiny `CONTEXT_DEFAULT_POSE = {"business": "idle", "private": "chilling"}` map that the flip consults to pick the resting pose-state when nothing is tracked. No duplicate rows, no per-context Idle bookkeeping — the context is just an index into a mood map. The two-idle-states design was explicitly rejected.

### 20. A persisted settings field is fully untrusted — discard the whole override on any bad row
`activity_states` (the registry override) is user-editable JSON on disk, so hand-edits, partial writes and schema drift are all possible. `Settings.states()` treats it as ADVERSARIAL input: every row must be a dict whose keys ⊆ the dataclass fields, with `key`+`label` present and both str, `poses` a sequence of str, and keys unique across rows; ANY violation discards the WHOLE override and falls back to the code default. Never ship a PARTIAL registry — a half-valid list is worse than the clean default. `[]` (the default) means "use the code registry", and nothing is written to disk until the user actually edits (Phase E), so `settings.json` stays clean and the default lives in code. `load()` also HEALS an out-of-range scalar (`current_context` not in business/private → business) so a bad value is never re-persisted on the next `save()`. `state_map()` layers on top: a registry-derived base with the legacy `state_pose_map` applied as a per-KEY overlay (never a whole-dict replace), so a newly-seeded key like `focus` can never be hidden by an old override.

### 21. Test isolation: an un-isolated vault leaks a running activity span between tests
22. A warm cache must be marked from the WRITE, not from the intent to write
23. Model size shows up as intent quality, not just fluency (0.6B vs 1.7B)
24. A windowed frozen exe has no stdout — `print()` is fine, `isatty()` is not
25. A QSS `*` colour rule turns every forgotten widget class into white-on-white
26. Wayland forbids self-positioning — anchored UI must be a child widget, not a window
27. Screen y grows downward: an "upper arc" needs +sin, not −sin
28. QPlainTextEdit's documentSize().height() is in LINES, not pixels
A `Shell` built in a test reads/writes the REAL `<vault>/activity.json`; if a test starts (or restores) a running activity span and the vault path isn't redirected, the NEXT test sees that span still "running" — order-dependent, so mood-pose-only-when-idle assertions then fail nondeterministically. Fix: isolate per-test with `monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")` (alongside `XDG_CONFIG_HOME` for config), so each `Shell` gets a fresh empty vault. Any store that persists to a shared user path needs the same isolation as the config dir, not just the config dir itself.

### 22. A warm cache must be marked from the WRITE, not from the intent to write

The Weekly-Board digest cached "the board I already authored a digest for" by stamping the
signature *before* submitting the job. Once the queue started deduping identical labels, a
submit could be silently dropped — and the stamp claimed the new board while the cached text
still described the old one, permanently. The rule that generalises: a cache key may only
advance on the code path that actually produced the value. If the producing call can fail or
be dropped, it must RETURN that fact and the key must depend on it. (Same shape as the
`refresh()`-during-`__init__` bug next to it: a callback injected *after* construction means
the constructor silently takes the fallback path — inject it as a constructor argument.)

### 23. Model size shows up as intent quality, not just fluency (0.6B vs 1.7B)

Real-backend golden set (10 EN+DE capture utterances, 2026-08-06): `Qwen3-1.7B-Q4_K_M`
scored 10/10 and even upgraded one verdict the deterministic parser got wrong
("morgen 17 Uhr Steuerberater anrufen" → reminder). `Qwen3-0.6B-Q8_0` scored 8/10 — and its
failures were the expensive kind: it *downgraded* the parser's correct `reminder` intent to
`note` in both languages, which would silently disarm the whole reminder ladder. The smaller
model was not less articulate, it was less willing to commit to a structured intent. Two
consequences: keep 1.7B as `DEFAULT_MODEL_FILE`, and remember that "the LLM only refines
intent + title on top of the parser" is a real risk surface, not just a safety story — the
refinement can be a regression.

### 24. A windowed frozen exe has no stdout — `print()` is fine, `isatty()` is not
25. A QSS `*` colour rule turns every forgotten widget class into white-on-white
26. Wayland forbids self-positioning — anchored UI must be a child widget, not a window
27. Screen y grows downward: an "upper arc" needs +sin, not −sin
28. QPlainTextEdit's documentSize().height() is in LINES, not pixels

The installer's optional post-install step runs the *windowed* PyInstaller exe with
`--fetch-models`. In that process `sys.stdout is None`. Verified behaviour: `print()` is a
silent no-op (safe), but any attribute access on the stream — `sys.stdout.isatty()`, which a
progress-bar guard naturally reaches for — raises `AttributeError` and would abort the
download. So: guard the stream, and give a GUI-less process a log file to report into,
because "no output" and "crashed" look identical to the user otherwise.

### 25. A QSS `*` colour rule turns every forgotten widget class into white-on-white

`theme.stylesheet()` opens with `* { color: ink }` (near-white) but sets a *background* only
for the selectors it names. That asymmetry is a trap: every widget class nobody styled keeps
the platform's LIGHT plate and paints near-white text on it. It is not "slightly unstyled",
it is invisible. Found in the wild across the Settings tab bar, plain `QPushButton`s in every
dialog, `QMessageBox`, tooltips, `QCheckBox::indicator` (a white square, and checked looked
identical to unchecked) and the horizontal `QScrollBar` (only `:vertical` had rules). Two
durable rules: (a) a theme that colours text globally MUST define a background floor for
every container it can reach, and sub-controls (`::indicator`, `::up-button`, `::drop-down`,
`::tab`) count as separate classes; (b) top-level windows inherit NOTHING — `mini_window`
and `expanded_panel` set `stylesheet()` + `objectName("dock")` themselves, and any new
window must too. The only test that catches this renders the widget and reads its pixels.

### 26. Wayland forbids self-positioning — anchored UI must be a child widget, not a window

Under WSLg the dock lands wherever the compositor likes: `platform_win.dock_right()` calls
`setGeometry()`, and on Wayland a client simply cannot place its own surface (X11 and Windows
can). Consequences beyond the dock: any "popup anchored to a button" implemented as a window
is unplaceable there, and `QT_QPA_PLATFORM=xcb` is not an escape hatch (it core-dumps in this
setup). So the Quick-todo bubble is a CHILD WIDGET of the dock, positioned in parent
coordinates — no frame, no compositor involvement, and it works identically on both
platforms. Worth remembering before designing any other anchored surface.

### 27. Screen y grows downward: an "upper arc" needs +sin, not −sin

The activity ring placed its bubbles with `by = cy - radius_y * sin(angle)` over 200°–340°.
Across that range `sin` is negative, so subtracting it moved every bubble DOWN — the
"upper arc" the comment described was actually below the widget, and six of eight bubbles
were clipped away. The user's report was "Serenity's states are gone". Two lessons: mixing
math-convention angles with screen coordinates needs the sign checked against a real render,
and a one-sided clamp (`max(4, by)`) hides exactly half of such a bug — clamp both edges.

### 28. QPlainTextEdit's documentSize().height() is in LINES, not pixels

Building a text field that grows with its content: `QTextEdit`'s document layout reports
`documentSize()` in pixels, but `QPlainTextDocumentLayout` reports the HEIGHT IN LINES. The
same "divide by lineSpacing" code that works for one silently collapses every length to a
single line in the other. Verified by printing it (`documentSize()` was 9.0 for nine wrapped
lines with a 14px line height).

### 29. A test suite inherits the user's real HOME — isolate the vault, not just the config dir

After the suite was caught overwriting `~/.config/serenity/settings.json`, `conftest.py`
redirected `XDG_CONFIG_HOME`/`APPDATA` — and the leak continued through a second door. Any
test that builds a real `Shell()` gets `Settings.vault_path` defaulted to
`paths.default_vault_dir()`, which is `Path.home() / "SerenityVault"`. So Shell tests wrote
protocol notes and todos straight into the real vault, and the suite indexed the user's own
notes with the embedding model (a ~1 min test and a fastembed warning were the only visible
symptoms). `Path.home()` reads `HOME`, so the fix is to redirect `HOME`/`USERPROFILE` in the
same session fixture. The general lesson: enumerate EVERY path the app derives from the
environment before declaring an isolation leak closed — config, data, cache, and anything
hanging off the home directory. And prove it with a checksum of a real user file taken
before and after a full run, not by reading the fixture.

### 30. Recurrence that clones a todo destroys series identity unless you carry a key

`TodoStore._spawn_recurrence` builds a fresh `Todo` with a NEW id and deliberately drops
`ics_uid`/`linked_note_ids` ("a new occurrence is a new event identity"). Correct for an
occurrence — but it means a weekly meeting has NO thread linking its occurrences, so
"the previous occurrence's protocol" is simply not derivable from the data. Meeting-Prep
needed one optional field (`series_id`, seeded from the first occurrence's own id and
carried forward) to make the chain exist. Worth checking early in any feature that reasons
across occurrences of a recurring thing: the recurrence may be producing strangers, not
siblings. The fallback matters too — a topic search still finds older protocols that predate
the key, and the prep states which route it used so a fuzzy match is visible, not silent.
