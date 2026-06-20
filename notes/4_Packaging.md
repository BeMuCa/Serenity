# 4 — Packaging (Serenity → native Windows .exe via PyInstaller)

_Created 2026-06-20 on `wf/packaging`. Spec: `../serenity.spec`. Cross-refs: `1_Planning.md` item 5 (PyInstaller smoke-test = top risk), `3_Build_Decisions.md`._

## 1. Overview — what ships

- **ONEDIR** bundle: `dist/Serenity/Serenity.exe` plus a `_internal/` folder (Qt DLLs, plugins, bundled data). Distribute the whole `dist/Serenity/` folder (or wrap it in an installer).
- **Voice ships in (FULL build); heavy AI extras do not.** The lightweight, no-PyTorch voice runtimes — Kokoro (`kokoro-onnx` on `onnxruntime`, all English voices) + Piper (German neural ONNX) + `soundfile` — are bundled **inside** the exe via guarded `collect_all` in `serenity.spec`, so TTS works on a fresh machine with no pip step (USER DECISION: bundling Option A). The heavy/optional extras (`llm` / `stt` / `semantic` / `power` / `clone`-torch) are **NOT** bundled — the exe degrades gracefully without them (keyword search, deterministic parser). The voice *models* themselves (Kokoro's `kokoro-v1.0.onnx` + `voices-v1.0.bin`, Piper `.onnx` voices) still download **per-user** at runtime into `%APPDATA%/Serenity/voices`, which lives **outside** the bundle — only the runtime code ships in the exe. **SAPI5/pyttsx3 is dropped** from the shipped voice set (Kokoro + Piper cover EN + DE; SAPI sounds robotic). A **BASE build** that skips `requirements-voice.txt` still works: the guarded `collect_all` finds nothing to bundle and the exe falls back to silent TTS.
- Why onedir, not onefile: onefile re-extracts the entire bundle to a temp dir on **every** launch — painful for a tray-resident, always-on-top app the user relaunches often. The per-user model/voice folders are outside the bundle anyway, so onefile buys nothing for them, and onedir lets you inspect/patch the shipped Qt plugin set during verification.

## 2. Windows build steps (Windows ONLY — this repo's WSL/Linux cannot build the exe)

Run from the repo root in a Windows shell:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .                          REM base deps: PySide6, dateparser, PyYAML
pip install -r requirements-voice.txt     REM FULL build: bundle Kokoro + Piper + soundfile (no torch)
pip install pyinstaller
pyinstaller serenity.spec                  REM add --noconfirm to overwrite a previous dist\
```

- The `pip install -r requirements-voice.txt` step is what makes the **FULL** build bundle voice out of the box: the spec's guarded `collect_all('kokoro_onnx'|'soundfile'|'piper'|'onnxruntime'|'espeakng_loader'|'phonemizer')` pulls each runtime's native DLLs, package data and submodules into the exe. Skip that one line for a **BASE** build — the guards simply find nothing to bundle and the exe ships with silent TTS. (Do **not** install `requirements-voice.txt`'s Chatterbox/torch line for the bundle — the `clone` extra stays optional and per-user; `collect_all` never touches torch.)
- Output: `dist\Serenity\Serenity.exe` (+ `dist\Serenity\_internal\`).
- `build\` and `dist\` are already git-ignored.
- Do **not** build on Linux/WSL — PyInstaller produces a host-OS binary; a Windows exe requires a real Windows box.

## 3. Auto-start-to-tray

- The app already registers an HKCU `Run` entry via `serenity/ui/platform_win.py::set_autostart()` (toggled in Settings → autostart). It stays in the tray (`setQuitOnLastWindowClosed(False)`).
- **Frozen-mode fix (done on this branch):** when `sys.frozen` is set, `set_autostart()` registers the **bare exe path** (`"C:\path\to\Serenity.exe"`), NOT `"{sys.executable}" -m serenity`. In a frozen exe `sys.executable` IS `Serenity.exe`, so `-m serenity` would fail. Dev mode still launches the module.
- For an installer, register `"C:\path\to\Serenity.exe"` under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (value name `Serenity`).

## 4. Bundle-layout contract (paths.py ⇄ serenity.spec)

The `datas` in `serenity.spec` place `serenity/assets` → `assets` and `serenity/data` → `data` at the **bundle root** (= `sys._MEIPASS`), giving:

```
<bundle root = sys._MEIPASS>/
  assets/poses/*.webp
  data/voice_lines.json
```

`serenity/core/paths.py::_bundle_root()` returns `Path(sys._MEIPASS)` when frozen and reads `assets/` + `data/` from there; otherwise it falls back to the source package root (dev / pip). `config_dir()`, `voices_dir()`, `default_vault_dir()` stay **per-user writable** and are NOT moved into the bundle. **If you change one side of this contract, change the other.**

## 5. Icon

No `.ico` exists today (`img/` and `current_Imgs/` hold only `.png` / `.gif` / `.webp`; PyInstaller needs `.ico` on Windows), so `serenity.spec` sets `icon=None` and the exe gets the default PyInstaller icon — fine for the first smoke-test. To add one later:

```python
from PIL import Image
Image.open('img/serenity_happy.png').save('serenity.ico')  # use a 256px source
```

then set `icon='serenity.ico'` in the `EXE(...)` block of `serenity.spec`.

## 6. Native-verification checklist (Windows ONLY — cannot be ticked from WSL/Linux)

Each item lists the failure symptom and which spec/plugin gap it points back to.

- [ ] **Tray icon + context menu** — icon appears; menu (Full / Mini / Hidden, Settings, Quit) works.
- [ ] **Frameless always-on-top dock** — pinned to the right edge, full height.
- [ ] **Mini-dock mode** — toggles via the tray radio and the title-bar control.
- [ ] **Mascot WebP poses animate** — failure ⇒ `imageformats/qwebp` plugin missing from `_internal\PySide6\plugins\imageformats\`.
- [ ] **SVG icons render** (title-bar / tab icons) — failure ⇒ `QtSvg` / `iconengines\qsvgicon` or `imageformats\qsvg` missing.
- [ ] **TTS audio actually plays** — enable voice + drop a `.onnx` into `%APPDATA%/Serenity/voices`; failure ⇒ the FFmpeg multimedia backend is missing. On PySide6 6.11 QtMultimedia defaults to FFmpeg (NOT Windows Media Foundation), so look for `_internal\PySide6\plugins\multimedia\ffmpegmediaplugin.dll` and its FFmpeg DLLs (`avcodec-*.dll`, `avformat-*.dll`, `avutil-*.dll`, `swresample-*.dll`, `swscale-*.dll`). The spec collects these via `collect_dynamic_libs('PySide6')` (see §7). Also confirm the **silent Noop degrade** when no model is present (no crash).
- [ ] **Single-instance** — a 2nd launch focuses the running instance and does NOT start a second (QSharedMemory `serenity-single-instance`).
- [ ] **Per-user download flow** — `%APPDATA%/Serenity/voices` and `models` dirs are writable from the frozen exe (i.e. `config_dir()`/`voices_dir()` did NOT get pulled into the read-only bundle).
- [ ] **Pure-degrade** — runs with NONE of `llm` / `stt` / `semantic` / `voice` / `power` installed (base exe): keyword search, deterministic parser, silent TTS, no crashes.
- [ ] **Auto-start-to-tray** — enable in Settings, reboot, app comes back in the tray; the HKCU `Run` entry uses the **exe path**, not `-m serenity`.
- [ ] **Blank-window check** — if the window is blank, the `qwindows` platform plugin is missing from `_internal\PySide6\plugins\platforms\`. Fix: force explicit Qt plugin collection (`--collect-all PySide6`, or `collect_data_files`/`collect_dynamic_libs` in the spec). Kept lean by default — only add if the build comes back blank.

## 7. Post-build binary checks (do these right after `pyinstaller serenity.spec`, before the runtime checklist)

These catch the silent-failure cases by inspecting `dist\Serenity\_internal\` — no need to run the app first.

- **Multimedia backend present** — confirm `_internal\PySide6\plugins\multimedia\ffmpegmediaplugin.dll` exists, and the FFmpeg DLLs `avcodec-*.dll`, `avformat-*.dll`, `avutil-*.dll`, `swresample-*.dll`, `swscale-*.dll` are in `_internal\` (or `_internal\PySide6\`). The spec's `binaries = collect_dynamic_libs('PySide6')` is there specifically so these can't be silently dropped; if any are still missing, rebuild with `--collect-all PySide6`. (Silent TTS with no crash is the symptom of this gap — see the TTS checklist item.)
- **Platform + image plugins present** — `_internal\PySide6\plugins\platforms\qwindows.dll` (else blank window) and `_internal\PySide6\plugins\imageformats\qwebp.dll` + `qsvg.dll` (else no mascot poses / no SVG icons).

## 8. Entry point — why the spec uses `serenity_launch.py`, not `serenity/__main__.py`

PyInstaller compiles the Analysis entry script and runs it as the top-level module `__main__` with **no package context** (`__package__ == ""`). `serenity/__main__.py` does a relative import (`from .ui.shell import Shell`), which raises `ImportError: attempted relative import with no known parent package` in that context — the exe would crash immediately on launch. The spec therefore points `Analysis` at the top-level `serenity_launch.py`, which does `from serenity.__main__ import main` (absolute, full package context) and calls it. `python -m serenity` is unaffected — it still runs `serenity/__main__.py` with proper package context. `serenity` is also in `hiddenimports` so the package is collected.
