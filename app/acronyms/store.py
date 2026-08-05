"""Acronym packs: load JSON, merge, build lookup index. No Tk, no network.

Two pack locations:
  * repo   — app/acronyms/data/*.json   (public industry terms, ships with the app)
  * local  — ~/.bonjur-epta/packs/*.json (site-specific, never committed)

Pack file is either {"id","title","priority","entries":[...]} or a bare list.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("bonjur.acronyms")

BUILTIN_DIR = Path(__file__).resolve().parent / "data"
LOCAL_DIR = Path.home() / ".bonjur-epta" / "packs"

# pack id → default priority when the file does not declare one
_DEFAULT_PRIORITY = {"user": 40, "gftx": 30}
_PRIORITY_FALLBACK = 10

_WS = re.compile(r"\s+")


def norm_key(s: str) -> str:
    """Lookup key: upper-case, single spaces, curly apostrophe folded."""
    t = (s or "").strip().upper().replace("’", "'")
    return _WS.sub(" ", t)


@dataclass(frozen=True)
class Entry:
    term: str
    expansion: str
    ru: str = ""
    where: str = ""
    domain: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    source_title: str = ""
    source_url: str = ""
    pack: str = ""
    priority: int = _PRIORITY_FALLBACK

    @property
    def ident(self) -> tuple[str, str]:
        """Identity for cross-pack dedupe."""
        return (norm_key(self.term), norm_key(self.expansion))

    @classmethod
    def from_dict(cls, d: dict, *, pack: str = "", priority: int = _PRIORITY_FALLBACK) -> Entry | None:
        term = str(d.get("term") or "").strip()
        expansion = str(d.get("expansion") or "").strip()
        if not term or not expansion:
            return None
        dom = d.get("domain") or ()
        if isinstance(dom, str):
            dom = (dom,)
        al = d.get("aliases") or ()
        if isinstance(al, str):
            al = (al,)
        src = d.get("source") or {}
        if not isinstance(src, dict):
            src = {}
        return cls(
            term=term,
            expansion=expansion,
            ru=str(d.get("ru") or "").strip(),
            where=str(d.get("where") or "").strip(),
            domain=tuple(str(x).strip().lower() for x in dom if str(x).strip()),
            aliases=tuple(str(x).strip() for x in al if str(x).strip()),
            source_title=str(src.get("title") or "").strip(),
            source_url=str(src.get("url") or "").strip(),
            pack=pack,
            priority=priority,
        )


@dataclass
class Pack:
    id: str
    title: str
    origin: str  # "repo" | "local"
    path: Path
    priority: int = _PRIORITY_FALLBACK
    entries: list[Entry] = field(default_factory=list)
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.entries)


class Index:
    """Immutable-ish lookup built from a list of entries."""

    def __init__(self, entries: list[Entry]) -> None:
        from . import detect  # local: detect imports norm_key from here

        self.by_key: dict[str, list[Entry]] = {}
        self.phrases: list[str] = []  # normalized multi-word keys
        self.literals: list[str] = []  # Cpk, Ra, Kanban — spellings no shape rule accepts
        self.entries: list[Entry] = []  # deduped, in pack order — for browsing
        seen: set[tuple[str, str]] = set()
        for e in entries:
            if e.ident in seen:
                continue  # same term+expansion already came from a higher pack
            seen.add(e.ident)
            self.entries.append(e)
            for raw in (e.term, *e.aliases):
                k = norm_key(raw)
                if not k:
                    continue
                bucket = self.by_key.setdefault(k, [])
                if e not in bucket:
                    bucket.append(e)
                if " " in k:
                    if k not in self.phrases:
                        self.phrases.append(k)
                elif raw not in self.literals and not detect.shape_ok(raw.strip()):
                    self.literals.append(raw.strip())
        self._phrase_re = self._compile(self.phrases, ignore_case=True)
        self._literal_re = self._compile(self.literals, ignore_case=False)

    @staticmethod
    def _compile(items: list[str], *, ignore_case: bool):
        if not items:
            return None
        parts = []
        # longest first so "TAKT TIME" wins over a hypothetical "TAKT"
        for p in sorted(items, key=len, reverse=True):
            esc = re.escape(p)
            # a short symbol (Ra, Cp) must keep its case; a word (Kanban) need not
            parts.append(esc if ignore_case or len(p) < 5 else f"(?i:{esc})")
        flags = re.I if ignore_case else 0
        return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(parts) + r")(?![A-Za-z0-9])", flags)

    @property
    def phrase_re(self):
        return self._phrase_re

    @property
    def literal_re(self):
        """Dictionary terms the shape rules cannot see — matched verbatim."""
        return self._literal_re

    def get(self, key: str) -> list[Entry]:
        k = norm_key(key)
        hit = self.by_key.get(k)
        if hit:
            return hit
        # plural / possessive: PPAPs, PPAP's, NCMs
        if k.endswith("'S"):
            hit = self.by_key.get(k[:-2])
        elif k.endswith("S") and len(k) > 2:
            hit = self.by_key.get(k[:-1])
        return hit or []

    def __len__(self) -> int:
        return len(self.by_key)

    @property
    def empty(self) -> bool:
        return not self.by_key


EMPTY_INDEX = Index([])


# ── pack loading ────────────────────────────────────────────


def _read_pack(path: Path, origin: str) -> Pack:
    pid = path.stem.lower()
    pack = Pack(id=pid, title=pid, origin=origin, path=path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        pack.error = str(exc)
        log.warning("acronym pack unreadable %s: %s", path.name, exc)
        return pack
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("entries") or []
        pack.id = str(raw.get("id") or pid).lower()
        pack.title = str(raw.get("title") or pack.id)
        try:
            pack.priority = int(raw.get("priority", _DEFAULT_PRIORITY.get(pack.id, _PRIORITY_FALLBACK)))
        except Exception:  # noqa: BLE001
            pack.priority = _PRIORITY_FALLBACK
    else:
        pack.error = "unexpected JSON shape"
        return pack
    if pack.title == pack.id:
        pack.priority = _DEFAULT_PRIORITY.get(pack.id, pack.priority)
    for row in rows:
        if not isinstance(row, dict):
            continue
        e = Entry.from_dict(row, pack=pack.id, priority=pack.priority)
        if e is not None:
            pack.entries.append(e)
    return pack


def discover_packs() -> list[Pack]:
    """All packs on disk, local before repo (local wins ties in the index)."""
    packs: list[Pack] = []
    for d, origin in ((LOCAL_DIR, "local"), (BUILTIN_DIR, "repo")):
        try:
            # "_name.json" is scratch (import review dumps, backups) — not a pack
            files = sorted(f for f in d.glob("*.json") if not f.name.startswith("_")) if d.is_dir() else []
        except Exception:  # noqa: BLE001
            files = []
        for f in files:
            packs.append(_read_pack(f, origin))
    packs.sort(key=lambda p: -p.priority)
    return packs


# ── module-level cached index ───────────────────────────────

_lock = threading.Lock()
_packs: list[Pack] | None = None
_index: Index | None = None
_enabled: dict[str, bool] = {}


def set_enabled(mapping: dict | None) -> None:
    """Pack id → on/off (missing id = on). Drops the cached index."""
    global _enabled
    with _lock:
        _enabled = {str(k): bool(v) for k, v in (mapping or {}).items()}
    reload()


def is_enabled(pack_id: str) -> bool:
    return _enabled.get(pack_id, True)


def reload() -> None:
    global _packs, _index
    with _lock:
        _packs = None
        _index = None


def packs() -> list[Pack]:
    global _packs
    with _lock:
        if _packs is None:
            _packs = discover_packs()
        return list(_packs)


def index() -> Index:
    """Merged index over enabled packs. Built once, cached until reload()."""
    global _index
    with _lock:
        if _index is not None:
            return _index
    found = packs()  # outside the lock — discover_packs does file IO
    rows: list[Entry] = []
    for p in found:
        if is_enabled(p.id):
            rows.extend(p.entries)
    built = Index(rows)
    with _lock:
        _index = built
    return built


def warm() -> None:
    """Build the index off the UI thread — call once at startup."""
    threading.Thread(target=index, name="acronym-index", daemon=True).start()


def local_dir() -> Path:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_DIR
