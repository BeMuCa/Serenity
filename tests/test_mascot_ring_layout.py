"""
============================================================
Author:  Berk
Created: 2026-08-10
Purpose: Verify the activity-state ring actually lands INSIDE the mascot stage - the
         states were invisible in the running app because the arc was placed below the
         widget and clipped (only the two end bubbles showed).
Role:    Headless geometry regression for ui/mascot_stage.MascotStage._place_bubbles.

Test classes:
- TestRingGeometry — every bubble fully inside the stage, arced ABOVE the arc centre
============================================================
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from serenity.core.settings import Settings  # noqa: E402
from serenity.ui.mascot_stage import MascotStage  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _stage(qapp, width=348, height=240):
    stage = MascotStage(Settings())
    stage.resize(width, height)
    stage.show()
    qapp.processEvents()
    return stage


class TestRingGeometry:
    def test_every_bubble_is_fully_inside_the_stage(self, qapp):
        stage = _stage(qapp)
        stage.open_selector()
        qapp.processEvents()
        assert len(stage._bubbles) > 2, "the ring should offer more than a couple of states"
        outside = [b.text() for b in stage._bubbles
                   if not stage.rect().contains(b.geometry())]
        assert outside == [], f"clipped out of the stage: {outside}"

    def test_bubbles_arc_above_the_avatar_centre(self, qapp):
        """The dock puts the mascot at the bottom, so the ring must fan UPWARD - if the arc
        drops below her centre it runs off the widget on any normal dock height."""
        stage = _stage(qapp)
        stage.open_selector()
        qapp.processEvents()
        avatar_mid = stage.avatar.geometry().center().y()
        below = [b.text() for b in stage._bubbles if b.geometry().top() > avatar_mid]
        assert below == [], f"bubbles placed below the avatar's middle: {below}"

    def test_ring_survives_a_short_stage(self, qapp):
        """Mini mode / a small render scale gives a shorter stage; nothing may escape it."""
        stage = _stage(qapp, width=232, height=200)
        stage.open_selector()
        qapp.processEvents()
        for b in stage._bubbles:
            g = b.geometry()
            assert g.left() >= 0 and g.top() >= 0
            assert g.right() <= stage.width() and g.bottom() <= stage.height(), \
                f"{b.text()} escapes: {g} vs stage {stage.rect()}"

    def test_close_selector_removes_every_bubble(self, qapp):
        stage = _stage(qapp)
        stage.open_selector()
        qapp.processEvents()
        assert stage._bubbles
        stage.close_selector()
        qapp.processEvents()
        assert stage._bubbles == []
