"""Point-translation: selecting text in one pane highlights its counterpart.

How it works (the CAT-tool approach, not true linguistic alignment — that would
need a word-aligner we do not have): on selection we translate just the fragment
with the active provider, then look for that translation as a substring of the
other pane and tag it. A fragment whose translation is not found gets a "?"
marker in the footer so the user knows the mapping was not possible (a name, a
number, or a phrase the engine rendered differently).
"""

from __future__ import annotations

import re

from . import logutil
from . import translators as tr

TAG = "spotlight"
TAG_MISS = "spotlight_miss"

MAX_FRAGMENT = 300


def normalize(text: str) -> str:
    return (text or "").strip()


def find_fragment(haystack: str, needle: str) -> tuple[int, int] | None:
    """Case-insensitive substring hit. Returns (start, end) char offsets or None."""
    if not haystack or not needle:
        return None
    idx = haystack.lower().find(needle.lower())
    if idx < 0:
        return None
    return idx, idx + len(needle)


def translate_fragment(text: str, source: str, target: str, provider_id: str | None) -> str:
    """Translate one fragment; '' on any failure (caller shows the miss marker)."""
    text = normalize(text)
    if not text:
        return ""
    try:
        r = tr.translate(text[:MAX_FRAGMENT], source=source, target=target, provider_id=provider_id)
        return normalize(r.text) if r.ok else ""
    except Exception:  # noqa: BLE001
        logutil.exc("spotlight translate")
        return ""


def words_only(text: str) -> bool:
    """Heuristic: translatable prose, not a bare number/punct (those rarely map)."""
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", text or ""))