"""
============================================================
Author:  Berk
Created: 2026-08-10
Purpose: Guard the theme's readability floor by RENDERING widgets and reading pixels:
         every widget class the app puts in a dialog or popup must get a dark
         background, because the QSS `*` rule already paints all text near-white.
Role:    Headless regression test for ui/theme.stylesheet(). Catches the white-on-white
         class of bug that no logic test can see (reported from the running app).

Test classes:
- TestReadableOnDark — plain buttons, tabs, list rows, date/time fields render dark
- TestContrast — the painted text colour is far from the painted background colour
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import (QApplication, QDateEdit, QDialog, QLabel, QListWidget,  # noqa: E402
                               QPushButton, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from serenity.ui.theme import COLORS, stylesheet  # noqa: E402

# What an unstyled widget looks like on this platform: the light plate that made text
# vanish. Any widget the theme covers must be nowhere near it.
PLATFORM_LIGHT = 0xEF


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _brightness(color) -> int:
    return max(color.red(), color.green(), color.blue())


def _render(qapp, widget) -> "tuple":
    """Show the widget inside a themed dialog, then return its grabbed image."""
    host = QDialog()
    host.setStyleSheet(stylesheet())
    lay = QVBoxLayout(host)
    lay.addWidget(widget)
    host.resize(320, 190)
    host.show()
    qapp.processEvents()
    img = widget.grab().toImage()
    return img


def _tabs():
    tabs = QTabWidget()
    page = QWidget()
    QVBoxLayout(page).addWidget(QLabel("Pose for each state"))
    tabs.addTab(page, "Appearance")
    tabs.addTab(QWidget(), "AI and voice")
    return tabs


def _list():
    lst = QListWidget()
    lst.addItems(["Working", "Coding", "Idle"])
    return lst


# Factories, not instances: a QWidget built at collection time (before QApplication) aborts.
WIDGET_FACTORIES = [
    ("plain QPushButton", lambda: QPushButton("Save")),
    ("QTabWidget/QTabBar", _tabs),
    ("QListWidget", _list),
    ("QDateEdit", QDateEdit),
    ("QTimeEdit", QTimeEdit),
]


class TestReadableOnDark:
    @pytest.mark.parametrize("name,factory", WIDGET_FACTORIES,
                             ids=[n for n, _ in WIDGET_FACTORIES])
    def test_widget_is_not_left_on_the_platform_light_plate(self, qapp, name, factory):
        img = _render(qapp, factory())
        # sample a spread of points rather than one, so a styled border can't hide an
        # unstyled interior (and vice versa)
        pts = [(2, 2), (img.width() // 2, img.height() // 2), (img.width() - 3, img.height() - 3)]
        bright = [_brightness(img.pixelColor(x, y)) for x, y in pts
                  if 0 <= x < img.width() and 0 <= y < img.height()]
        assert bright, f"{name}: nothing rendered"
        assert max(bright) < PLATFORM_LIGHT, f"{name}: still painted light {bright}"


class TestContrast:
    def test_button_label_contrasts_with_its_plate(self, qapp):
        """The actual failure mode was near-white text on a near-white plate: assert the
        brightest pixel (the glyphs) and the darkest (the plate) are far apart."""
        btn = QPushButton("Close")
        img = _render(qapp, btn)
        vals = [_brightness(img.pixelColor(x, y))
                for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)]
        assert max(vals) - min(vals) > 60, f"no contrast inside the button: {min(vals)}..{max(vals)}"

    def test_theme_keeps_ink_light_so_backgrounds_must_stay_dark(self):
        """Documents WHY the rules above are required: `*` paints all text near-white, so a
        missing background rule is automatically unreadable, never merely ugly."""
        assert _brightness_hex(COLORS["ink"]) > 0xD0
        assert _brightness_hex(COLORS["panel"]) < 0x30
        assert "QPushButton {" in stylesheet()          # the floor rule exists


def _brightness_hex(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    return max(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
