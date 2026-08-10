"""
============================================================
Author:  Berk
Created: 2026-08-10
Purpose: Dev-only visual harness - boot the real Shell headlessly, drive it into named
         scenes, and write a PNG of each so the UI can be LOOKED at (white-on-white,
         clipped widgets and elided labels are invisible to logic tests).
Role:    Not shipped and never imported by the app. Run it from the repo root:
             .venv/bin/python tools/uishot.py [scene ...] [--out DIR]
         With no scene names it renders all of them. Config and vault are redirected to a
         temp dir, so a run can never touch real settings, notes or models.

Functions:
- scenes() - the scene registry: name -> callable(ctx) -> widget to grab
- seed(shell) - believable demo todos / notes / activity / diary lines
- main(argv) - parse args, boot the shell, render each scene, print a summary table
============================================================
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = Path(tempfile.mkdtemp(prefix="serenity-uishot-"))
os.environ["XDG_CONFIG_HOME"] = str(_TMP / "cfg")

from serenity.core import paths  # noqa: E402

paths.default_vault_dir = lambda: _TMP / "vault"

from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.activity import ActivityEntry, ActivityLog  # noqa: E402
from serenity.core.diary import DiaryLine  # noqa: E402
from serenity.core.llm_queue import LlmJob  # noqa: E402
from serenity.core.models import SubTask, Todo  # noqa: E402
from serenity.ui import platform_win  # noqa: E402

platform_win.set_autostart = lambda *a, **k: False


def seed(sh) -> None:
    """Demo content: enough to make every surface show something real."""
    now = datetime.now()
    mon = (now - timedelta(days=now.weekday())).replace(hour=9, minute=0, second=0, microsecond=0)
    ts = sh.todo_store
    a = ts.add(Todo(title="Ship the LLM job queue", due=now + timedelta(hours=3),
                    category="Development", tags=["serenity", "infra"], context="business",
                    state_tag="development",
                    subtasks=[SubTask(text="3-pass QA", done=True),
                              SubTask(text="open PR #9", done=True),
                              SubTask(text="native verify on Windows", done=False)]))
    b = ts.add(Todo(title="Call the accountant", due=now + timedelta(days=1, hours=2),
                    category="Admin", tags=["invoice"], context="business", state_tag="admin"))
    # a real dependency edge, so the graph has something to draw
    c = ts.add(Todo(title="Send the signed contract", due=now + timedelta(days=2),
                    category="Admin", context="business", state_tag="admin",
                    depends_on=[b.id]))
    ts.add(Todo(title="Renew the gym membership", due=now + timedelta(days=4),
                context="private", state_tag="chilling", tags=["health"]))
    ts.add(Todo(title="Take out the trash", recurring="every monday", context="private",
                state_tag="chilling"))
    done = ts.add(Todo(title="Write the release notes", category="Writing",
                       context="business", state_tag="development"))
    ts.complete(done.id)
    ts.save()

    ns = sh.note_store
    ns.create(title="Airport parking", body="Parked on level 3, spot C14.\n\n#travel",
              tags=["travel"])
    ns.create(title="Standup 2026-08-10",
              body="- queue QA done\n- downloader verified\n- next: Windows box\n\n#work",
              tags=["work"])
    ns.create(title="Piper voices",
              body="`de_DE-kerstin-low` (DE), `en_US-amy-medium` (EN).", tags=["setup"])

    sh.activity_store._log = ActivityLog([
        ActivityEntry("Development", mon, mon + timedelta(hours=3, minutes=20)),
        ActivityEntry("Admin", mon + timedelta(days=1, hours=1), mon + timedelta(days=1, hours=2)),
        ActivityEntry("Writing", mon + timedelta(days=2), mon + timedelta(days=2, hours=1)),
        ActivityEntry("Development", mon + timedelta(days=3), mon + timedelta(days=3, hours=4)),
    ])
    sh.activity_store.save()

    ds = sh.diary_store
    ds.add(DiaryLine(ts=mon, text="Queue finally drains without freezing the dock.",
                     state_tag="development", context="business"))
    ds.add(DiaryLine(ts=mon + timedelta(days=3, hours=6),
                     text="Downloader pulled the 1.7B model in under two minutes.",
                     state_tag="development", context="business"))
    ds.save()
    sh.todos_view.refresh()          # switch_tab only refreshes trash/graph/board/calendar
    sh.notes_view.refresh()


def _tab(key):
    def scene(sh, app):
        sh.switch_tab(key)
        app.processEvents()
        return sh
    return scene


def _ring(sh, app):
    sh.mascot.open_selector()
    app.processEvents()
    return sh.mascot


def _inspector(sh, app):
    sh.llm_worker.stop(); sh.llm_worker.wait(2000)     # else it drains the demo jobs at once
    for label in ("Weekly digest", "Meeting prep: Monday standup", "Task voice-lines"):
        sh.llm_queue.submit(LlmJob(label=label, run=lambda llm: ""))
    sh.llm_queue.next_runnable()
    sh.llm_status_line.set_busy(True)
    sh.llm_inspector.resize(400, 175)
    sh.llm_inspector.render()
    app.processEvents()
    return sh.llm_inspector


def _settings(sh, app):
    from serenity.ui.settings_window import SettingsWindow
    win = SettingsWindow(sh.settings, parent=sh)
    win.resize(560, 620)
    win.show()
    app.processEvents()
    return win


def _quick_todo(sh, app):
    from serenity.ui.modals import QuickTodoDialog
    dlg = QuickTodoDialog(sh.todo_store, sh.settings, sh, stamp=sh.stamp)
    dlg.show()
    app.processEvents()
    return dlg


def _mini(sh, app):
    from serenity.ui.shell import MODE_MINI
    sh.set_window_mode(MODE_MINI)
    app.processEvents()
    return sh._mini if getattr(sh, "_mini", None) is not None else sh


def scenes() -> dict:
    return {
        "todos": _tab("todos"), "notes": _tab("notes"), "board": _tab("board"),
        "calendar": _tab("calendar"), "graph": _tab("graph"), "trash": _tab("trash"),
        "ring": _ring, "inspector": _inspector, "settings": _settings,
        "quick_todo": _quick_todo, "mini": _mini,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path("/tmp/serenity-uishot")
    if "--out" in argv:
        i = argv.index("--out")
        out = Path(argv[i + 1]); del argv[i:i + 2]
    registry = scenes()
    wanted = [a for a in argv if not a.startswith("-")] or list(registry)
    unknown = [w for w in wanted if w not in registry]
    if unknown:
        print(f"unknown scene(s): {', '.join(unknown)}\navailable: {', '.join(registry)}")
        return 1
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    from serenity.ui.shell import Shell
    sh = Shell()
    seed(sh)
    sh.show()
    app.processEvents()

    for name in wanted:
        widget = registry[name](sh, app)
        app.processEvents()
        pix = widget.grab()
        path = out / f"{name}.png"
        pix.save(str(path))
        print(f"{name:11} {pix.width():4}x{pix.height():<5} {path}")

    sh.tray.hide()
    from serenity.ui.llm_worker import stop_all_workers
    stop_all_workers()                 # the app does this in _quit; a script must too
    print(f"\n{len(wanted)} scene(s) -> {out}   (temp profile: {_TMP})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
