"""Brand system — serious translator, joke only in word + chip + tagline.

Fonts: Segoe UI (Windows) — full Cyrillic, UTF-8 source files.
Brand: the latin "epta" spelling of the meme, safe on mixed keyboards.

Layout rhythm (Lebedev: proximity + common air):
  one scale → equal gaps between equals, same inset in both panes.

Themes: light | dark | auto (follow Windows AppsUseLightTheme).
"""

from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

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
PROVIDER_COMBO_W = 142
TOOL_GAP = 8

FONT_UI = "Segoe UI"
FONT_MDL2 = "Segoe MDL2 Assets"
GLYPH_SETTINGS = "\uE713"  # gear
GLYPH_RESTART = "\uE72C"  # circular refresh arrow (Segoe MDL2)
GLYPH_DICT = "\uE8F1"  # stack of books — acronym dictionary
GLYPH_TOKEN = "\uE192"  # key — paste the AI token
FONT_UI_SIZE = 13
FONT_BODY_SIZE = 13
FONT_BRAND_SIZE = 18
FONT_BRAND_CYR_SIZE = 18
FONT_VERSION_SIZE = 9

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_AUTO = "auto"
THEME_CHOICES = (THEME_LIGHT, THEME_DARK, THEME_AUTO)
THEME_LABELS = {
    THEME_LIGHT: "светлая",
    THEME_DARK: "тёмная",
    THEME_AUTO: "авто",
}

_LIGHT = {
    "BG": "#f2f2ef",
    "SURFACE": "#ffffff",
    "FIELD": "#fafaf8",
    "LINE": "#e2e2dc",
    "LINE_STRONG": "#b8b8b0",
    "INK": "#141414",
    "INK_SOFT": "#5a5a54",
    "INK_FAINT": "#8e8e86",
    "ACCENT": "#111111",
    "ACCENT_HOVER": "#2c2c2c",
    "ON_ACCENT": "#ffffff",
    "ON_ERR": "#ffffff",
    "ERR_HOVER": "#8f1d13",
    "CHIP_BG": "#f7f7f4",
    "CHIP_BORDER": "#d8d8d0",
    "CHIP_HOVER": "#ecece6",
    # spotlight: the twin-pane match must be obvious. CHIP_HOVER is only a
    # hair off the field colour, so the highlight was invisible in practice.
    "SPOT_BG": "#ffe27a",
    "SPOT_INK": "#141414",
    "CHIP_INK": "#1a1a1a",
    "OK": "#1a7f4b",
    "WARN": "#b06f00",
    "ERR": "#b42318",
    "OK_HOVER": "#14663a",
    "ON_OK": "#ffffff",
    "TITLE_BG": "#ecece8",
    "TITLE_BTN_HOVER": "#e0e0da",
    "TITLE_CLOSE_HOVER": "#e81123",
    "TITLE_CLOSE_HOVER_FG": "#ffffff",
    "CLEAR_TINT": "#faf3f2",
    "CLEAR_BORDER": "#e8c4c0",
    "CLEAR_HOVER": "#f3e8e6",
    "SETTINGS_BG": "#eceae4",
    "SETTINGS_CARD": "#ffffff",
    "SWITCH_ON": "#111111",
    "SWITCH_OFF": "#8a8a82",
    "SWITCH_KNOB": "#d4d4cc",
    "SWITCH_KNOB_HOVER": "#c4c4bc",
    "READ_BG": "#ebeae4",
    "LINK": "#215d9c",
}

_DARK = {
    "BG": "#1a1a18",
    "SURFACE": "#242422",
    "FIELD": "#2c2c28",
    "LINE": "#3a3a36",
    "LINE_STRONG": "#52524c",
    "INK": "#f2f2ef",
    "INK_SOFT": "#b0b0a8",
    "INK_FAINT": "#8a8a82",
    "ACCENT": "#e8e8e2",
    "ACCENT_HOVER": "#ffffff",
    "ON_ACCENT": "#141414",
    "ON_ERR": "#1c0b09",
    "ERR_HOVER": "#f27b72",
    "CHIP_BG": "#2c2c28",
    "CHIP_BORDER": "#4a4a44",
    "CHIP_HOVER": "#363632",
    "SPOT_BG": "#7a5d18",
    "SPOT_INK": "#fdf6e3",
    "CHIP_INK": "#f2f2ef",
    "OK": "#3dba6e",
    "WARN": "#e0a63a",
    "ERR": "#e85a50",
    "OK_HOVER": "#52d184",
    "ON_OK": "#0a1f12",
    "TITLE_BG": "#222220",
    "TITLE_BTN_HOVER": "#32322e",
    "TITLE_CLOSE_HOVER": "#e81123",
    "TITLE_CLOSE_HOVER_FG": "#ffffff",
    "CLEAR_TINT": "#3a2826",
    "CLEAR_BORDER": "#6a403c",
    "CLEAR_HOVER": "#4a3230",
    "SETTINGS_BG": "#1a1a18",
    "SETTINGS_CARD": "#242422",
    "SWITCH_ON": "#e8e8e2",
    "SWITCH_OFF": "#5a5a54",
    "SWITCH_KNOB": "#3a3a36",
    "SWITCH_KNOB_HOVER": "#4a4a46",
    "READ_BG": "#2a2a26",
    "LINK": "#7ab4e8",
}

