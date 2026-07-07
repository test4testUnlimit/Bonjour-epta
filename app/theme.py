"""Brand system — serious translator, joke only in word + chip + tagline.

Fonts: Segoe UI (Windows) — full Cyrillic, UTF-8 source files.
Brand: latin «epta» = russian «ёпта» (meme safety for mixed keyboards).
"""

from __future__ import annotations

import customtkinter as ctk

# paper studio
BG = "#f2f2ef"
SURFACE = "#ffffff"
FIELD = "#ffffff"
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

# layout rhythm (px)
PAD = 16
GAP = 12
ROW_H = 34
PANE_GAP = 12
BAR_H = 40
TITLE_H = 40

# UTF-8 / Cyrillic-safe UI font (Segoe UI ships with full Cyrillic on Win)
FONT_UI = "Segoe UI"
FONT_UI_SIZE = 13

APP_VERSION = "1.3.2"
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
