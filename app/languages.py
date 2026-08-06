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


# short RU names for mini-popup header: (английский)
SHORT_RU: dict[str, str] = {
    "auto": "авто",
    "en": "английский",
    "ru": "русский",
    "uk": "украинский",
    "de": "немецкий",
    "fr": "французский",
    "es": "испанский",
    "it": "итальянский",
    "pt": "португальский",
    "pl": "польский",
    "tr": "турецкий",
    "zh": "китайский",
    "ja": "японский",
    "ko": "корейский",
    "ar": "арабский",
    "hi": "хинди",
    "nl": "нидерландский",
    "sv": "шведский",
    "cs": "чешский",
    "fi": "финский",
}


def short_ru(code: str | None) -> str:
    if not code:
        return "авто"
    c = str(code).lower().split("-")[0]
    return SHORT_RU.get(c, c)


# ── alphabet sniffing ────────────────────────────────────────────────
# Not a language detector — just enough to notice that the combo says
# English while the box holds Russian. Picking the wrong source silently
# returns the text unchanged, which reads as "перевод не работает".

SCRIPTS: dict[str, str] = {
    "en": "latin", "de": "latin", "fr": "latin", "es": "latin", "it": "latin",
    "pt": "latin", "pl": "latin", "tr": "latin", "nl": "latin", "sv": "latin",
    "cs": "latin", "fi": "latin",
    "ru": "cyrillic", "uk": "cyrillic",
    "zh": "han", "ja": "kana", "ko": "hangul", "ar": "arabic", "hi": "devanagari",
}


def _script_of_char(ch: str) -> str | None:
    o = ord(ch)
    if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or 0x00C0 <= o <= 0x024F:
        return "latin"
    if 0x0400 <= o <= 0x04FF:
        return "cyrillic"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0x4E00 <= o <= 0x9FFF:
        return "han"
    if 0xAC00 <= o <= 0xD7AF:
        return "hangul"
    if 0x0600 <= o <= 0x06FF:
        return "arabic"
    if 0x0900 <= o <= 0x097F:
        return "devanagari"
    return None


def script_of(text: str | None) -> str | None:
    """Dominant alphabet of `text`, or None when there are no letters to judge."""
    if not text:
        return None
    counts: dict[str, int] = {}
    for ch in text:
        s = _script_of_char(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return None
    best = max(counts, key=lambda k: counts[k])
    # Japanese mixes kana with han; kana anywhere settles it.
    if best == "han" and counts.get("kana"):
        return "kana"
    return best


def script_mismatch(code: str | None, text: str | None) -> bool:
    """True when `text` plainly cannot be in language `code`."""
    if not code or code == "auto":
        return False
    want = SCRIPTS.get(str(code).lower().split("-")[0])
    got = script_of(text)
    if not want or not got:
        return False
    return want != got


def counterpart(code: str | None) -> str:
    """The other half of the everyday pair — used when source and target collide."""
    return "en" if str(code or "").lower().split("-")[0] == "ru" else "ru"


def effective_target(target: str | None, source: str | None, text: str | None) -> str:
    """Which language this text should actually go into.

    With an explicit A→B pair, the direction follows the text: configured ru→en
    and an English selection is not «уже на целевом языке», it is the same pair
    running the other way. With source=auto there is no pair to reverse, so the
    caller's target stands.
    """
    tgt = str(target or "").lower().split("-")[0]
    src = str(source or "").lower().split("-")[0]
    if not tgt or src in ("", "auto") or src == tgt:
        return tgt
    got = script_of(text)
    if got and SCRIPTS.get(tgt) == got and SCRIPTS.get(src) != got:
        return src
    return tgt
