"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Tests for FEATURE 3 - autostart default ON, the Settings toggle's set_autostart side
         effect, the boot greeting, and the Windows standby/resume re-greeting (headless).
Role:    Guards the locked decision "autostart ON by default + greet on boot AND on open +
         react to standby/resume" without touching the Windows registry or any heavy deps.
         The native power-message decision lives in a pure helper (platform_win.is_resume_message)
         so the resume path is unit-testable on Linux; the shell wiring is exercised by calling
         the handler directly (nativeEvent itself is untestable off Windows).

Test classes:
- TestAutostartDefault - the setting defaults to True and survives load/save round-trips
- TestAutostartCommand - the registered command carries the --autostarted sentinel; off-Windows
  set_autostart / get_autostart are no-ops returning False
- TestResumeMessage - is_resume_message accepts only WM_POWERBROADCAST + a resume sub-event
- TestSettingsToggle - the Settings dialog _save calls platform_win.set_autostart with the toggle
- TestShellGreeting - greet() picks boot/resume/open lines; the resume handler greets; boot flag
============================================================
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from serenity.core.settings import Settings  # noqa: E402
from serenity.ui import platform_win  # noqa: E402


class TestAutostartDefault:
    def test_default_is_true(self):
        assert Settings().autostart is True

    def test_round_trips_through_save_load(self, tmp_path):
        p = tmp_path / "settings.json"
        s = Settings()
        s._path = p
        s.save()
        assert Settings.load(p).autostart is True
        # an explicit opt-out is honored, not reset to the default
        s.autostart = False
        s.save()
        assert Settings.load(p).autostart is False


class TestAutostartCommand:
    def test_registered_command_carries_the_sentinel(self, monkeypatch):
        """On Windows, the command written to the Run key ends with --autostarted so the login
        launch can greet with the boot line. We fake winreg + is_windows to capture the value."""
        captured = {}

        class _FakeKey:
            pass

        class _FakeWinreg:
            HKEY_CURRENT_USER = 0
            KEY_SET_VALUE = 0
            REG_SZ = 1

            def OpenKey(self, *a, **k):
                return _FakeKey()

            def SetValueEx(self, key, name, reserved, typ, value):
                captured["name"] = name
                captured["value"] = value

            def DeleteValue(self, key, name):  # pragma: no cover - not hit when enabling
                pass

            def CloseKey(self, key):
                pass

        monkeypatch.setattr(platform_win, "is_windows", lambda: True)
        monkeypatch.setitem(__import__("sys").modules, "winreg", _FakeWinreg())

        assert platform_win.set_autostart(True) is True
        assert captured["name"] == platform_win.APP_RUN_KEY
        assert platform_win.AUTOSTART_FLAG in captured["value"]

    def test_off_windows_is_a_noop(self, monkeypatch):
        monkeypatch.setattr(platform_win, "is_windows", lambda: False)
        assert platform_win.set_autostart(True) is False
        assert platform_win.set_autostart(False) is False
        assert platform_win.get_autostart() is False


class TestResumeMessage:
    def test_resume_suspend_is_a_resume(self):
        assert platform_win.is_resume_message(
            platform_win.WM_POWERBROADCAST, platform_win.PBT_APMRESUMESUSPEND) is True

    def test_resume_automatic_is_a_resume(self):
        assert platform_win.is_resume_message(
            platform_win.WM_POWERBROADCAST, platform_win.PBT_APMRESUMEAUTOMATIC) is True

    def test_wrong_subevent_is_not_a_resume(self):
        # 0x04 == PBT_APMSUSPEND (going to sleep) - must NOT re-greet.
        assert platform_win.is_resume_message(platform_win.WM_POWERBROADCAST, 0x04) is False

    def test_wrong_message_is_not_a_resume(self):
        # A resume sub-event under a non-power message is irrelevant.
        assert platform_win.is_resume_message(0x0001, platform_win.PBT_APMRESUMESUSPEND) is False


# --------------------------------------------------------------------------- #
# Shell wiring (headless)
# --------------------------------------------------------------------------- #
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestSettingsToggle:
    def test_save_calls_set_autostart_with_the_toggle(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.settings_window import SettingsWindow

        # _save does `from .platform_win import set_autostart`, which binds to this attribute
        # at call time - so patching it here captures the toggle the dialog passes through.
        calls = []
        monkeypatch.setattr(platform_win, "set_autostart",
                            lambda enabled, *a, **k: calls.append(enabled) or True)

        s = Settings()
        s._path = tmp_path / "settings.json"
        dlg = SettingsWindow(s)
        try:
            dlg.autostart_cb.setChecked(False)
            dlg._save()
            assert calls and calls[-1] is False
            assert s.autostart is False
        finally:
            dlg.deleteLater()


class TestShellGreeting:
    def test_greet_selects_the_line_for_each_kind(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        # Never let the shell touch a real registry on the CI host.
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            events = []
            monkeypatch.setattr(shell.voice, "say",
                                lambda event, lang="en", **kw: events.append(event) or "x")
            shell.greet("boot")
            shell.greet("resume")
            shell.greet("open")
            shell.greet("nonsense")  # unknown -> open greeting, never silent
            assert events == [
                "app_boot_greeting",
                "app_resumed_greeting",
                "app_opened_greeting",
                "app_opened_greeting",
            ]
        finally:
            shell.tray.hide()

    def test_resume_handler_triggers_a_resume_greeting(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            said = []
            monkeypatch.setattr(shell.mascot, "says",
                                lambda text, *a, **k: said.append(text))
            shell._on_resume()
            # The resume greeting was spoken (one of the app_resumed_greeting variants).
            assert len(said) == 1 and said[0]
        finally:
            shell.tray.hide()

    def test_boot_flag_selects_the_boot_greeting(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.ui import shell as shell_mod
        from serenity.ui.shell import Shell

        # Spy on greet() to confirm the boot launch routes to the boot greeting.
        kinds = []
        orig = Shell.greet
        monkeypatch.setattr(shell_mod.Shell, "greet",
                            lambda self, kind="open": kinds.append(kind) or orig(self, kind))

        shell = Shell(boot=True)
        try:
            assert kinds == ["boot"]
        finally:
            shell.tray.hide()

    def test_default_launch_selects_the_open_greeting(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
        from serenity.ui import shell as shell_mod
        from serenity.ui.shell import Shell

        kinds = []
        orig = Shell.greet
        monkeypatch.setattr(shell_mod.Shell, "greet",
                            lambda self, kind="open": kinds.append(kind) or orig(self, kind))

        shell = Shell()  # no boot flag -> manual open
        try:
            assert kinds == ["open"]
        finally:
            shell.tray.hide()
