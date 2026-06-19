"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: App entry point - boot the Qt app, enforce single instance, show the shell.
Role:    `python -m serenity`. Creates the QApplication, keeps it tray-resident
         (does not quit on last window closed), and focuses an existing instance on
         a second launch via QSharedMemory.

Functions:
- main() -> int - the program entry point
============================================================
"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtCore import QSharedMemory
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Serenity")
    app.setOrganizationName("Serenity")
    # tray-resident: closing the dock hides it, it does not quit the app
    app.setQuitOnLastWindowClosed(False)

    # single instance guard (second launch exits; the running one keeps going).
    # On Unix a System V segment outlives a crashed process, which would make the
    # app permanently unlaunchable; attach+detach first to clear any stale segment
    # an earlier crash left behind, then try to claim it.
    shared = QSharedMemory("serenity-single-instance")
    if shared.attach():
        shared.detach()
    if not shared.create(1):
        print("Serenity is already running.")
        return 0

    from .ui.shell import Shell

    shell = Shell()
    shell.show()
    rc = app.exec()
    shared.detach()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
