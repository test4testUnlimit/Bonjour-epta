"""Expansions the text hands you for free: «Full Name (ABC)» and «ABC (Full Name)».

Works with an empty dictionary — that is the point. A one-off project acronym
spelled out once in the same paragraph gets decoded without anyone curating it.
"""

from __future__ import annotations

import re

from .store import norm_key

_PAREN = re.compile(r"\(([^()]{2,90})\)")
_WORD_BEFORE = re.compile(r"([A-Za-z0-9][A-Za-z0-9&/.\-']*)\s*$")
_ACRONYMISH = re.compile(r"^[A-Z][A-Za-z0-9&/.\-]{1,9}$")
_SPLIT = re.compile(r"[\s\-/]+")
_FILLER = {"of", "the", "and", "for", "in", "to", "a", "an", "&", "on", "at", "with", "по", "и"}
_MAX_WORDS = 10


def _words(phrase: str) -> list[str]:
    return [w for w in _SPLIT.split(phrase.strip()) if w]


def _walk(letters: list[str], words: list[str], li: int, wi: int) -> bool:
    if li == len(letters):
        return all(w.lower().strip(".,") in _FILLER for w in words[wi:])
    if wi >= len(words):
        return False
    w = words[wi]
    if w and w[0].upper() == letters[li]:
        # a single word may supply several consecutive letters (HiPot → HP/HIPOT)
        k = 1
        while True:
            if _walk(letters, words, li + k, wi + 1):
                return True
            if li + k < len(letters) and k < len(w) and w[k].upper() == letters[li + k]:
                k += 1
            else:
                break
    if w.lower().strip(".,") in _FILLER and _walk(letters, words, li, wi + 1):
        return True
    return False


def initials_match(acronym: str, phrase: str) -> bool:
    """True if the phrase spells out the acronym (fillers may be skipped)."""
    letters = [c for c in acronym.upper() if c.isalpha()]
    words = _words(phrase)
    if not letters or not words or len(words) > _MAX_WORDS:
        return False
    return _walk(letters, words, 0, 0)


def inline_map(text: str) -> dict[str, str]:
    """key → expansion found in this very text. First definition wins."""
    t = text or ""
    found: dict[str, str] = {}
    for m in _PAREN.finditer(t):
        inner = m.group(1).strip()
        head = t[: m.start()]

        # «Coordinate Measuring Machine (CMM)»
        if _ACRONYMISH.match(inner) and " " not in inner:
            words = _words(head)[-(_MAX_WORDS):]
            n_letters = sum(1 for c in inner if c.isalpha())
            for take in range(n_letters, len(words) + 1):
                phrase = " ".join(words[-take:])
                if initials_match(inner, phrase):
                    found.setdefault(norm_key(inner.replace(".", "")), phrase)
                    break
            continue

        # «CMM (Coordinate Measuring Machine)»
        wm = _WORD_BEFORE.search(head)
        if wm and _ACRONYMISH.match(wm.group(1)) and initials_match(wm.group(1), inner):
            found.setdefault(norm_key(wm.group(1).replace(".", "")), inner)
    return found
