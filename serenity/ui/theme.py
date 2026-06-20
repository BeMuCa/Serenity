"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: The shadcn-dark theme - colors + a Qt stylesheet, translated from the mockup.
Role:    Single styling source for every widget. Mirrors the CSS variables in
         app-ui-v2.html (bg/panel/ink/accent + neon for Serenity only). Accent is
         injected from Settings so the user's accent applies app-wide.

Functions:
- stylesheet(accent) -> str - the full app QSS with the chosen accent color
- COLORS - the palette dict (also used by widgets that paint directly)
- CHIP_COLORS / NOTE_COLOR_HEX - chip + note-card color hexes
- pill_label(text, *, border) -> QLabel - the house-style tag/badge pill
============================================================
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

COLORS = {
    "bg": "#0a0a0b",
    "panel": "#0f0f11",
    "panel2": "#141417",
    "panel3": "#18181b",
    "line": "rgba(255,255,255,0.08)",
    "line2": "rgba(255,255,255,0.12)",
    "ink": "#ededf0",
    "ink2": "#a1a1aa",
    "ink3": "#71717a",
    "accent": "#a78bfa",
    "accent_soft": "rgba(167,139,250,0.14)",
    "cyan": "#19e3ff",
    "mag": "#ff3bd4",
}

# note-card colorways (left accent + tint). Neon reserved for Serenity.
NOTE_COLOR_HEX = {
    "violet": "#a78bfa",
    "sky": "#7dd3fc",
    "green": "#86efac",
    "amber": "#fbbf24",
    "rose": "#fca5a5",
    "neutral": "#52525b",
}


def pill_label(text: str, *, border: str = COLORS["line2"]) -> QLabel:
    """A house-style tag / badge pill QLabel (muted ink, thin border, rounded).

    Shared by the tag pills (notes_view), the variant chips (tag_consolidation_dialog) and the
    kind badges (duplicates_dialog). Tooltip / elision stay with the caller so the rendered QSS
    is identical to the previous inline copies. `border` defaults to the line2 variant; the
    notes tag pill passes COLORS['line']."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{COLORS['ink2']}; border:1px solid {border};"
        f"border-radius:6px; padding:1px 7px; font-size:10.5px;"
    )
    return lbl


def stylesheet(accent: str = "#a78bfa") -> str:
    c = COLORS
    return f"""
    * {{
        font-family: "Segoe UI", system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif;
        font-size: 13px;
        color: {c['ink']};
        outline: none;
    }}
    QWidget#dock {{ background: {c['panel']}; }}
    QWidget#titleBar {{ background: {c['panel']}; border-bottom: 1px solid {c['line']}; }}
    QLabel#brand {{ font-size: 13px; font-weight: 600; }}
    QLabel#brandSub {{ color: {c['ink3']}; font-size: 11px; }}

    QToolButton, QPushButton#iconbtn {{
        border: 1px solid transparent; border-radius: 7px; color: {c['ink2']};
        background: transparent; padding: 4px;
    }}
    QToolButton:hover, QPushButton#iconbtn:hover {{
        background: {c['panel3']}; color: {c['ink']}; border: 1px solid {c['line']};
    }}
    QToolButton:checked {{ color: {accent}; background: {c['accent_soft']}; }}

    /* tabs */
    QPushButton#tab {{
        border: none; background: transparent; color: {c['ink3']};
        padding: 8px 12px 10px; font-size: 13px; border-radius: 7px;
    }}
    QPushButton#tab:hover {{ color: {c['ink2']}; }}
    QPushButton#tab:checked {{ color: {c['ink']}; font-weight: 600; border-bottom: 2px solid {accent}; }}

    /* inputs */
    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {c['panel2']}; border: 1px solid {c['line']}; border-radius: 8px;
        padding: 7px 9px; color: {c['ink']}; selection-background-color: {accent};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {accent}; }}
    QLineEdit::placeholder {{ color: {c['ink3']}; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['panel3']}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QLabel#sectLabel {{ color: {c['ink3']}; font-size: 11px; }}

    /* primary button */
    QPushButton#primary {{
        background: {accent}; color: #0a0a0b; border: none; border-radius: 8px;
        padding: 8px 13px; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: #b9a3fb; }}

    /* ghost / danger */
    QPushButton#ghost {{
        background: {c['panel2']}; color: {c['ink2']}; border: 1px solid {c['line2']};
        border-radius: 7px; padding: 4px 10px; font-size: 11px;
    }}
    QPushButton#ghost:hover {{ border: 1px solid {accent}; color: {c['ink']}; }}
    QPushButton#danger {{
        background: rgba(252,165,165,0.06); color: #fca5a5;
        border: 1px solid rgba(252,165,165,0.25); border-radius: 7px; padding: 4px 8px; font-size: 11px;
    }}
    QPushButton#danger:hover {{ background: rgba(252,165,165,0.16); }}

    /* toggle pill buttons */
    QPushButton#pill {{
        background: transparent; color: {c['ink3']}; border: none; border-radius: 6px;
        padding: 5px 12px; font-size: 12px;
    }}
    QPushButton#pill:checked {{ background: {c['panel3']}; color: {c['ink']}; font-weight: 600; }}

    QFrame#card {{ background: {c['panel2']}; border: 1px solid {c['line']}; border-radius: 10px; }}
    QFrame#capture {{ background: {c['panel']}; border-top: 1px solid {c['line']}; }}

    QDialog, QMainWindow {{ background: {c['panel']}; }}
    QMenu {{ background: {c['panel2']}; border: 1px solid {c['line2']}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['ink']}; }}

    QComboBox {{
        background: {c['panel2']}; border: 1px solid {c['line']}; border-radius: 7px; padding: 5px 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {c['panel2']}; border: 1px solid {c['line2']}; selection-background-color: {c['accent_soft']};
    }}
    QCheckBox {{ spacing: 8px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['panel3']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {accent}; width: 14px; margin: -6px 0; border-radius: 7px; }}
    """
