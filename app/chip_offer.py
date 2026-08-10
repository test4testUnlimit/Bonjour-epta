"""When to offer the «чивобля?» chip for a selection (fast, offline)."""

from __future__ import annotations

import re
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

# lab v2 CHIP_FALSE_POS clusters: code / path / id / mash / tech
_RE_PATH = re.compile(
    r"(?i)(?:[a-z]:\\|/home/|/Users/|\\Projects\\|\\app\\|\.py\b|\.json\b|\.ts\b|\.js\b|\.tsx\b|\.cs\b)"
)
_RE_CODE = re.compile(
    r"(?is)"
    r"(^\s*[{\[<])|"  # JSON / HTML / array
    r"(</?[a-z][\w:-]*[\s>])|"  # HTML tag
    r"(\bSELECT\b.+\bFROM\b)|"
    r"(\b(?:def|class|function|const|let|var)\s+\w)|"
    r"(\bimport\s+[\w.]+)|"
    r"(\bfrom\s+[\w.]+\s+import\b)|"
    r"(->\s*str\b)|"
    r"(\bgit\s+\w+)|"
    r"(\bnpm\s+\w+)|"
    r"(\bWHERE\s+\w+\s*=)"
)
_RE_SNAKE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_RE_CAMEL = re.compile(r"^[A-Za-z][a-z0-9]*[A-Z][A-Za-z0-9]*$")
_RE_API_KEY = re.compile(r"(?i)\b(?:sk-|pk-|api[_-]?key)[a-z0-9_-]*")
_RE_HOTKEY = re.compile(
    r"(?i)\b(?:ctrl|alt|shift|win|cmd|meta)\s*\+\s*(?:ctrl|alt|shift|win|cmd|meta|[a-z0-9]|f\d{1,2})\b"
)
_RE_LOREM = re.compile(r"(?i)\blorem\s+ipsum\b")
_RE_TECH_VER = re.compile(
    r"(?i)\b(?:windows|linux|macos|dpi|ctrl|alt|shift|hotkey|monitor)\b.*\d|\d.*\b(?:dpi|%|px|mhz)\b"
)
_VOWELS = set("aeiouyаеёиоуыэюяAEIOUYАЕЁИОУЫЭЮЯ")


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


def _max_run(s: str) -> int:
    best = cur = 0
    prev = ""
    for ch in s:
        if ch == prev:
            cur += 1
        else:
            best = max(best, cur)
            cur = 1
            prev = ch
    return max(best, cur)


def _looks_code_or_junk(text: str) -> bool:
    """True → do not offer chip (lab v2 false-pos: code/path/id/mash/tech)."""
    t = text.strip()
    if not t:
        return True

    if (
        _RE_PATH.search(t)
        or _RE_CODE.search(t)
        or _RE_API_KEY.search(t)
        or _RE_HOTKEY.search(t)
        or _RE_LOREM.search(t)
    ):
        return True

    # elongated / mashed tokens even inside a phrase ("AAAA… veryyyy…")
    words = re.findall(r"[A-Za-zА-Яа-яЁё]+", t)
    stretched = 0
    for w in words:
        if len(w) >= 6 and _max_run(w.lower()) >= 5:
            stretched += 1
        elif len(w) >= 12:
            uniq = len({c.lower() for c in w})
            if uniq <= 4:
                stretched += 1
    if stretched >= 1 and (stretched >= 2 or len(words) <= 8):
        # one long stretch in a short phrase, or several stretches
        if any(len(w) >= 8 and _max_run(w.lower()) >= 5 for w in words):
            return True
        if stretched >= 2:
            return True

    # single-token programming identifiers (no spaces)
    if " " not in t and "\n" not in t and "\t" not in t:
        tok = t.strip("`\"'")
        if _RE_SNAKE.match(tok) or _RE_CAMEL.match(tok):
            return True
        # long unbroken mash / stretch
        letters = [c for c in tok if c.isalpha()]
        if len(letters) >= 10:
            if _max_run(tok.lower()) >= 6:
                return True
            uniq = len({c.lower() for c in letters})
            if uniq <= 4:
                return True
            vowels = sum(1 for c in letters if c in _VOWELS)
            if vowels / len(letters) < 0.15:
                return True

    # tech version noise: "Windows 11 DPI 125%" etc.
    letters = [c for c in t if c.isalpha()]
    digits = sum(1 for c in t if c.isdigit())
    if letters and digits >= 2 and _RE_TECH_VER.search(t):
        words = re.findall(r"[A-Za-zА-Яа-яЁё]+", t)
        if len(words) <= 6:
            return True

    return False


def should_offer_chip(text: str, *, target_lang: str, acronym_scan=None) -> bool:
    """
    True → show «чивобля?» near selection.
    Skip: empty, digits/symbols, code/paths/ids/junk, text already in target script.
    Hotkey path is unaffected — only the floating chip.

    `acronym_scan(text) -> bool` is asked only about text already in the target
    language, and only after the cheap filters have passed — so the dictionary
    is touched for the handful of selections that would otherwise be dropped.
    """
    t = (text or "").strip()
    if not t:
        return False

    # Field H3: stray leading c made «cInturristo» look like camelCase junk.
    # Evaluate chip usefulness on the peeled form (sanitize also peels).
    try:
        from . import auto_catch

        reason = auto_catch.looks_stray_c(t)
        if reason == "lone_c":
            return False
        if reason and reason.startswith("prefix_c+") and len(t) >= 2:
            t = t[1:].lstrip()
            if not t:
                return False
    except Exception:  # noqa: BLE001
        pass

    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False  # 123, 3.14, $50, dates without letters

    # mostly numeric noise with a stray letter (e.g. "№12")
    non_space = [c for c in t if not c.isspace()]
    digit_like = sum(1 for c in non_space if c.isdigit() or c in ".,/%$#€₽№+-±")
    if digit_like >= len(non_space) * 0.7 and len(letters) <= 1:
        return False

    if _looks_code_or_junk(t):
        return False

    buckets = Counter(
        s for c in letters if (s := _script_of(c)) and s != "other"
    )
    if not buckets:
        return True

    dominant, n = buckets.most_common(1)[0]
    mixed = n / len(letters) < 0.55

    tgt = (target_lang or "").lower().split("-")[0]
    expected = _TARGET_SCRIPT.get(tgt)

    # mixed RU+EN tech ("Open файл settings.json") — still skip if path/code-like
    # already handled above; for other mixed natural text, offer
    if mixed:
        return True

    if expected and dominant == expected:
        # Already the language you translate into — the chip only earns its
        # place if the text hides acronyms («Отправь PPAP до EOW»), which a
        # translator would copy across untouched.
        if acronym_scan is None:
            return False
        try:
            return bool(acronym_scan(t))
        except Exception:  # noqa: BLE001
            return False
    return True
