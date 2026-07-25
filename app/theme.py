"""Brand system — serious translator, joke only in word + chip + tagline.

Fonts: Segoe UI (Windows) — full Cyrillic, UTF-8 source files.
Brand: latin «epta» = russian «ёпта» (meme safety for mixed keyboards).

Layout rhythm (Lebedev: proximity + common air):
  one scale → equal gaps between equals, same inset in both panes.
"""

from __future__ import annotations

from pathlib import Path

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
CLEAR_TINT = "#faf3f2"
CLEAR_BORDER = "#e8c4c0"
CLEAR_HOVER = "#f3e8e6"
SETTINGS_BG = "#eceae4"
SETTINGS_CARD = SURFACE

# ── layout rhythm (px) — one air unit everywhere ─────────────
AIR = 10
PAD = AIR
GAP = AIR
MID_W = AIR
INSET = 10
BAR_GAP = 8
CTRL_H = 30
BAR_H = CTRL_H
ROW_H = CTRL_H
ICON_W = 30
COPY_W = 66
BTN_GAP = 12
LANG_COMBO_W = 118
SWAP_W = 36
DOT_SIZE = 14
CORNER = 10
CORNER_SM = 6
TITLE_H = 32
FOOT_H = 26
TEXT_BORDER_SPACING = 6
HEAD_H = 36
ON_ACCENT = "#ffffff"
PROVIDER_COMBO_W = 142
TOOL_GAP = 8

# UTF-8 / Cyrillic-safe UI font (Segoe UI ships with full Cyrillic on Win)
FONT_UI = "Segoe UI"
FONT_MDL2 = "Segoe MDL2 Assets"
GLYPH_SETTINGS = "\uE713"
FONT_UI_SIZE = 13
FONT_BODY_SIZE = 13
FONT_BRAND_SIZE = 21
FONT_BRAND_CYR_SIZE = 16

def _read_version() -> str:
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        return line or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()
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


def mdl2_font(size: int = 15) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_MDL2, size=size)
