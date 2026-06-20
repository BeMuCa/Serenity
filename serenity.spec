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

from PyInstaller.utils.hooks import collect_dynamic_libs

# BUNDLE-LAYOUT CONTRACT with serenity/core/paths.py::_bundle_root():
# datas land assets/ and data/ at the bundle ROOT (= sys._MEIPASS), giving
# assets/poses/*.webp and data/voice_lines.json. Do NOT use a 'serenity/' prefix
# here — paths.py expects them at the root. Change one, change both.
datas = [
    ('serenity/assets', 'assets'),
    ('serenity/data', 'data'),
]

# Belt-and-suspenders for the QtMultimedia backend. On PySide6 6.11 QtMultimedia
# defaults to the FFmpeg backend: the multimedia plugin is ffmpegmediaplugin and it
# depends on bundled FFmpeg shared libs (avcodec/avformat/avutil/swresample/swscale;
# on Windows the avcodec-*.dll etc. under PySide6\Qt\bin). The PySide6 hook normally
# collects these, but plugin/DLL collection for QtMultimedia is historically the
# most fragile part — and if it's silently dropped the exe still launches and ONLY
# TTS audio is broken (no crash, hardest thing to debug remotely). Explicitly
# collecting PySide6's dynamic libs guarantees the av*/sw* DLLs ride along.
binaries = collect_dynamic_libs('PySide6')

# PySide6 (6.11) ships official PyInstaller hooks that auto-collect the Qt plugins
# (platforms/qwindows, imageformats/qwebp + qsvg, multimedia backend, etc.) and
# QML/translations. The spec stays lean and relies on that hook, plus the explicit
# binaries safety net below. The two QtMultimedia/QtSvg hints:
#   QtMultimedia -> genuinely lazy: imported INSIDE methods (tts.py::_play,
#     mascot_stage.py::_play), which PyInstaller's static analysis can miss. Needs
#     the hiddenimport hint. TTS audio is silent without it AND its backend plugin.
#   QtSvg        -> imported at MODULE level in serenity/ui/icons.py:19
#     (`from PySide6.QtSvg import QSvgRenderer`), so static analysis already follows
#     it — this entry is purely defensive insurance for the QtSvg plugin/dll, not
#     because the import is missed.
# `serenity` is listed so the package itself is collected when Analysis is pointed
# at the top-level launcher (serenity_launch.py), which imports it.
hiddenimports = [
    'PySide6.QtMultimedia',
    'PySide6.QtSvg',
    'serenity',
]

# tkinter is unused; trimming it shrinks the bundle. Do NOT exclude the optional
# llm/stt/semantic/voice extras — they simply aren't installed in the base build,
# so Analysis won't find them; there is nothing to exclude.
excludes = ['tkinter']


a = Analysis(
    # Entry script is the top-level launcher, NOT serenity/__main__.py. PyInstaller
    # runs the entry script as __main__ with no package context, so __main__.py's
    # relative import (`from .ui.shell import Shell`) would crash the exe on launch.
    # serenity_launch.py imports the package's main() with full package context.
    # `python -m serenity` still uses serenity/__main__.py and is unaffected.
    ['serenity_launch.py'],
    pathex=[],
    binaries=binaries,
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
