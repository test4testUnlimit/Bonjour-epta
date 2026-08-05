"""Candidates → ranked meanings. Local, offline, a few milliseconds."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from . import detect, inline
from .store import Entry, Index, index as global_index

MAX_HITS = 40
MAX_UNKNOWN = 12


@dataclass
class Hit:
    key: str
    raw: str  # as written in the text
    entries: list[Entry] = field(default_factory=list)
    inline: str = ""  # expansion the text itself provided
    ambiguous: bool = False  # two readings scored too close to call

    @property
    def best(self) -> Entry | None:
        return self.entries[0] if self.entries else None


@dataclass
class Report:
    hits: list[Hit] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    ms: float = 0.0

    @property
    def count(self) -> int:
        return len(self.hits)

    def __bool__(self) -> bool:
        return bool(self.hits or self.unknown)


def _score(e: Entry, dominant: set[str], ctx_packs: set[str]) -> int:
    s = min(max(e.priority, 0), 40) // 10  # user 4 · gftx 3 · repo 1
    if dominant and any(d in dominant for d in e.domain):
        s += 3
    if e.pack in ctx_packs:
        s += 2
    return s


def explain(text: str, *, idx: Index | None = None) -> Report:
    """Full breakdown for the main window. No junk gate — the user asked for it."""
    t0 = time.perf_counter()
    ix = idx if idx is not None else global_index()
    rep = Report()
    if not (text or "").strip():
        return rep

    cands = detect.candidates(text) + detect.dict_hits(text, ix.phrase_re, ix.literal_re)
    cands.sort(key=lambda c: (c.start, -len(c.raw)))
    inl = inline.inline_map(text)

    # first pass — collect context from the unambiguous matches
    resolved: list[tuple[object, list[Entry]]] = []
    seen: set[str] = set()
    covered: list[tuple[int, int]] = []  # spans taken by phrases
    domains: Counter[str] = Counter()
    ctx_packs: set[str] = set()

    for c in cands:
        if any(a <= c.start and c.end <= b for a, b in covered):
            continue  # inside a phrase we already took ("TIME" in "TAKT TIME")
        if c.key in seen:
            continue
        entries = ix.get(c.key)
        if entries and " " in c.key:
            covered.append((c.start, c.end))
        if not entries and c.key not in inl:
            if not c.noise:
                resolved.append((c, []))
                seen.add(c.key)
            continue
        seen.add(c.key)
        resolved.append((c, list(entries)))
        if len(entries) == 1:
            e = entries[0]
            domains.update(e.domain)
            ctx_packs.add(e.pack)

    dominant = {d for d, _ in domains.most_common(3)}

    for c, entries in resolved:
        if not entries:
            if c.key in inl:
                rep.hits.append(Hit(key=c.key, raw=c.raw, inline=inl[c.key]))
            elif len(rep.unknown) < MAX_UNKNOWN and c.raw not in rep.unknown:
                rep.unknown.append(c.raw)
            continue
        if len(entries) > 1:
            scored = sorted(entries, key=lambda e: -_score(e, dominant, ctx_packs))
            gap = _score(scored[0], dominant, ctx_packs) - _score(scored[1], dominant, ctx_packs)
            entries = scored
            amb = gap < 2
        else:
            amb = False
        rep.hits.append(
            Hit(key=c.key, raw=c.raw, entries=entries, inline=inl.get(c.key, ""), ambiguous=amb)
        )
        if len(rep.hits) >= MAX_HITS:
            break

    rep.ms = (time.perf_counter() - t0) * 1000.0
    return rep


def quick_scan(text: str, *, idx: Index | None = None) -> int:
    """How many known acronyms are in there — drives the chip, so it stays cheap
    and respects the same junk gate the chip uses."""
    t = (text or "").strip()
    if not t:
        return 0
    from ..chip_offer import _looks_code_or_junk

    if _looks_code_or_junk(t):
        return 0
    ix = idx if idx is not None else global_index()
    if ix.empty:
        return 0
    keys: set[str] = set()
    for c in detect.candidates(t):
        if c.key not in keys and ix.get(c.key):
            keys.add(c.key)
    for c in detect.dict_hits(t, ix.phrase_re, ix.literal_re):
        keys.add(c.key)
    return len(keys)
