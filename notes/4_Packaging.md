# 4 — Packaging (Serenity → native Windows .exe via PyInstaller)

_Created 2026-06-20 on `wf/packaging`. Spec: `../serenity.spec`. Cross-refs: `1_Planning.md` item 5 (PyInstaller smoke-test = top risk), `3_Build_Decisions.md`._

## 1. Overview — what ships

- **ONEDIR** bundle: `dist/Serenity/Serenity.exe` plus a `_internal/` folder (Qt DLLs, plugins, bundled data). Distribute the whole `dist/Serenity/` folder (or wrap it in an installer).
- **Base app only.** The optional AI/voice extras (`llm` / `stt` / `semantic` / `voice` / `power` / `clone`) are **NOT** bundled. The exe degrades gracefully without them (keyword search, deterministic parser, silent TTS). Models/voices download **per-user** at runtime into `%APPDATA%/Serenity` (`voices/`, `models/`), which lives **outside** the bundle.
- Why onedir, not onefile: onefile re-extracts the entire bundle to a temp dir on **every** launch — painful for a tray-resident, always-on-top app the user relaunches often. The per-user model/voice folders are outside the bundle anyway, so onefile buys nothing for them, and onedir lets you inspect/patch the shipped Qt plugin set during verification.

## 2. Windows build steps (Windows ONLY — this repo's WSL/Linux cannot build the exe)

Run from the repo root in a Windows shell:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .            REM base deps: PySide6, dateparser, PyYAML
pip install pyinstaller
pyinstaller serenity.spec   REM add --noconfirm to overwrite a previous dist\
```

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
- [ ] **TTS audio actually plays** — enable voice + drop a `.onnx` into `%APPDATA%/Serenity/voices`; failure ⇒ the multimedia backend (`windowsmediafoundation`) plugin is missing. Also confirm the **silent Noop degrade** when no model is present (no crash).
- [ ] **Single-instance** — a 2nd launch focuses the running instance and does NOT start a second (QSharedMemory `serenity-single-instance`).
- [ ] **Per-user download flow** — `%APPDATA%/Serenity/voices` and `models` dirs are writable from the frozen exe (i.e. `config_dir()`/`voices_dir()` did NOT get pulled into the read-only bundle).
- [ ] **Pure-degrade** — runs with NONE of `llm` / `stt` / `semantic` / `voice` / `power` installed (base exe): keyword search, deterministic parser, silent TTS, no crashes.
- [ ] **Auto-start-to-tray** — enable in Settings, reboot, app comes back in the tray; the HKCU `Run` entry uses the **exe path**, not `-m serenity`.
- [ ] **Blank-window check** — if the window is blank, the `qwindows` platform plugin is missing from `_internal\PySide6\plugins\platforms\`. Fix: force explicit Qt plugin collection (`--collect-all PySide6`, or `collect_data_files`/`collect_dynamic_libs` in the spec). Kept lean by default — only add if the build comes back blank.
