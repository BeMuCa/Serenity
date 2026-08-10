"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: App entry point - boot the Qt app, enforce single instance, show the shell.
Role:    `python -m serenity`. Creates the QApplication, keeps it tray-resident
         (does not quit on last window closed), and focuses an existing instance on
         a second launch via QSharedMemory.

Functions:
- main() -> int - the program entry point (--fetch-models delegates to the downloader)
============================================================
"""

from __future__ import annotations

import sys

FETCH_FLAG = "--fetch-models"


def main() -> int:
    # Setup mode, before any Qt import: the frozen exe has no python CLI, so this flag is
    # the only way an INSTALLED Serenity can pull its models (installer post-install step /
    # `Serenity.exe --fetch-models`). Everything after the flag is passed straight through.
    if FETCH_FLAG in sys.argv:
        from .fetch_models import main as fetch_main
        return fetch_main(sys.argv[sys.argv.index(FETCH_FLAG) + 1:])

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

    from .ui.platform_win import AUTOSTART_FLAG
    from .ui.shell import Shell

    # The autostart Run-key command carries --autostarted (see platform_win.set_autostart),
    # so a login launch greets with the boot line; a manual open uses the normal greeting.
    booted = AUTOSTART_FLAG in sys.argv
    shell = Shell(boot=booted)
    shell.show()
    rc = app.exec()
    shared.detach()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
