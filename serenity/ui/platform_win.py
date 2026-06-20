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
- set_autostart(enabled, exe_cmd) -> bool - HKCU Run key (Windows only)
- get_autostart() -> bool
============================================================
"""

from __future__ import annotations

import sys

APP_RUN_KEY = "Serenity"


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


def set_autostart(enabled: bool, exe_cmd: str | None = None) -> bool:
    """Register/unregister run-on-login. Windows: HKCU Run key. No-op elsewhere."""
    if not is_windows():
        return False
    try:
        import winreg  # type: ignore

        # Frozen (PyInstaller exe): sys.executable IS Serenity.exe, so `-m serenity`
        # is invalid — register the bare exe path. Dev: launch the module.
        if exe_cmd:
            cmd = exe_cmd
        elif getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}"'
        else:
            cmd = f'"{sys.executable}" -m serenity'
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
