"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Windows-only window behaviors (dock to right edge, autostart), guarded.
Role:    Isolates the platform-specific calls so the shell stays portable. Every
         function degrades to a no-op (returning False) on non-Windows so the app
         still IMPORTS and RUNS on Linux/WSL for dev. The real docking + autostart
         only take effect on Windows.

Functions:
- is_windows() -> bool
- dock_right(window, width) -> bool - position the frameless window at the right edge
- dock_left_of(panel, anchor, width) -> bool - place a panel flush LEFT of an anchor, full
  height of the anchor's current screen, left-clamped so its header stays on-screen
- set_autostart(enabled, exe_cmd) -> bool - HKCU Run key (Windows only); the registered
  command carries the --autostarted sentinel so the boot launch greets differently
- get_autostart() -> bool
- is_resume_message(msg_type, wparam) -> bool - pure test of a WM_POWERBROADCAST resume
============================================================
"""

from __future__ import annotations

import sys

APP_RUN_KEY = "Serenity"

# Sentinel appended to the registered autostart command so the boot launch can tell it
# was started on login (greet with the boot line) versus a manual open. __main__ reads it.
AUTOSTART_FLAG = "--autostarted"

# Win32 power-broadcast message + the resume sub-events we re-greet on. WM_POWERBROADCAST
# fires with one of these in wParam when the machine wakes from standby/hibernate.
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMESUSPEND = 0x07      # resume from a normal suspend
PBT_APMRESUMEAUTOMATIC = 0x12    # automatic wake (the system woke itself)
_RESUME_EVENTS = (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC)


def is_resume_message(msg_type: int, wparam: int) -> bool:
    """Pure predicate: is this native event a wake-from-standby/resume?

    Kept free of any Qt/ctypes/Windows imports so the shell's nativeEvent handler is a thin
    guarded wrapper and the actual decision is unit-testable headlessly on Linux."""
    return msg_type == WM_POWERBROADCAST and wparam in _RESUME_EVENTS


def is_windows() -> bool:
    return sys.platform.startswith("win")


def dock_right(window, width: int) -> bool:
    """Place the window flush against the right edge of the primary screen, full height.

    Works cross-platform via Qt geometry (no AppBar reservation in Phase 1). Returns
    True if positioned. The always-on-top + frameless flags are set on the window
    itself in the shell; this only handles placement."""
    try:
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.availableGeometry()
        window.setGeometry(geo.right() - width + 1, geo.top(), width, geo.height())
        return True
    except Exception:
        return False


def dock_left_of(panel, anchor, width: int | None = None) -> bool:
    """Place `panel` flush against the LEFT edge of `anchor`, full height of the anchor's screen.

    Mirrors dock_right but anchors to the anchor's *current* screen (not always the primary)
    so the pop-out follows the dock to whichever monitor it lives on. The left edge is clamped
    to the screen and the width reduced when the requested width would run off-screen, keeping
    the header/close on-screen (P2-13). Returns True if positioned, False (no-op) on any error
    so a missing/torn-down anchor can never crash the open. Frameless/always-on-top flags live
    on the panel itself; this only handles placement."""
    try:
        from PySide6.QtGui import QGuiApplication
        screen = anchor.screen() or QGuiApplication.screenAt(
            anchor.frameGeometry().topLeft()
        ) or QGuiApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.availableGeometry()
        if width is None:
            width = panel.width()
        anchor_left = anchor.frameGeometry().left()
        left = anchor_left - width
        # clamp the left edge to the screen, reducing width so the right edge still meets the
        # anchor (header/close stay visible even when the gap is narrower than the request).
        if left < geo.left():
            left = geo.left()
            width = anchor_left - geo.left()
        panel.setGeometry(left, geo.top(), width, geo.height())
        return True
    except Exception:
        return False


def set_autostart(enabled: bool, exe_cmd: str | None = None) -> bool:
    """Register/unregister run-on-login. Windows: HKCU Run key. No-op elsewhere."""
    if not is_windows():
        return False
    try:
        import winreg  # type: ignore

        # Frozen (PyInstaller exe): sys.executable IS Serenity.exe, so `-m serenity`
        # is invalid — register the bare exe path. Dev: launch the module. Either way the
        # --autostarted sentinel is appended so the login launch greets with the boot line.
        if exe_cmd:
            cmd = exe_cmd
        elif getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}" {AUTOSTART_FLAG}'
        else:
            cmd = f'"{sys.executable}" -m serenity {AUTOSTART_FLAG}'
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            winreg.SetValueEx(key, APP_RUN_KEY, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_RUN_KEY)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def get_autostart() -> bool:
    if not is_windows():
        return False
    try:
        import winreg  # type: ignore

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, APP_RUN_KEY)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
