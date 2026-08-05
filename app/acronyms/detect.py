"""Find acronym candidates in text. Pure regex + stop-lists, no dictionary needed.

Shapes we accept: PPAP · 8D · GD&T · I/O · GC-MS · TL;DR · 1:1 · F.A.I. · CpK · 4680.

Two rejection levels, because the dictionary must always win over a guess:
  * hard drop  — never a candidate (common words, units right after a number)
  * noise flag — still a candidate so a dictionary hit can rescue it, but never
                 reported as «не знаю» (roman numerals, CamelCase, bare digits,
                 ALL-CAPS SHOUTING).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .store import norm_key

# one pass over the text; punctuation inside a token is allowed, trimmed after
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9&/;:.\-']*")
_TRIM = " \t\n.,;:!?\"'`()[]{}«»„“”…–—/\\&-"

_SHAPE_CAPS = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")  # PPAP, EOW, QE, BMA45
_SHAPE_NUMLED = re.compile(r"^[0-9]{1,2}[A-Z]{1,3}$")  # 8D, 5S, 5W
_SHAPE_COMPOUND = re.compile(r"^[A-Z0-9]{1,6}(?:[&/;:.\-][A-Z0-9]{1,6}){1,3}$")  # GD&T, I/O
_SHAPE_DOTTED = re.compile(r"^(?:[A-Za-z]\.){2,4}[A-Za-z]?$")  # F.A.I. / F.A.I
_SHAPE_CAMEL = re.compile(r"^[A-Z][a-z]{1,4}[A-Z][A-Za-z]{0,5}$")  # CpK, HiPot
_SHAPE_DIGITS = re.compile(r"^[0-9]{4,5}$")  # 4680, 18650, 21700
_ROMAN = re.compile(r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
# two-letter romans are far more often acronyms (DC, MM, CM, MI, DI, XL), so only
# the ones that really do read as numbers are muted at that length
_ROMAN_SHORT = {"II", "IV", "VI", "IX", "XI"}

# all-caps words that are words, not acronyms worth explaining
_STOP = {
    "A", "AN", "THE", "AND", "OR", "NOT", "BUT", "FOR", "ALL", "ANY", "NEW", "OLD",
    "TOP", "END", "ALSO", "WITH", "FROM", "THIS", "THAT", "THESE", "THOSE", "WILL",
    "MUST", "PLEASE", "THANKS", "OK", "OKAY", "YES", "NO", "NONE",
    "OF", "TO", "IN", "ON", "AT", "BY", "IS", "IT", "AS", "BE", "WE", "US", "IF",
    "DO", "GO", "SO", "UP", "MY", "ME", "HE", "SHE", "YOU", "ARE", "WAS", "HAS",
    "HAD", "OUT", "OFF", "ONE", "TWO", "TEN", "NOW", "WHY", "HOW", "WHO", "WHAT",
    "WHEN", "SEE", "USE", "GET", "PUT", "RUN", "FIX", "ADD", "SET", "LET", "MAY",
    "USA", "USD", "EUR", "GBP", "RUB", "UK", "EU", "UN", "TV", "PDF", "CSV", "XLS",
    "XLSX", "DOC", "DOCX", "PNG", "JPG", "JPEG", "GIF", "ZIP", "URL", "WWW",
    "HTTP", "HTTPS", "EMAIL",
}

# dropped only when they follow a number: "5 MM", "400 KW", "10 AM"
_UNITS = {
    "MM", "CM", "KM", "UM", "NM", "IN", "FT", "MIL", "THOU",
    "KG", "MG", "LB", "LBS", "OZ",
    "MS", "US", "HR", "HRS", "MIN", "SEC",
    "MV", "KV", "MA", "KA", "KW", "MW", "WH", "KWH", "MWH",
    "HZ", "KHZ", "MHZ", "GHZ", "RPM", "PSI", "BAR", "PA", "KPA", "MPA",
    "DEG", "PPM", "PPB", "DB", "DPI", "PX", "GB", "MB", "TB",
    "AM", "PM", "AC", "DC",
}
_NUM_BEFORE = re.compile(r"\d\s{0,2}$")


@dataclass(frozen=True)
class Candidate:
    raw: str  # exactly as written
    key: str  # normalized lookup key
    start: int
    end: int
    noise: bool = False  # dictionary may rescue it; never shown as «не знаю»


def _shouty(text: str) -> bool:
    """Whole message in caps → all-caps tokens are words, not acronyms."""
    letters = [c for c in text if c.isalpha() and c.isascii()]
    if len(letters) < 40:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.6


def _shape(tok: str) -> tuple[bool, bool]:
    """(is_candidate, is_noise) for a trimmed token."""
    if _SHAPE_DOTTED.match(tok):
        return True, False
    if _SHAPE_CAPS.match(tok):
        return sum(1 for c in tok if c.isalpha()) >= 2, False
    if _SHAPE_NUMLED.match(tok):
        return True, False
    if _SHAPE_COMPOUND.match(tok):
        return any(c.isalpha() for c in tok), False
    if _SHAPE_CAMEL.match(tok):
        return True, True
    if _SHAPE_DIGITS.match(tok):
        return True, True
    return False, False


def shape_ok(token: str) -> bool:
    """Would this spelling ever be found by candidates()? The index asks, so it
    knows which of its own terms (Cpk, Ra, Kanban) need a verbatim regex."""
    tok = (token or "").strip(_TRIM)
    if len(tok) < 2:
        return False
    ok, _ = _shape(tok)
    return ok and norm_key(tok.replace(".", "") if _SHAPE_DOTTED.match(tok) else tok) not in _STOP


def candidates(text: str) -> list[Candidate]:
    """Shape-valid tokens in order of appearance, hard noise already dropped."""
    t = text or ""
    if not t.strip():
        return []
    shouty = _shouty(t)
    out: list[Candidate] = []
    for m in _TOKEN.finditer(t):
        raw = m.group(0)
        lead = len(raw) - len(raw.lstrip(_TRIM))
        tok = raw.strip(_TRIM)
        if len(tok) < 2:
            continue

        ok, noise = _shape(tok)
        if not ok:
            continue

        start = m.start() + lead
        key = norm_key(tok.replace(".", "") if _SHAPE_DOTTED.match(tok) else tok)
        if not key or key in _STOP:
            continue
        if key in _UNITS and _NUM_BEFORE.search(t[max(0, start - 4) : start]):
            continue
        if key in _ROMAN_SHORT or (len(key) > 2 and _ROMAN.match(key)):
            noise = True  # section IX — unless the dictionary knows it
        if shouty and tok.isupper():
            noise = True

        out.append(Candidate(raw=tok, key=key, start=start, end=start + len(tok), noise=noise))
    return out


def dict_hits(text: str, *regexes) -> list[Candidate]:
    """Terms only the dictionary can spot: phrases («Takt time») and odd
    spellings («Cpk», «Kanban»). Regexes come from the index."""
    t = text or ""
    if not t.strip():
        return []
    out: list[Candidate] = []
    for rx in regexes:
        if rx is None:
            continue
        out += [
            Candidate(raw=m.group(0), key=norm_key(m.group(0)), start=m.start(), end=m.end())
            for m in rx.finditer(t)
        ]
    return out
