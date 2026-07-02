"""Common language codes for UI combos."""

from __future__ import annotations

# (code, label) — code is what APIs expect (ISO 639-1 mostly)
LANGUAGES: list[tuple[str, str]] = [
    ("auto", "Автодетект"),
    ("en", "English"),
    ("ru", "Русский"),
    ("uk", "Українська"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("pt", "Português"),
    ("pl", "Polski"),
    ("tr", "Türkçe"),
    ("zh", "中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("ar", "العربية"),
    ("hi", "हिन्दी"),
    ("nl", "Nederlands"),
    ("sv", "Svenska"),
    ("cs", "Čeština"),
    ("fi", "Suomi"),
]

LANG_LABELS = {code: label for code, label in LANGUAGES}


def codes_for_source() -> list[str]:
    return [c for c, _ in LANGUAGES]


def codes_for_target() -> list[str]:
    return [c for c, _ in LANGUAGES if c != "auto"]


def label_of(code: str) -> str:
    return LANG_LABELS.get(code, code)
