"""Colours and the Qt stylesheet.

Every UI size is multiplied by the scale S, which follows the window size, so
the panels and header fit any screen. The canvas is NOT scaled by this: it
keeps its own native pixel size.
"""
from __future__ import annotations

from pathlib import Path

BG = "#F3F4F6"
SURFACE = "#FFFFFF"
SURFACE_2 = "#F7F8FA"
LINE = "rgba(0,0,0,36)"
LINE_2 = "rgba(0,0,0,66)"
TEXT = "#111418"
DIM = "#3E444C"
MUTE = "#5C636E"
ACCENT = "#0B7A4B"
ACCENT_BG = "#E6F4EC"
NEG = "#B3261E"
SEL = "#1F6FEB"          # selection blue
STAGE = "#D5D8DD"        # around the canvas
DOT = "#C3C8CF"          # canvas dots
SNAP = "#E5398F"         # snap guides and gap markers
HINT_LINE = "#1F6FEB"    # faint helper lines while dragging (drawn with low alpha)

SANS = "Inter, Segoe UI, system-ui, sans-serif"
MONO = "Cascadia Mono, Consolas, monospace"

S = 1.0                   # current UI scale
ICONS = (Path(__file__).resolve().parent / "icons").as_posix()   # small SVGs the stylesheet uses (drop-down arrow)


def px(v: float) -> int:
    return max(1, round(v * S))


def qss() -> str:
    f = px(13)
    return f"""
* {{ font-family: {SANS}; font-size: {f}px; color: {TEXT}; }}
QMainWindow, #Root {{ background: {BG}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {LINE_2}; padding: {px(4)}px; }}
#Header QLabel#Title {{ font-size: {px(18)}px; font-weight: 700; }}
#Sep {{ background: {LINE_2}; }}
#Status {{ font-family: {MONO}; font-size: {px(12)}px; color: {DIM}; }}

QPushButton {{
  min-height: {px(28)}px; max-height: {px(28)}px; padding: 0 {px(12)}px;
  border: 1px solid {LINE_2}; border-radius: {px(4)}px; background: {SURFACE};
}}
QPushButton:hover {{ border-color: {ACCENT}; background: {ACCENT_BG}; }}
QPushButton:disabled {{ color: rgba(17,20,24,90); border-color: {LINE}; }}
QPushButton:checked, QPushButton[on="true"] {{ background: {ACCENT}; color: #fff; border-color: {ACCENT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #fff; border-color: {ACCENT}; font-weight: 600; }}
QPushButton#Ic {{ padding: 0; min-width: {px(28)}px; max-width: {px(28)}px; }}
QPushButton#Small {{ min-height: {px(26)}px; max-height: {px(26)}px; padding: 0 {px(8)}px; font-size: {px(12)}px; }}
QPushButton#Tab {{ min-height: {px(26)}px; max-height: {px(26)}px; padding: 0 {px(8)}px; font-size: {px(12)}px; }}
QPushButton#Tab[empty="true"]:!checked {{ color: rgba(17,20,24,110); }}
QPushButton#Swatch {{ padding: 0; min-width: {px(36)}px; max-width: {px(36)}px; }}
QPushButton::menu-indicator {{ width: 0; }}
QPushButton#Step {{ padding: 0; min-width: {px(20)}px; max-width: {px(20)}px; min-height: {px(22)}px; max-height: {px(22)}px; }}
QPushButton#Step:pressed {{ background: #CFEBDB; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  min-height: {px(26)}px; max-height: {px(26)}px; padding: 0 {px(6)}px;
  border: 1px solid {LINE_2}; border-radius: {px(4)}px; background: {SURFACE};
  selection-background-color: {ACCENT}; selection-color: #fff;
}}
QAbstractSpinBox {{ padding: 0 0 0 {px(6)}px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
  subcontrol-origin: border; width: {px(16)}px; border: 0; border-left: 1px solid {LINE}; background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {px(4)}px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: {px(4)}px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {ACCENT_BG}; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background: #CFEBDB; }}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}
QAbstractSpinBox QLineEdit {{ border: 0; padding: 0; margin: 0; min-height: 0; max-height: 16777215; background: transparent; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox {{ padding-right: {px(22)}px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; border: 0; width: {px(22)}px; }}
QComboBox::down-arrow {{ image: url("{ICONS}/chevron-down.svg"); width: {px(12)}px; height: {px(12)}px; }}
QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{ image: url("{ICONS}/chevron-down-hover.svg"); }}
QComboBox::down-arrow:disabled {{ image: url("{ICONS}/chevron-down-off.svg"); }}
QComboBox QAbstractItemView {{ border: 1px solid {LINE_2}; background: {SURFACE}; selection-background-color: {ACCENT_BG}; selection-color: {TEXT}; outline: 0; }}
QCheckBox {{ spacing: {px(6)}px; }}
QCheckBox::indicator {{ width: {px(14)}px; height: {px(14)}px; border: 1px solid {LINE_2}; border-radius: {px(3)}px; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QSlider::groove:horizontal {{ height: {px(4)}px; background: {LINE}; border-radius: {px(2)}px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: {px(2)}px; }}
QSlider::handle:horizontal {{ width: {px(14)}px; margin: -{px(5)}px 0; border-radius: {px(7)}px; background: {SURFACE}; border: 1px solid {ACCENT}; }}

#Panel {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: {px(8)}px; }}
#PanelTitle {{ font-size: {px(12)}px; font-weight: 700; }}
#PanelTitle:hover {{ color: {ACCENT}; }}
#FieldLabel {{ font-size: {px(11)}px; color: {MUTE}; }}
#Hint {{ font-size: {px(12)}px; color: {MUTE}; }}
#Mono {{ font-family: {MONO}; font-size: {px(12)}px; }}
#KV {{ font-family: {MONO}; font-size: {px(11)}px; color: {DIM}; }}
#KVKey {{ font-size: {px(11)}px; color: {MUTE}; }}

QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: {px(8)}px; background: transparent; margin: 0; }}
QScrollBar:horizontal {{ height: {px(8)}px; background: transparent; margin: 0; }}
QScrollBar::handle {{ background: rgba(0,0,0,50); border-radius: {px(4)}px; min-height: {px(24)}px; min-width: {px(24)}px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}

#PageStrip {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: {px(8)}px; }}

QPlainTextEdit {{ border: 1px solid {LINE_2}; border-radius: {px(4)}px; background: {SURFACE};
  padding: {px(4)}px {px(6)}px; selection-background-color: {ACCENT}; selection-color: #fff; }}
QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QListWidget {{ border: 1px solid {LINE_2}; border-radius: {px(4)}px; background: {SURFACE}; outline: 0; }}
QListWidget::item {{ padding: {px(3)}px {px(6)}px; border-radius: {px(3)}px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #fff; }}
QListWidget::item:hover:!selected {{ background: #EEF1F4; }}

QMenu {{ background: {SURFACE}; border: 1px solid {LINE_2}; padding: {px(4)}px; }}
QMenu::item {{ padding: {px(5)}px {px(18)}px {px(5)}px {px(12)}px; border-radius: {px(3)}px; }}
QMenu::item:selected {{ background: {ACCENT_BG}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: {px(4)}px {px(6)}px; }}
"""
