"""
============================================================
Author:  Berk
Created: 2026-08-10
Purpose: Verify the dock's tab row is icon-only (six text labels did not fit and elided
         to "Boarc"/"Cal") and that the ACTIVE tab is still identifiable - its icon is
         tinted with the accent while the others stay muted.
Role:    Headless UI regression for ui/shell.py's tab bar + _paint_tab_icons.

Test classes:
- TestIconTabs — no labels, every tab has an icon + a tooltip name
- TestActiveTint — the checked tab's icon is accent-tinted, the others are not
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.ui import icons  # noqa: E402
from serenity.ui.shell import TAB_ICONS, TAB_TIPS  # noqa: E402
from serenity.ui.theme import COLORS  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shell(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from serenity.core import paths
    from serenity.ui import platform_win
    monkeypatch.setattr(platform_win, "set_autostart", lambda *a, **k: False)
    monkeypatch.setattr(paths, "default_vault_dir", lambda: tmp_path / "vault")
    from serenity.ui.shell import Shell
    sh = Shell()
    yield sh
    sh.tray.hide()


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _tint_of(button) -> str:
    """Classify the icon's ink as "accent" or "muted" by averaging its opaque pixels and
    taking the nearer of the two theme colours. Averaging (rather than exact matching) is
    what makes this robust to the anti-aliased edges of a stroked SVG."""
    img = button.icon().pixmap(17, 17).toImage()
    rs = gs = bs = n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 120:            # skip the feathered edge, keep the solid stroke
                continue
            rs += c.red(); gs += c.green(); bs += c.blue(); n += 1
    if not n:
        return "empty"
    mean = (rs / n, gs / n, bs / n)
    def dist(hex_color):
        a, b, c = _rgb(hex_color)
        return (mean[0] - a) ** 2 + (mean[1] - b) ** 2 + (mean[2] - c) ** 2
    return "accent" if dist(COLORS["accent"]) < dist(COLORS["ink3"]) else "muted"


class TestIconTabs:
    def test_every_tab_is_icon_only_with_a_tooltip(self, shell):
        assert set(shell.tab_buttons) == set(TAB_ICONS)
        for key, b in shell.tab_buttons.items():
            assert b.text() == "", f"{key} still carries a text label: {b.text()!r}"
            assert not b.icon().isNull(), f"{key} has no icon"
            assert b.toolTip() == TAB_TIPS[key], f"{key} tooltip is {b.toolTip()!r}"

    def test_every_mapped_icon_name_exists(self):
        """A typo'd name renders an EMPTY icon, which looks like a missing tab."""
        for key, name in TAB_ICONS.items():
            assert name in icons._PATHS, f"{key} -> unknown icon {name!r}"

    def test_each_tab_still_switches_its_view(self, shell):
        for key in TAB_ICONS:
            shell.switch_tab(key)
            assert shell.stack.currentIndex() == shell._view_index[key]
            assert shell.tab_buttons[key].isChecked()


class TestActiveTint:
    def test_active_icon_is_accent_and_the_others_are_not(self, shell):
        shell.switch_tab("board")
        tints = {k: _tint_of(b) for k, b in shell.tab_buttons.items()}
        assert tints["board"] == "accent", tints
        assert [k for k, t in tints.items() if t == "accent"] == ["board"], tints

    def test_tint_follows_the_switch(self, shell):
        shell.switch_tab("notes")
        shell.switch_tab("calendar")
        assert _tint_of(shell.tab_buttons["calendar"]) == "accent"
        assert _tint_of(shell.tab_buttons["notes"]) == "muted"
