"""
============================================================
Author:  Berk
Created: 2026-08-12
Purpose: Enforce the standing UI rule - every feature, setting and option explains itself
         on hover. Boots the real Shell (and the Settings window) headless and fails on
         any interactive control with no tooltip.
Role:    The guard that keeps hover explanations from rotting: a new button, checkbox,
         combo or slider that ships without a tooltip fails the suite instead of shipping
         unexplained. Mirrors test_theme_readability.py, which renders and asserts pixels.

Test classes:
- TestShellTooltipCoverage - every interactive control in the dock explains itself
- TestSettingsTooltipCoverage - the same for the Settings window's options
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTimeEdit,
)

# The control kinds a user can act on. QLineEdit/QPlainTextEdit are excluded: they carry a
# placeholder, which is the same promise made in a way that is visible without hovering.
INTERACTIVE = (QPushButton, QCheckBox, QComboBox, QSlider, QRadioButton, QSpinBox,
               QDateEdit, QTimeEdit)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _unexplained(root) -> list[str]:
    """Interactive controls under `root` with no tooltip, described well enough to find."""
    out = []
    for w in root.findChildren(object):
        if not isinstance(w, INTERACTIVE) or w.toolTip():
            continue
        label = (w.text() if hasattr(w, "text") else "") or w.objectName() or "<unnamed>"
        parent = w.parent().__class__.__name__ if w.parent() else "?"
        out.append(f"{type(w).__name__} {label!r} in {parent}")
    return out


class TestShellTooltipCoverage:
    def test_every_interactive_control_explains_itself(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.ui.shell import Shell

        shell = Shell()
        try:
            missing = _unexplained(shell)
            assert not missing, "controls with no hover explanation:\n  " + "\n  ".join(missing)
        finally:
            shell.tray.hide()


class TestSettingsTooltipCoverage:
    def test_every_option_explains_itself(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        from serenity.core.settings import Settings
        from serenity.ui.settings_window import SettingsWindow

        win = SettingsWindow(Settings())
        missing = _unexplained(win)
        assert not missing, "settings with no hover explanation:\n  " + "\n  ".join(missing)
