"""Brand system — serious translator, joke only in word + chip + tagline.

Fonts: Segoe UI (Windows) — full Cyrillic, UTF-8 source files.
Brand: latin «epta» = russian «ёпта» (meme safety for mixed keyboards).

Layout rhythm (Lebedev: proximity + common air):
  one scale → equal gaps between equals, same inset in both panes.
"""

from __future__ import annotations

import customtkinter as ctk

# paper studio
BG = "#f2f2ef"
SURFACE = "#ffffff"
FIELD = "#fafaf8"
LINE = "#e2e2dc"
LINE_STRONG = "#cecec6"
INK = "#141414"
INK_SOFT = "#5a5a54"
INK_FAINT = "#8e8e86"
ACCENT = "#111111"
ACCENT_HOVER = "#2c2c2c"
CHIP_BG = "#f7f7f4"
CHIP_BORDER = "#d8d8d0"
CHIP_HOVER = "#ecece6"
CHIP_INK = "#1a1a1a"
OK = "#1a7f4b"
ERR = "#b42318"
TITLE_BG = "#ecece8"
TITLE_BTN_HOVER = "#e0e0da"
TITLE_CLOSE_HOVER = "#e81123"
TITLE_CLOSE_HOVER_FG = "#ffffff"

# ── layout rhythm (px) — one air unit everywhere ─────────────
# outer margin == inter-pane gap == vertical stack gap (Lebedev common air)
AIR = 12
PAD = AIR         # shell → content / foot (L/R/B)
GAP = AIR         # toolbar ↔ panes, panes ↔ foot
MID_W = AIR       # between source/target cards (⇄ lives on toolbar only)
INSET = AIR       # pane internal padding (all sides of bar/field)
BAR_GAP = AIR     # language bar → text field
CTRL_H = 32       # base control height (load-bearing equality below)
BAR_H = CTRL_H    # pane language bar
ROW_H = CTRL_H    # toolbar / chip buttons
ICON_W = 32       # clear (✕) width
COPY_W = 72       # «копир.» width
SWAP_W = 40       # ⇄ button on toolbar (centered over pane gap)
DOT_SIZE = 18     # provider ● — proportional to ROW_H icons
CORNER = 12       # card radius
CORNER_SM = 8     # field / chip radius
TITLE_H = 36
FOOT_H = 28       # tagline + version
TEXT_BORDER_SPACING = 10  # CTkTextbox inner text pad
HEAD_H = 40       # top toolbar row
ON_ACCENT = "#ffffff"  # text on ACCENT buttons

# UTF-8 / Cyrillic-safe UI font (Segoe UI ships with full Cyrillic on Win)
FONT_UI = "Segoe UI"
FONT_UI_SIZE = 13

APP_VERSION = "1.3.5"
# short OS/taskbar name — no version (version lives in custom chrome only)
APP_NAME = "bonjour epta"
BRAND_LATIN = "epta"  # latin spelling
BRAND_CYR = "ёпта"  # same word for RU keyboards / reading aloud
TAGLINE = "Хочешь в Париж — учи язык"


def apply_appearance() -> None:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")


def ui_font(size: int = FONT_UI_SIZE, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_UI, size=size, weight=weight)
