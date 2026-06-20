# ============================================================
# Author:  Berk
# Created: 2026-06-20
# Purpose: PyInstaller entry script — a thin top-level runner for the frozen exe.
# Role:    The .spec points Analysis at THIS file, not serenity/__main__.py.
#          PyInstaller compiles the entry script as the top-level module __main__
#          with NO package context (__package__ == ""), so the relative import in
#          serenity/__main__.py (`from .ui.shell import Shell`) would raise
#          "attempted relative import with no known parent package" and the exe
#          would crash on launch. Importing main() from the serenity package keeps
#          full package context. `python -m serenity` still works unchanged via
#          serenity/__main__.py.
# ============================================================

from serenity.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
