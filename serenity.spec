# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# Author:  Berk
# Created: 2026-06-20
# Purpose: PyInstaller build spec for Serenity — a windowed (no console),
#          ONEDIR PySide6 desktop app shipped as a native Windows .exe.
# Role:    Single source of truth for how the exe is assembled. Bundles the
#          read-only assets/ (mascot WebP poses) and data/ (voice_lines.json)
#          at the bundle root so serenity.core.paths._bundle_root() (which reads
#          them under sys._MEIPASS when frozen) finds them. The OPTIONAL heavy
#          extras (llm/stt/semantic/voice/power/clone) are NOT bundled — the base
#          exe degrades gracefully and models download per-user at runtime into
#          %APPDATA%/Serenity. Build steps + verification: notes/4_Packaging.md.
#
# Build (Windows only — WSL/Linux cannot build this):
#   pip install -e .  &&  pip install pyinstaller  &&  pyinstaller serenity.spec
# Output: dist/Serenity/Serenity.exe  (+ dist/Serenity/_internal/)
# ============================================================

# ONEDIR over onefile: faster startup (onefile re-extracts the whole bundle to a
# temp dir on every launch — painful for a tray-resident app relaunched often),
# the per-user model/voice folders live outside the bundle anyway, and the shipped
# Qt plugin set is easy to inspect/patch during Windows verification.

# BUNDLE-LAYOUT CONTRACT with serenity/core/paths.py::_bundle_root():
# datas land assets/ and data/ at the bundle ROOT (= sys._MEIPASS), giving
# assets/poses/*.webp and data/voice_lines.json. Do NOT use a 'serenity/' prefix
# here — paths.py expects them at the root. Change one, change both.
datas = [
    ('serenity/assets', 'assets'),
    ('serenity/data', 'data'),
]

# PySide6 (6.11) ships official PyInstaller hooks that auto-collect the Qt plugins
# (platforms/qwindows, imageformats/qwebp + qsvg, multimedia backend, etc.) and
# QML/translations. The spec stays lean and relies on that hook. These two modules
# are lazy-imported inside functions (`from PySide6.QtMultimedia import ...`), which
# static analysis can miss — list them as cheap insurance so Analysis pulls them
# (and their backend plugins) in:
#   QtMultimedia -> tts.py + mascot_stage.py; TTS audio is silent without it.
#   QtSvg        -> icons.py uses QSvgRenderer for title-bar/tab icons.
hiddenimports = [
    'PySide6.QtMultimedia',
    'PySide6.QtSvg',
]

# tkinter is unused; trimming it shrinks the bundle. Do NOT exclude the optional
# llm/stt/semantic/voice extras — they simply aren't installed in the base build,
# so Analysis won't find them; there is nothing to exclude.
excludes = ['tkinter']


a = Analysis(
    ['serenity/__main__.py'],   # entry point == `python -m serenity`
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # ONEDIR: binaries collected by COLLECT below
    name='Serenity',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX can corrupt Qt DLLs / trip antivirus
    console=False,              # windowed GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon: OMITTED — no .ico exists (img/ + current_Imgs/ are .png/.gif/.webp only,
    # and PyInstaller needs .ico on Windows). To add one, convert a 256px pose PNG to
    # serenity.ico (e.g. Pillow: Image.open('img/serenity_happy.png').save('serenity.ico'))
    # and set icon='serenity.ico'. See notes/4_Packaging.md.
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Serenity',
)
