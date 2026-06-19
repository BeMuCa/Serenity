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
