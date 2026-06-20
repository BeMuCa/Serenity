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

---

### 1. WSL2 can't host a Windows tray/always-on-top app
A system-tray icon that floats over other Windows apps + captures audio must be a **native Windows process**. WSLg apps are sandboxed and have no Windows tray. → Dev in WSL2, but build/run the `.exe` on Windows.

### 2. Local LLM runtime: in-process beats a daemon for a single-user .exe
**in-process `llama-cpp-python` > Ollama** here: no background service/port, one self-contained `.exe`, and the SAME GBNF/json_schema constrained-decoding engine (Ollama is a llama.cpp wrapper). Runtime RAM is similar once a model is loaded — the real wins are "no daemon" + direct in-process JSON control. Cost: PyInstaller native-DLL bundling is fiddly — test the frozen exe early.

### 3. Small models need constrained decoding for valid JSON
Models under ~7B are unreliable at emitting valid JSON by prompting alone. Use **grammar / JSON-schema constrained decoding** (GBNF or `response_format` json_schema). It guarantees schema-shaped TOKENS, not a complete object — set generous max-tokens + Pydantic validate + retry, and validate the grammar at init (fail closed).

### 4. Local embeddings: avoid PyTorch bloat; mind licenses
**multilingual-e5-base** via **fastembed (ONNX, no PyTorch)** keeps the `.exe` lean and has solid German retrieval; store vectors in **sqlite-vec** (same DB file, no extra service). **BGE-M3** (MIT) is a strong alt with 8192-token context + hybrid search. **jina-v3 is CC-BY-NC** → can't ship commercially offline. (e5 requires `query:`/`passage:` prefixes — enforce centrally.)

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
Every heavy capability is one shape: a `typing.Protocol` seam (`name` / `available` + the work method) with TWO implementations - a deterministic, dependency-free **Stub** (the default, used by tests + as the always-safe path) and a **real lazy backend** that imports its heavy dep INSIDE its methods and sets `available=False` when the dep/model is absent. `LLMEngine`→`StubLLM`/`LlamaCppLLM`, `Embedder`→`StubEmbedder`/`E5Embedder`, `Transcriber`→`StubTranscriber`/`WhisperTranscriber` all follow it. Callers depend only on the Protocol, so a backend swaps in with zero caller change and absence is a graceful degrade, never a crash.

### 10. Stub-first AI keeps the suite green with zero heavy deps
Because the default of every seam is a deterministic stub, the WHOLE 635-test suite runs with NONE of the `[llm]`/`[semantic]`/`[stt]`/`[power]` extras installed - on stock `sqlite3`, no torch, no ONNX, no model files. The stub's output is stable so a test can assert exact text. Cost: stub-tested ≠ backend-tested - the real backends still need a one-time verification pass on a box that has them (logged in `1_Planning.md`).

### 11. sqlite-vec fast path with a pure-Python cosine fallback
The vector store picks its path at OPEN time: if the `sqlite-vec` extension loads, KNN runs in SQL (the fast path); otherwise it falls back to a pure-Python cosine scan over the same stored vectors. Two layers of degrade above it: no embedder at all → keyword "Text" search. Net: Meaning search works (slower) without the native extension, and the suite needs neither `sqlite-vec` nor `fastembed`.

### 12. The low-RAM-at-idle principle: lazy load + shared-per-process
A personal secretary is resident all day, so nothing heavy may sit in RAM while idle. Each backend loads its model on FIRST use, not at construction, and caches it in a process-wide shared slot (`KokoroEngine._shared`, `E5Embedder._shared`, `LlamaCppLLM._shared`) so the second call is warm without a second copy. Model tiers default SMALL (Qwen3-1.7B, e5-base/small, Whisper tiny/base) with bigger sizes reachable by a parameter - the always-warm tier stays tiny.

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
