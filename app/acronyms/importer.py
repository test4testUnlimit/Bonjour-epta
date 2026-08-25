"""Confluence-style acronym table -> pack entries, with a public/internal call.

The classifier is deliberately pessimistic: a row has to prove it is generic
industry vocabulary to be called public. Anything mentioning a site, a product,
a codename, an internal system or a named colleague stays on the local disk.

Used by both `scripts/import_confluence.py` (batch) and the dictionary window
(paste a table, see the split, save) — so it lives in the package, not in
`scripts/`, and ships inside the build.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .store import BUILTIN_DIR, LOCAL_DIR, norm_key

__all__ = [
    "DOMAIN_HINTS",
    "INTERNAL_MARKERS",
    "LOCAL_MARKERS_FILE",
    "Row",
    "classify",
    "guess_domains",
    "local_markers",
    "load_keep",
    "parse",
    "repo_pairs",
    "squash",
    "to_entry",
    "write_pack",
]


# ── internal markers ────────────────────────────────────────
# (label, pattern) — matched case-insensitively against term + expansion + notes.
# Anything that hits one of these stays on the local disk.
#
# The shipped list is employer-agnostic on purpose. Your own site names,
# product codenames, internal systems and line ids go in
# ~/.bonjur-epta/internal_markers.json:
#
#     [["site", "\\byour ?plant\\b|\\bYP\\d\\b"],
#      ["codename", "\\bproject-?one\\b|\\bproject-?two\\b"]]
#
# That file is worth writing even though the default verdict is already
# "internal": a marker beats GENERIC_HINTS, so without it a row like
# "process control at <your site>" can be talked into "public".

INTERNAL_MARKERS: list[tuple[str, str]] = [
    ("internal url", r"https?://[^\s]*(?:confluence|jira|sharepoint|intranet|\.corp\b|\.internal\b)"),
    ("internal system", r"\b(?:confluence|jira|sharepoint|servicenow)\b"),
    ("person/opinion", r"\bper [A-Z][a-z]+ [A-Z][a-z]+|\bscrewed up\b|\blol\b|\bstupid\b"
                       r"|\bgarbage\b|\bhated\b|\bfinally died\b|\bnobody uses\b"),
]

LOCAL_MARKERS_FILE = LOCAL_DIR.parent / "internal_markers.json"


def local_markers() -> list[tuple[str, str]]:
    """Site-specific markers from LOCAL_MARKERS_FILE. Missing file → none."""
    try:
        raw = json.loads(LOCAL_MARKERS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — absent or malformed: ship-only defaults
        return []
    out: list[tuple[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            label, pat = item
            re.compile(str(pat))
        except Exception:  # noqa: BLE001 — one bad row must not kill the import
            continue
        out.append((str(label), str(pat)))
    return out


_INTERNAL_RE = [
    (label, re.compile(pat, re.I))
    for label, pat in (*INTERNAL_MARKERS, *local_markers())
]

# A row may only be *considered* public if it looks like textbook industry
# vocabulary. Either the term is already in a repo pack (proof it is generic),
# or the definition reads like a standard process/measurement noun.
GENERIC_HINTS = re.compile(
    r"\b(statistical|standard|international|iso\b|ansi|asme|astm|sae\b|aiag|nist|ipc\b|nfpa"
    r"|process control|measurement|tolerance|calibration|inspection|maintenance|assembly"
    r"|controller|protocol|spectroscop|microscop|welding|machining|torque|voltage|current"
    r"|resistance|temperature|humidity|pressure|bill of materials|purchase order"
    r"|failure mode|root cause|corrective action|preventive|lean\b|six sigma|kaizen)\b",
    re.I,
)

# Rows whose "term" is obviously not an acronym (a vendor, a person, a product).
_NOT_A_TERM = re.compile(r"^(?:acronym|term|expansion|definition|background|notes)\b", re.I)

# domain guessing for ranking — first match wins, order matters
DOMAIN_HINTS: list[tuple[str, str]] = [
    ("battery", r"\bcell\b|\bmodule\b|\bpack\b|anode|cathode|electrode|electrolyte|jelly ?roll"
                r"|busbar|bus bar|wire bond|\bBMS\b|state of charge|kwh\b"),
    ("metrology", r"\bCMM\b|calibrat|gauge|gage|measurement system|scan|metrolog|datum|GD&T|dimensional"),
    ("quality", r"\bquality\b|defect|non-?conform|scrap|rework|yield|audit|containment|8D\b"
                r"|corrective|FMEA|PPAP|SPC\b|inspection"),
    ("automation", r"\bPLC\b|robot|conveyor|HMI\b|SCADA|servo|actuator|fixture|gripper|vision system"),
    ("manufacturing", r"\bline\b|station|assembly|production|takt|cycle time|throughput|shift\b|tooling"),
    ("logistics", r"\bwarehouse\b|\bkit\b|\bkitting\b|supplier|shipment|inventory|material flow"),
    ("it", r"\bdatabase\b|\bAPI\b|\bserver\b|software|dashboard|query|\bSQL\b|network"),
    ("safety", r"\bsafety\b|\bLOTO\b|lockout|\bPPE\b|hazard|ergonom"),
    ("hr", r"\bemployee\b|\bshift lead\b|\bheadcount\b|training|onboard"),
]

_DOMAIN_RE = [(name, re.compile(pat, re.I)) for name, pat in DOMAIN_HINTS]


# ── parsing ─────────────────────────────────────────────────


@dataclass
class Row:
    term: str
    expansion: str
    notes: str = ""
    verdict: str = "internal"
    reasons: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)
    ru: str = ""  # a pasted table never has one; the AI answer does


_TERM_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9&/;:.\-'’ ]{0,28}$")
_LOOKS_ACRONYM = re.compile(r"[A-Z0-9]{2}")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip(" \t\u200b")


def _is_term_line(line: str) -> bool:
    """A bare term on its own line: short, shouty, no sentence punctuation."""
    t = _clean(line)
    if not t or len(t) > 28 or _NOT_A_TERM.match(t):
        return False
    if t.endswith((".", ",", ":", ";")) or t.count(" ") > 1:
        return False
    if not (_TERM_SHAPE.match(t) and _LOOKS_ACRONYM.search(t)):
        return False
    head = t.split(" ")[0]
    if not head.isupper() and not head.isdigit() and not head[:2].isupper():
        return False
    # "21700 Battery Cells" is a definition, "TIA Portal" is a term
    return sum(1 for c in t if c.islower()) <= 6


def parse(text: str) -> list[Row]:
    """Tolerant parser: proper TSV rows and the loose browser-copy shape."""
    rows: list[Row] = []
    pending: Row | None = None

    def flush() -> None:
        nonlocal pending
        # an expansion with no capital is commentary, not a definition
        # ("PMI" -> "lol, that finally died")
        if pending and pending.term and pending.expansion and any(c.isupper() for c in pending.expansion):
            rows.append(pending)
        pending = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not _clean(line):
            continue
        cells = [_clean(c) for c in line.split("\t")]
        cells = [c for c in cells if c] or [""]

        if len(cells) >= 2 and _is_term_line(cells[0]):
            # full row on one line: TERM \t expansion \t notes
            flush()
            if _NOT_A_TERM.match(cells[0]):
                continue
            pending = Row(term=cells[0], expansion=cells[1], notes=" ".join(cells[2:]))
            flush()
            continue

        if len(cells) == 1 and _is_term_line(cells[0]):
            flush()
            pending = Row(term=cells[0], expansion="")
            continue

        if pending is None:
            continue  # stray prose before the first term

        # continuation lines belong to the open row
        if not pending.expansion:
            pending.expansion = cells[0]
            if len(cells) > 1:
                pending.notes = " ".join(cells[1:])
        else:
            pending.notes = _clean(pending.notes + " " + " ".join(cells))

    flush()
    return _split_expansion(rows)


_DEF_SPLIT = re.compile(r"^(?P<exp>[^.:;]{3,80}?)\s*[:.]\s+(?P<rest>[A-Z(].*)$", re.S)


def _split_expansion(rows: list[Row]) -> list[Row]:
    """`Current Collector: The stamped aluminum...` -> expansion + notes."""
    for r in rows:
        m = _DEF_SPLIT.match(r.expansion)
        if m and len(r.expansion) > 90:
            r.notes = _clean(m.group("rest") + " " + r.notes)
            r.expansion = _clean(m.group("exp"))
        r.expansion = _clean(r.expansion).rstrip(".")
        r.notes = _clean(r.notes)
    return rows


# ── classification ──────────────────────────────────────────


def squash(s: str) -> str:
    """`First-Pass Yield` and `First Pass Yield` collapse to the same string."""
    return re.sub(r"[^A-Z0-9]+", "", (s or "").upper())


def repo_pairs() -> set[tuple[str, str]]:
    """(term, expansion) already shipped in git — importing them again is noise."""
    known: set[tuple[str, str]] = set()
    for f in sorted(BUILTIN_DIR.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for e in raw.get("entries", []) if isinstance(raw, dict) else raw:
            if not isinstance(e, dict) or not e.get("term"):
                continue
            exp = squash(e.get("expansion", ""))
            for name in (e["term"], *(e.get("aliases") or [])):
                known.add((norm_key(name), exp))
    return known


def classify(row: Row, known: set[tuple[str, str]]) -> None:
    pair = (norm_key(row.term), squash(row.expansion))
    if pair in known:
        row.verdict, row.reasons = "known", ["already shipped in a repo pack"]
        return
    blob = f"{row.term} {row.expansion} {row.notes}"
    hits = [label for label, rx in _INTERNAL_RE if rx.search(blob)]
    if hits:
        row.verdict, row.reasons = "internal", hits
        return
    if GENERIC_HINTS.search(f"{row.expansion} {row.notes}"):
        row.verdict, row.reasons = "public", ["reads as generic industry term"]
        return
    row.verdict, row.reasons = "internal", ["no proof it is public (default)"]


def guess_domains(row: Row) -> list[str]:
    blob = f"{row.term} {row.expansion} {row.notes}"
    found = [name for name, rx in _DOMAIN_RE if rx.search(blob)]
    return found[:3]


# ── output ──────────────────────────────────────────────────


def to_entry(row: Row, keep: dict[tuple[str, str], dict], *, default_domain=("local",)) -> dict:
    """`default_domain` only kicks in when nothing could be guessed from the text."""
    prev = keep.get((norm_key(row.term), norm_key(row.expansion)), {})
    entry = {
        "term": row.term,
        "expansion": row.expansion,
        "ru": prev.get("ru") or row.ru,
        "where": prev.get("where") or row.notes,
        "domain": prev.get("domain") or row.domain or list(default_domain),
    }
    if prev.get("aliases"):
        entry["aliases"] = prev["aliases"]
    return {k: v for k, v in entry.items() if v not in ("", [])} | {"term": row.term, "expansion": row.expansion}


def load_keep(path: Path, overwrite: bool) -> dict[tuple[str, str], dict]:
    """Existing hand-written text, so a re-import does not wipe translations."""
    if overwrite or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    rows = raw.get("entries", []) if isinstance(raw, dict) else raw
    return {
        (norm_key(e.get("term", "")), norm_key(e.get("expansion", ""))): e
        for e in rows
        if isinstance(e, dict)
    }


def write_pack(path: Path, pack_id: str, title: str, priority: int, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"id": pack_id, "title": title, "priority": priority, "entries": entries}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