# active tokens (mutated by apply_theme)
BG = _LIGHT["BG"]
SURFACE = _LIGHT["SURFACE"]
FIELD = _LIGHT["FIELD"]
LINE = _LIGHT["LINE"]
LINE_STRONG = _LIGHT["LINE_STRONG"]
INK = _LIGHT["INK"]
INK_SOFT = _LIGHT["INK_SOFT"]
INK_FAINT = _LIGHT["INK_FAINT"]
ACCENT = _LIGHT["ACCENT"]
ACCENT_HOVER = _LIGHT["ACCENT_HOVER"]
ON_ACCENT = _LIGHT["ON_ACCENT"]
ON_ERR = _LIGHT["ON_ERR"]
ERR_HOVER = _LIGHT["ERR_HOVER"]
CHIP_BG = _LIGHT["CHIP_BG"]
CHIP_BORDER = _LIGHT["CHIP_BORDER"]
CHIP_HOVER = _LIGHT["CHIP_HOVER"]
SPOT_BG = _LIGHT["SPOT_BG"]
SPOT_INK = _LIGHT["SPOT_INK"]
CHIP_INK = _LIGHT["CHIP_INK"]
OK = _LIGHT["OK"]
WARN = _LIGHT["WARN"]
ERR = _LIGHT["ERR"]
OK_HOVER = _LIGHT["OK_HOVER"]
ON_OK = _LIGHT["ON_OK"]
TITLE_BG = _LIGHT["TITLE_BG"]
TITLE_BTN_HOVER = _LIGHT["TITLE_BTN_HOVER"]
TITLE_CLOSE_HOVER = _LIGHT["TITLE_CLOSE_HOVER"]
TITLE_CLOSE_HOVER_FG = _LIGHT["TITLE_CLOSE_HOVER_FG"]
CLEAR_TINT = _LIGHT["CLEAR_TINT"]
CLEAR_BORDER = _LIGHT["CLEAR_BORDER"]
CLEAR_HOVER = _LIGHT["CLEAR_HOVER"]
SETTINGS_BG = _LIGHT["SETTINGS_BG"]
SETTINGS_CARD = _LIGHT["SETTINGS_CARD"]
SWITCH_ON = _LIGHT["SWITCH_ON"]
SWITCH_OFF = _LIGHT["SWITCH_OFF"]
SWITCH_KNOB = _LIGHT["SWITCH_KNOB"]
SWITCH_KNOB_HOVER = _LIGHT["SWITCH_KNOB_HOVER"]
READ_BG = _LIGHT["READ_BG"]
LINK = _LIGHT["LINK"]

_resolved: str = THEME_LIGHT
_preference: str = THEME_LIGHT


def _read_version() -> str:
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        return line or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()
APP_NAME = "Bonjour"
BRAND_LATIN = "epta"
BRAND_CYR = "ёпта"
TAGLINE = "Хочешь в Париж — учи язык"


def system_is_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(val) == 0
    except Exception:  # noqa: BLE001
        return False


def resolve_theme(preference: str | None) -> str:
    pref = (preference or THEME_LIGHT).strip().lower()
    if pref not in THEME_CHOICES:
        pref = THEME_LIGHT
    if pref == THEME_AUTO:
        return THEME_DARK if system_is_dark() else THEME_LIGHT
    return pref


def apply_theme(preference: str | None = None) -> str:
    """Push palette into module tokens + CTk appearance. Returns resolved light|dark."""
    global _resolved, _preference
    global BG, SURFACE, FIELD, LINE, LINE_STRONG, INK, INK_SOFT, INK_FAINT
    global ACCENT, ACCENT_HOVER, ON_ACCENT, CHIP_BG, CHIP_BORDER, CHIP_HOVER, CHIP_INK
    global OK, WARN, ERR, TITLE_BG, TITLE_BTN_HOVER, TITLE_CLOSE_HOVER, TITLE_CLOSE_HOVER_FG
    global CLEAR_TINT, CLEAR_BORDER, CLEAR_HOVER, SETTINGS_BG, SETTINGS_CARD
    global SWITCH_ON, SWITCH_OFF, SWITCH_KNOB, SWITCH_KNOB_HOVER, READ_BG, LINK

    pref = (preference or THEME_LIGHT).strip().lower()
    if pref not in THEME_CHOICES:
        pref = THEME_LIGHT
    _preference = pref
    resolved = resolve_theme(pref)
    _resolved = resolved
    pal = _DARK if resolved == THEME_DARK else _LIGHT
    for key, val in pal.items():
        globals()[key] = val
    ctk.set_appearance_mode("Dark" if resolved == THEME_DARK else "Light")
    ctk.set_default_color_theme("green")
    return resolved


def apply_appearance() -> None:
    """Back-compat boot: light until settings load calls apply_theme."""
    apply_theme(THEME_LIGHT)


def current_preference() -> str:
    return _preference


def current_resolved() -> str:
    return _resolved


# ── contrast (WCAG relative luminance) ────────────────────────
def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexs: str) -> float:
    """WCAG relative luminance 0..1 for a #rrggbb colour."""
    h = str(hexs).lstrip("#")
    if len(h) != 6:
        return 0.0
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio 1..21 between two #rrggbb colours."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_text(bg: str, dark: str = "#141414", light: str = "#ffffff") -> str:
    """Pick the text colour (dark or light) that reads best on `bg`.

    Used anywhere a label sits on an accent/surface fill so the foreground is
    never the same as the background (the black-on-black tab bug).
    """
    return dark if contrast_ratio(bg, dark) >= contrast_ratio(bg, light) else light


def ui_font(size: int = FONT_UI_SIZE, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_UI, size=size, weight=weight)


def mdl2_font(size: int = 15) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_MDL2, size=size)