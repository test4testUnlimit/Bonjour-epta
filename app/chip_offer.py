"""When to offer the «чивобля?» chip for a selection (fast, offline)."""

from __future__ import annotations

from collections import Counter

# target ISO code → script we treat as "already readable" for that language
_TARGET_SCRIPT: dict[str, str] = {
    "ru": "cyrillic",
    "uk": "cyrillic",
    "en": "latin",
    "de": "latin",
    "fr": "latin",
    "es": "latin",
    "it": "latin",
    "pt": "latin",
    "pl": "latin",
    "tr": "latin",
    "nl": "latin",
    "sv": "latin",
    "cs": "latin",
    "fi": "latin",
    "zh": "cjk",
    "ja": "cjk",
    "ko": "cjk",
    "ar": "arabic",
    "hi": "devanagari",
}


def _script_of(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    o = ord(ch)
    if 0x0400 <= o <= 0x052F or 0x2DE0 <= o <= 0x2DFF or 0xA640 <= o <= 0xA69F:
        return "cyrillic"
    if (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0x3040 <= o <= 0x30FF
        or 0x31F0 <= o <= 0x31FF
        or 0xAC00 <= o <= 0xD7AF
        or 0x1100 <= o <= 0x11FF
    ):
        return "cjk"
    if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
        return "arabic"
    if 0x0900 <= o <= 0x097F:
        return "devanagari"
    # Latin (ASCII + common European letters)
    if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or 0x00C0 <= o <= 0x024F:
        return "latin"
    return "other"


def should_offer_chip(text: str, *, target_lang: str) -> bool:
    """
    True → show «чивобля?» near selection.
    Skip: empty, digits/symbols only, text already in target language script.
    Hotkey path is unaffected — only the floating chip.
    """
    t = (text or "").strip()
    if not t:
        return False

    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False  # 123, 3.14, $50, dates without letters

    # mostly numeric noise with a stray letter (e.g. "№12")
    non_space = [c for c in t if not c.isspace()]
    digit_like = sum(1 for c in non_space if c.isdigit() or c in ".,/%$#€₽№+-±")
    if digit_like >= len(non_space) * 0.7 and len(letters) <= 1:
        return False

    buckets = Counter(
        s for c in letters if (s := _script_of(c)) and s != "other"
    )
    if not buckets:
        return True

    dominant, n = buckets.most_common(1)[0]
    if n / len(letters) < 0.55:
        return True  # mixed scripts → likely worth offering

    tgt = (target_lang or "").lower().split("-")[0]
    expected = _TARGET_SCRIPT.get(tgt)
    if expected and dominant == expected:
        return False  # already looks like the language you're translating into
    return True
