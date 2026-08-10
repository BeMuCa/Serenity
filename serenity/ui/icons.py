"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Line-style SVG icons rendered to QIcon (no emoji - decisions doc).
Role:    Shared icon set for the title bar, tabs, chips and buttons. Icons are the
         Lucide-style strokes from the mockup, recolored at render time.

Functions:
- icon(name, color, size) -> QIcon - render a named SVG to a QIcon
- pixmap(name, color, size) -> QPixmap
============================================================
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer

# raw SVG path bodies (24x24 viewbox), stroked line icons
_PATHS = {
    "pin": '<path d="M12 17v5"/><path d="M9 10.8V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v5.8l2 3.2H7l2-3.2z"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 5.1A9 9 0 0 1 21 12a13 13 0 0 1-2 2.8"/>'
               '<path d="M6.2 6.2A12 12 0 0 0 3 12s3 7 9 7a8.5 8.5 0 0 0 4-1"/>',
    "settings": '<line x1="4" y1="8" x2="20" y2="8"/><circle cx="9" cy="8" r="2.2"/>'
                '<line x1="4" y1="16" x2="20" y2="16"/><circle cx="15" cy="16" r="2.2"/>',
    "minimize": '<line x1="5" y1="18" x2="19" y2="18"/>',
    "close": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "search": '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/>',
    "mic": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/>'
           '<line x1="12" y1="18" x2="12" y2="22"/>',
    "note": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "play": '<polygon points="6 4 20 12 6 20" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "timer": '<circle cx="12" cy="13" r="8"/><path d="M12 13V9"/><path d="M9 2h6"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    "repeat": '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>'
              '<path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
    "file": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
             '<path d="M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/>',
    "restore": '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/>',
    "caret": '<polyline points="9 6 15 12 9 18"/>',
    # diagonal out-arrows (expand / pop-out to the large editor)
    "expand": '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>'
              '<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
    "grip": '<circle cx="9" cy="6" r="1.4" fill="currentColor" stroke="none"/>'
            '<circle cx="15" cy="6" r="1.4" fill="currentColor" stroke="none"/>'
            '<circle cx="9" cy="12" r="1.4" fill="currentColor" stroke="none"/>'
            '<circle cx="15" cy="12" r="1.4" fill="currentColor" stroke="none"/>'
            '<circle cx="9" cy="18" r="1.4" fill="currentColor" stroke="none"/>'
            '<circle cx="15" cy="18" r="1.4" fill="currentColor" stroke="none"/>',
    "graph": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="18" r="2.5"/>'
             '<path d="M8 7.5 16 9"/><path d="M7 8l4 7.5"/><path d="M16.5 9.5 13 15.5"/>',
    # speaker + two sound waves (voice ON)
    "volume": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'
              '<path d="M18.5 6a9 9 0 0 1 0 12"/>',
    # speaker with an X (voice muted)
    "mute": '<path d="M11 5 6 9H3v6h3l5 4z"/><line x1="22" y1="9" x2="16" y2="15"/>'
            '<line x1="16" y1="9" x2="22" y2="15"/>',
    # Phase B context toggle: briefcase (Business) / house (Private)
    "business": '<rect x="3" y="7" width="18" height="13" rx="2"/>'
                '<path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "private": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
}


def _svg(name: str, color: str, stroke: float = 1.8) -> bytes:
    body = _PATHS.get(name, "")
    body = body.replace("currentColor", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")


def pixmap(name: str, color: str = "#a1a1aa", size: int = 16, stroke: float = 1.8) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return pm


def icon(name: str, color: str = "#a1a1aa", size: int = 16, stroke: float = 1.8) -> QIcon:
    return QIcon(pixmap(name, color, size, stroke))
